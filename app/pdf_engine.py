from pathlib import Path
import re

import fitz  # PyMuPDF
from PIL import Image

from .date_patterns import (
    DEFAULT_DATE_REGEX,
    EXCLUDE_CONTEXT_WORDS,
    LONG_DATE_REGEX,
    SHORT_DATE_REGEX,
    compile_pattern,
    parse_date_input,
)

DEFAULT_KEYWORDS = [
    "Signature of the Employer",
    "Signature of Employer",
    "Employer Signature",
    "Signature of the Contractor",
    "Signature of Contractor",
    "Contractor Signature",
    "Authorized Signatory",
    "Authorised Signatory",
    "Chief Technology Officer",
    "CTO",
    "Director",
    "Seal of the Establishment",
    "For Claaps Global Enterprises",
    "For Claaps",
    "Yours faithfully",
    "Remarks",
    "Signature",
    "Signatory",
]


def parse_keywords(kw_str: str | None) -> list[str]:
    if not kw_str or not kw_str.strip():
        return list(DEFAULT_KEYWORDS)
    parts = [k.strip() for k in kw_str.split(",") if k.strip()]
    return parts if parts else list(DEFAULT_KEYWORDS)


def compile_keyword_regexes(keywords: list[str]) -> list[tuple[re.Pattern, str]]:
    patterns = []
    for kw in keywords:
        clean = kw.strip()
        if not clean:
            continue
        if re.search(r"authori[sz]ed\s+signatory", clean, re.I):
            pat = re.compile(r"\bauthori[sz]ed\s+signatory\b", re.I)
        elif clean.lower() == "cto":
            pat = re.compile(r"\bCTO\b", re.I)
        else:
            pat = re.compile(r"\b" + re.escape(clean) + r"\b", re.I)
        patterns.append((pat, clean))
    return patterns


def get_page_count(pdf_path: str) -> int:
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def resolve_page_index(page_count: int, target_page: str) -> int:
    if target_page == "last":
        return page_count - 1
    try:
        idx = int(target_page) - 1
    except (TypeError, ValueError):
        idx = page_count - 1
    return max(0, min(idx, page_count - 1))


def render_page_png(pdf_path: str, page_index: int = 0, zoom: float = 1.5) -> bytes:
    with fitz.open(pdf_path) as doc:
        page_index = max(0, min(page_index, doc.page_count - 1))
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pix.tobytes("png")


def _image_aspect_ratio(image_path: str) -> float:
    with Image.open(image_path) as img:
        w, h = img.size
    return h / w if w else 1.0


def _pct_rect_to_page_rect(page: fitz.Page, x_pct: float, y_pct: float, w_pct: float, image_path: str) -> fitz.Rect:
    """x_pct/y_pct/w_pct are 0-100 relative to the page; height is derived from image aspect ratio."""
    pw, ph = page.rect.width, page.rect.height
    x0 = pw * (x_pct / 100.0)
    y0 = ph * (y_pct / 100.0)
    w = pw * (w_pct / 100.0)
    h = w * _image_aspect_ratio(image_path)
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def _overlay_images(doc: fitz.Document, page_index: int, placements: list[dict]) -> None:
    page = doc[page_index]
    for p in placements:
        rect = _pct_rect_to_page_rect(page, p["x"], p["y"], p["w"], p["image_path"])
        page.insert_image(rect, filename=p["image_path"])


def find_keyword_in_document(
    doc: fitz.Document, keywords: list[str] | None = None
) -> tuple[int, fitz.Rect, str] | None:
    """Locate the highest-priority matching keyword line in the document.
    Prioritizes specific keywords over generic ones, and checks the last page first."""
    kw_list = keywords if keywords else DEFAULT_KEYWORDS
    patterns = compile_keyword_regexes(kw_list)

    # Search order: last page first, then from end backwards
    pages_to_check = [doc.page_count - 1]
    for p in range(doc.page_count - 2, -1, -1):
        pages_to_check.append(p)

    for pat, label in patterns:
        for page_index in pages_to_check:
            page = doc[page_index]
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(s.get("text", "") for s in spans)
                    if not line_text.strip():
                        continue
                    # Never accidentally place on employee signature lines
                    if "employee" in line_text.lower() and "employer" not in line_text.lower():
                        continue
                    if pat.search(line_text):
                        x0 = min(s["bbox"][0] for s in spans)
                        y0 = min(s["bbox"][1] for s in spans)
                        x1 = max(s["bbox"][2] for s in spans)
                        y1 = max(s["bbox"][3] for s in spans)
                        return page_index, fitz.Rect(x0, y0, x1, y1), line_text.strip()
    return None


def detect_keywords_on_page(
    pdf_path: str, page_index: int, keywords: list[str] | None = None
) -> list[dict]:
    """Returns all keyword matches on the specified page with percentage coordinates for UI preview."""
    kw_list = keywords if keywords else DEFAULT_KEYWORDS
    patterns = compile_keyword_regexes(kw_list)
    results = []

    try:
        with fitz.open(pdf_path) as doc:
            if page_index < 0 or page_index >= doc.page_count:
                return []
            page = doc[page_index]
            pw, ph = page.rect.width, page.rect.height
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = "".join(s.get("text", "") for s in spans)
                    if not line_text.strip():
                        continue
                    if "employee" in line_text.lower() and "employer" not in line_text.lower():
                        continue
                    for pat, label in patterns:
                        if pat.search(line_text):
                            x0 = min(s["bbox"][0] for s in spans)
                            y0 = min(s["bbox"][1] for s in spans)
                            x1 = max(s["bbox"][2] for s in spans)
                            y1 = max(s["bbox"][3] for s in spans)
                            results.append({
                                "text": line_text.strip(),
                                "matched_keyword": label,
                                "x0_pct": round((x0 / pw) * 100, 2),
                                "y0_pct": round((y0 / ph) * 100, 2),
                                "x1_pct": round((x1 / pw) * 100, 2),
                                "y1_pct": round((y1 / ph) * 100, 2),
                            })
                            break
    except Exception:
        return []
    return results


def _replace_dates(doc: fitz.Document, new_date: str, pattern: re.Pattern) -> int:
    total_replacements = 0
    parsed = parse_date_input(new_date)

    for page_idx, page in enumerate(doc):
        pw, ph = page.rect.width, page.rect.height
        text_dict = page.get_text("dict")
        pending = []  # (rect, size, font, color, replacement_text)

        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans)
                if not line_text.strip():
                    continue

                line_lower = line_text.lower()
                # Skip employee DOB, tenure, appointment, joining lines
                if any(excl in line_lower for excl in EXCLUDE_CONTEXT_WORDS):
                    continue

                line_y0 = min(s["bbox"][1] for s in spans)
                is_top = (page_idx == 0 and line_y0 < ph * 0.3)
                is_bottom = (line_y0 > ph * 0.7 or re.search(r"\bdate\s*[:.]?\s*", line_text, re.I))

                for span in spans:
                    full_text = span.get("text", "")
                    if not full_text:
                        continue
                    for m in pattern.finditer(full_text):
                        matched_str = m.group(0)
                        rep_text = new_date
                        if parsed:
                            if is_top and LONG_DATE_REGEX.search(matched_str):
                                rep_text = parsed["long"]
                            elif is_bottom:
                                rep_text = parsed["short_hyphen"]
                            elif SHORT_DATE_REGEX.search(matched_str):
                                rep_text = parsed["short_hyphen"]
                            elif LONG_DATE_REGEX.search(matched_str):
                                rep_text = parsed["long"]

                        bbox = span["bbox"]
                        span_len = len(full_text)
                        start_frac = m.start() / span_len
                        end_frac = m.end() / span_len
                        x0 = bbox[0] + (bbox[2] - bbox[0]) * start_frac
                        x1 = bbox[0] + (bbox[2] - bbox[0]) * end_frac
                        rect = fitz.Rect(x0, bbox[1], x1, bbox[3])
                        color_int = span.get("color", 0)
                        color = (
                            ((color_int >> 16) & 255) / 255.0,
                            ((color_int >> 8) & 255) / 255.0,
                            (color_int & 255) / 255.0,
                        )
                        pending.append((rect, span.get("size", 10), span.get("font", "helv"), color, rep_text))

        if not pending:
            continue

        for rect, _size, _font, _color, _rep in pending:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        for rect, size, font, color, rep_text in pending:
            fontsize = max(size * 0.92, 6)
            baseline_y = rect.y1 - size * 0.2
            page.insert_text(
                (rect.x0, baseline_y),
                rep_text,
                fontsize=fontsize,
                color=color,
                fontname="helv",
            )
            total_replacements += 1

    return total_replacements


def process_pdf(
    input_path: str,
    output_path: str,
    target_page: str,
    signature: dict | None,
    stamp: dict | None,
    new_date: str | None,
    date_pattern: str | None,
    placement_mode: str = "hybrid",
    keywords: list[str] | None = None,
) -> tuple[bool, str, dict]:
    """
    signature/stamp dicts: {x, y, w, image_path} in 0-100 page-percent coordinates.
    Returns: (success: bool, message: str, meta: dict)
    """
    meta: dict = {"detected_page": None, "detected_text": None, "is_fallback": 0}
    try:
        with fitz.open(input_path) as doc:
            has_sig = bool(signature and signature.get("image_path"))
            has_stamp = bool(stamp and stamp.get("image_path"))

            if has_sig or has_stamp:
                hit = None
                if placement_mode == "hybrid":
                    hit = find_keyword_in_document(doc, keywords)

                if hit is not None:
                    page_index, auth_rect, matched_text = hit
                    page = doc[page_index]
                    pw, ph = page.rect.width, page.rect.height

                    meta["detected_page"] = page_index + 1
                    meta["detected_text"] = matched_text
                    meta["is_fallback"] = 0

                    sig_x0 = 0.0
                    sig_y0 = 0.0
                    sig_w_pts = 0.0

                    # 1. Position CTO Signature
                    if has_sig:
                        sig_w_pts = pw * (float(signature["w"]) / 100.0)
                        sig_h_pts = sig_w_pts * _image_aspect_ratio(signature["image_path"])

                        # Center horizontally over the matched signatory line
                        sig_x0 = auth_rect.x0 + (auth_rect.width - sig_w_pts) / 2.0
                        sig_x0 = max(15.0, min(sig_x0, pw - sig_w_pts - 15.0))

                        # Bottom edge of signature sits 6pt above text top edge
                        sig_y0 = max(10.0, auth_rect.y0 - 6.0 - sig_h_pts)
                        sig_rect = fitz.Rect(sig_x0, sig_y0, sig_x0 + sig_w_pts, sig_y0 + sig_h_pts)
                        page.insert_image(sig_rect, filename=signature["image_path"])

                    # 2. Position Company Stamp
                    if has_stamp:
                        stamp_w_pts = pw * (float(stamp["w"]) / 100.0)
                        stamp_h_pts = stamp_w_pts * _image_aspect_ratio(stamp["image_path"])

                        if has_sig:
                            # Place beside signature (right side if fits, else left side)
                            if sig_x0 + sig_w_pts + stamp_w_pts + 10.0 <= pw:
                                stamp_x0 = sig_x0 + sig_w_pts + 6.0
                            elif sig_x0 - stamp_w_pts - 6.0 >= 10.0:
                                stamp_x0 = sig_x0 - stamp_w_pts - 6.0
                            else:
                                stamp_x0 = max(10.0, min(pw - stamp_w_pts - 10.0, sig_x0 + sig_w_pts * 0.7))
                            stamp_y0 = max(10.0, auth_rect.y0 - (stamp_h_pts * 0.65))
                        else:
                            stamp_x0 = max(15.0, min(pw - stamp_w_pts - 15.0, auth_rect.x0 + (auth_rect.width - stamp_w_pts) / 2.0))
                            stamp_y0 = max(10.0, auth_rect.y0 - (stamp_h_pts * 0.65))

                        stamp_rect = fitz.Rect(stamp_x0, stamp_y0, stamp_x0 + stamp_w_pts, stamp_y0 + stamp_h_pts)
                        page.insert_image(stamp_rect, filename=stamp["image_path"])

                    msg = f"Signed & stamped (Found '{matched_text}' on page {page_index + 1})"
                else:
                    # Fallback to visual manual placement on target page
                    page_index = resolve_page_index(doc.page_count, target_page)
                    placements = []
                    if has_sig:
                        placements.append(signature)
                    if has_stamp:
                        placements.append(stamp)
                    _overlay_images(doc, page_index, placements)

                    meta["detected_page"] = page_index + 1
                    meta["is_fallback"] = 1 if placement_mode == "hybrid" else 0
                    msg = (
                        f"Signed & stamped (Fallback to visual position on page {page_index + 1})"
                        if placement_mode == "hybrid"
                        else f"Signed & stamped (Placed on page {page_index + 1})"
                    )
            else:
                msg = "Processed (no signature or stamp requested)"

            date_count = 0
            if new_date:
                pattern = compile_pattern(date_pattern)
                date_count = _replace_dates(doc, new_date, pattern)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            doc.save(output_path)

            if new_date and date_count == 0:
                msg += ", but no date text was found to replace"

            return True, msg, meta
    except Exception as exc:  # noqa: BLE001
        return False, f"Error: {exc}", meta
