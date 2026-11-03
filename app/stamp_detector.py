"""Existing Company Stamp / Seal Detector.

Scans incoming documents (PDF, Word .docx, Excel) to identify whether
an official circular/blue company seal stamp is already embedded.
Prevents redundant double-stamping on documents that already contain the seal.
"""
from pathlib import Path
import io
from PIL import Image, ImageStat
import fitz
import docx


def is_stamp_image(img: Image.Image) -> bool:
    """Evaluates whether a PIL image matches the geometry and color signature of a company seal."""
    try:
        w, h = img.size
        if min(w, h) < 140 or max(w, h) > 2000:
            return False

        aspect_ratio = float(w) / float(h)
        # Circular or square stamps have an aspect ratio close to 1.0
        if not (0.78 <= aspect_ratio <= 1.28):
            return False

        # Convert to RGB to analyze ink hue
        rgb_img = img.convert("RGB")
        stat = ImageStat.Stat(rgb_img)
        r_mean, g_mean, b_mean = stat.mean[:3]

        # Indian company seals use blue/purple ink on light/white paper
        # Header logos (like Claaps red banner) have R > B
        # Blue seals have B >= R
        if b_mean >= r_mean:
            return True

        # Secondary check for blue/purple ink pixels
        # Sample center region
        center_box = (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
        cropped = rgb_img.crop(center_box)
        c_stat = ImageStat.Stat(cropped)
        c_r, _, c_b = c_stat.mean[:3]
        if c_b >= c_r:
            return True

        return False
    except Exception:
        return False


def detect_existing_stamp(file_path: str | Path) -> tuple[bool, str]:
    """Inspects a file on disk. Returns (has_stamp: bool, detail: str)."""
    p = Path(file_path)
    if not p.exists():
        return False, "File does not exist"

    ext = p.suffix.lower()

    # 1. Word Documents (.docx)
    if ext == ".docx":
        try:
            d = docx.Document(str(p))
            for rel in d.part.rels.values():
                if "image" in rel.reltype:
                    blob = rel.target_part.blob
                    with Image.open(io.BytesIO(blob)) as img:
                        if is_stamp_image(img):
                            return True, f"Existing Company Stamp detected in Word document ({img.size[0]}x{img.size[1]}px)"
        except Exception as exc:
            return False, f"Could not inspect docx: {exc}"

    # 2. PDF Documents (.pdf)
    elif ext == ".pdf":
        try:
            with fitz.open(str(p)) as doc:
                for page_num, page in enumerate(doc):
                    for img_info in page.get_images():
                        xref = img_info[0]
                        base_img = doc.extract_image(xref)
                        with Image.open(io.BytesIO(base_img["image"])) as img:
                            if is_stamp_image(img):
                                return True, f"Existing Company Stamp detected on page {page_num + 1} ({img.size[0]}x{img.size[1]}px)"
        except Exception as exc:
            return False, f"Could not inspect pdf: {exc}"

    # 3. Excel Spreadsheets (.xlsx, .xls)
    elif ext in (".xlsx", ".xls"):
        # Statutory Excel files (Form F, Form T, Equal Remun) are raw templates
        # without embedded stamps, but if drawings exist we can inspect
        return False, "Excel raw workbook"

    return False, "No existing stamp found"

