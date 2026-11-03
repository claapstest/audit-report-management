import sys
import shutil
import subprocess
from pathlib import Path

HAS_WIN32 = False
if sys.platform == "win32":
    try:
        import pythoncom
        import win32com.client as win32
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False

WD_FORMAT_PDF = 17


def convert_to_pdf(input_path: str, output_path: str) -> tuple[bool, str]:
    """
    Converts a .docx file to PDF.
    - On Windows: Uses Word COM automation if available.
    - On Linux / Docker (Render): Uses headless LibreOffice (soffice).
    """
    input_abs = Path(input_path).resolve()
    output_abs = Path(output_path).resolve()
    output_abs.parent.mkdir(parents=True, exist_ok=True)

    # 1. Try Windows Word COM if running on Windows with Office installed
    if HAS_WIN32:
        pythoncom.CoInitialize()
        word = None
        doc = None
        try:
            word = win32.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(input_abs), ReadOnly=True)
            doc.SaveAs(str(output_abs), FileFormat=WD_FORMAT_PDF)
            return True, "OK"
        except Exception:
            pass  # Fall back to LibreOffice if COM fails
        finally:
            try:
                if doc is not None:
                    doc.Close(False)
            except Exception:
                pass
            try:
                if word is not None:
                    word.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    # 2. Try LibreOffice (Linux / Render / Docker or Windows fallback)
    soffice_cmd = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice_cmd:
        try:
            out_dir = output_abs.parent
            res = subprocess.run(
                [soffice_cmd, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(input_abs)],
                capture_output=True,
                text=True,
                timeout=90,
            )
            expected_pdf = out_dir / f"{input_abs.stem}.pdf"
            if expected_pdf.exists():
                if expected_pdf.resolve() != output_abs.resolve():
                    shutil.move(str(expected_pdf), str(output_abs))
                return True, "OK"
            return False, f"LibreOffice conversion failed: {res.stderr or res.stdout}"
        except Exception as exc:
            return False, f"LibreOffice execution error: {exc}"

    return False, "Neither MS Word (Windows) nor LibreOffice (Linux/Docker) is available for conversion."
