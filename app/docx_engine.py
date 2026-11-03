from pathlib import Path
import re

from docx import Document
from docx.shared import Inches, Pt

from .date_patterns import (
    DEFAULT_DATE_REGEX,
    EXCLUDE_CONTEXT_WORDS,
    FOR_MONTH_YEAR_REGEX,
    LONG_DATE_REGEX,
    SHORT_DATE_REGEX,
    WAGE_PERIOD_REGEX,
    compile_pattern,
    parse_date_input,
)
from .pdf_engine import DEFAULT_KEYWORDS, compile_keyword_regexes

SIGNATURE_MARKER = re.compile(r"\[SIGNATURE\]", re.IGNORECASE)


def _available_width_inches(doc: Document) -> float:
    try:
        section = doc.sections[0]
        width_emu = section.page_width - section.left_margin - section.right_margin
        return width_emu / 914400  # EMU per inch
    except Exception:
        return 6.5  # standard letter text width fallback


def _find_target_paragraph(doc: Document, keywords: list[str] | None = None):
    # 1. Check for explicit marker [SIGNATURE]
    for p in doc.paragraphs:
        if SIGNATURE_MARKER.search(p.text):
            return p, "[SIGNATURE]"

    # 2. Check for configured keywords in order of priority
    kw_list = keywords if keywords else DEFAULT_KEYWORDS
    patterns = compile_keyword_regexes(kw_list)

    # Collect all paragraphs including tables and headers/footers
    all_paras = list(doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    all_paras.append(p)

    # Search each pattern in order of specificity
    for pat, label in patterns:
        for p in reversed(all_paras):
            txt = p.text.strip()
            if not txt:
                continue
            # Never place on employee signature lines
            if "employee" in txt.lower() and "employer" not in txt.lower():
                continue
            if pat.search(txt):
                if label.lower() in ("remarks", "for claaps global enterprises", "for claaps", "yours faithfully"):
                    p_idx = -1
                    try:
                        p_idx = doc.paragraphs.index(p)
                    except ValueError:
                        pass
                    if p_idx >= 0 and p_idx + 1 < len(doc.paragraphs):
                        next_p = doc.paragraphs[p_idx + 1]
                        if not next_p.text.strip():
                            return next_p, f"{label} (Below line)"
                return p, txt

    return None, None


def _prune_empty_paragraphs_before(target_p):
    """Remove empty spacer paragraphs immediately preceding the signatory paragraph
    that were left in the Word template for manual physical signing."""
    p_elem = target_p._element.getprevious()
    while p_elem is not None:
        prev_p = p_elem
        p_elem = p_elem.getprevious()
        if prev_p.tag.endswith("p"):
            prev_text = "".join(prev_p.itertext()).strip()
            if not prev_text:
                prev_p.getparent().remove(prev_p)
            else:
                break


def _prune_trailing_empty_paragraphs(doc: Document):
    """Remove trailing empty paragraphs at the end of the document to prevent extra blank pages."""
    for p in list(reversed(doc.paragraphs)):
        if not p.text.strip():
            p._element.getparent().remove(p._element)
        else:
            break


def _insert_signature_block(
    doc: Document,
    signature_path: str | None,
    stamp_path: str | None,
    width_pct: float,
    keywords: list[str] | None = None,
) -> tuple[str, bool]:
    avail_width = _available_width_inches(doc)
    # Set proportional, compact image sizes so the document never overflows onto a 2nd page
    raw_w = max(avail_width * (width_pct / 100.0), 0.75)
    sig_width = Inches(min(raw_w, 1.35))
    stamp_width = Inches(min(raw_w * 0.9, 1.15))

    target_p, matched_text = _find_target_paragraph(doc, keywords)

    # Prune trailing empty lines at document end
    _prune_trailing_empty_paragraphs(doc)

    if target_p is not None and matched_text == "[SIGNATURE]":
        for run in list(target_p.runs):
            run.text = ""
        insert_p = target_p
        is_fallback = False
    elif target_p is not None and "(Below line)" in matched_text:
        insert_p = target_p
        is_fallback = False
    elif target_p is not None:
        # Collapse excessive blank spacer lines above the signatory line
        _prune_empty_paragraphs_before(target_p)
        insert_p = target_p.insert_paragraph_before()
        is_fallback = False
    else:
        insert_p = doc.add_paragraph()
        matched_text = "End of document"
        is_fallback = True

    # Tight formatting so the signature and stamp sit cleanly above the signatory line
    insert_p.paragraph_format.space_before = Pt(2)
    insert_p.paragraph_format.space_after = Pt(2)
    insert_p.paragraph_format.line_spacing = 1.0
    insert_p.paragraph_format.keep_with_next = True

    run = insert_p.add_run()
    if signature_path and Path(signature_path).exists():
        run.add_picture(signature_path, width=sig_width)
        insert_p.add_run("   ")
    if stamp_path and Path(stamp_path).exists():
        insert_p.add_run().add_picture(stamp_path, width=stamp_width)

    # Also keep target_p with following line (e.g. Place: Hyderabad Date: ...)
    if target_p is not None:
        target_p.paragraph_format.space_before = Pt(2)
        target_p.paragraph_format.space_after = Pt(0)
        target_p.paragraph_format.keep_with_next = True

        # If there is a following paragraph (like Place / Date), ensure it stays compact and attached
        try:
            p_idx = doc.paragraphs.index(target_p)
            for j in range(p_idx + 1, min(p_idx + 3, len(doc.paragraphs))):
                sub_p = doc.paragraphs[j]
                if any(k in sub_p.text.lower() for k in ["place", "date"]):
                    sub_p.paragraph_format.space_before = Pt(1)
                    sub_p.paragraph_format.space_after = Pt(0)
                    sub_p.paragraph_format.keep_with_next = True
        except ValueError:
            pass

    return matched_text or "End of document", is_fallback


def _smart_replace_paragraph_date(
    p,
    parsed_date: dict | None,
    fallback_date: str,
    pattern: re.Pattern,
    is_top: bool = False,
    is_bottom: bool = False,
    row_context: str = "",
) -> int:
    txt = p.text
    if not txt.strip():
        return 0
    full_context = (txt + " " + row_context).lower()
    for excl in EXCLUDE_CONTEXT_WORDS:
        if excl in full_context:
            return 0  # Preserve employee DOB, appointment, joining, tenure!

    new_txt = txt
    replaced = 0

    if parsed_date:
        # 1. Wage period heading (Employment card)
        if WAGE_PERIOD_REGEX.search(new_txt):
            new_txt, n = WAGE_PERIOD_REGEX.subn(rf"\g<1>{parsed_date['wage_period']}", new_txt)
            replaced += n

        # 2. "For <Month> <Year>" (Maternity Benefit Act top heading)
        elif FOR_MONTH_YEAR_REGEX.search(new_txt) and is_top:
            new_txt, n = FOR_MONTH_YEAR_REGEX.subn(rf"\g<1>{parsed_date['month_year']}", new_txt)
            replaced += n

        # 3. Signatory / bottom date (lines with Date:, Date., Place: Hyderabad Date:)
        elif re.search(r"\bdate\s*[:.]?\s*", new_txt, re.IGNORECASE) or is_bottom:
            if SHORT_DATE_REGEX.search(new_txt):
                new_txt, n = SHORT_DATE_REGEX.subn(parsed_date["short_hyphen"], new_txt)
                replaced += n
            elif LONG_DATE_REGEX.search(new_txt):
                new_txt, n = LONG_DATE_REGEX.subn(parsed_date["short_hyphen"], new_txt)
                replaced += n

        # 4. Top document date (e.g. standalone "July 05, 2026")
        elif is_top:
            if LONG_DATE_REGEX.search(new_txt):
                new_txt, n = LONG_DATE_REGEX.subn(parsed_date["long"], new_txt)
                replaced += n
            elif SHORT_DATE_REGEX.search(new_txt):
                new_txt, n = SHORT_DATE_REGEX.subn(parsed_date["short_hyphen"], new_txt)
                replaced += n
    else:
        # Custom user regex pattern fallback
        if pattern.search(new_txt):
            new_txt, n = pattern.subn(fallback_date, new_txt)
            replaced += n

    if replaced > 0 and new_txt != txt:
        if p.runs:
            p.runs[0].text = new_txt
            for extra in p.runs[1:]:
                extra.text = ""
        else:
            p.add_run(new_txt)
        return replaced
    return 0


def _replace_dates(doc: Document, new_date: str, pattern: re.Pattern) -> int:
    count = 0
    parsed = parse_date_input(new_date)

    # 1. Paragraphs
    total_p = len(doc.paragraphs)
    for i, p in enumerate(doc.paragraphs):
        is_top = (i < 10)
        is_bottom = (i >= total_p - 15)
        count += _smart_replace_paragraph_date(
            p, parsed, new_date, pattern, is_top=is_top, is_bottom=is_bottom
        )

    # 2. Table Cells (e.g. Appointment Order Form Q)
    for table in doc.tables:
        for row in table.rows:
            row_context = " ".join(c.text.strip() for c in row.cells)
            for cell in row.cells:
                for p in cell.paragraphs:
                    count += _smart_replace_paragraph_date(
                        p, parsed, new_date, pattern, is_top=False, is_bottom=True, row_context=row_context
                    )

    # 3. Headers and Footers
    for section in doc.sections:
        for part in (section.header, section.footer):
            for p in part.paragraphs:
                count += _smart_replace_paragraph_date(
                    p, parsed, new_date, pattern, is_top=False, is_bottom=False
                )

    return count


def process_docx(
    input_path: str,
    output_path: str,
    signature_path: str | None,
    stamp_path: str | None,
    image_width_pct: float,
    new_date: str | None,
    date_pattern: str | None,
    keywords: list[str] | None = None,
) -> tuple[bool, str, dict]:
    meta: dict = {"detected_page": None, "detected_text": None, "is_fallback": 0}
    try:
        doc = Document(input_path)

        # Normalize excessive paragraph spacing on body paragraphs to prevent 1-page letters overflowing
        for p in doc.paragraphs:
            if p.paragraph_format.space_after and p.paragraph_format.space_after.pt > 6:
                p.paragraph_format.space_after = Pt(3)

        matched_label = "End of document"
        is_fallback = False

        if signature_path or stamp_path:
            matched_label, is_fallback = _insert_signature_block(
                doc, signature_path, stamp_path, image_width_pct, keywords
            )
            meta["detected_text"] = matched_label
            meta["is_fallback"] = 1 if is_fallback else 0

        date_count = 0
        if new_date:
            pattern = compile_pattern(date_pattern)
            date_count = _replace_dates(doc, new_date, pattern)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        doc.save(output_path)

        msg = (
            f"Signed & stamped (Found '{matched_label}')"
            if not is_fallback
            else "Signed & stamped (Appended to document)"
        )
        if new_date and date_count == 0:
            msg += ", but no date text was found to replace"

        return True, msg, meta
    except Exception as exc:  # noqa: BLE001
        return False, f"Error: {exc}", meta
