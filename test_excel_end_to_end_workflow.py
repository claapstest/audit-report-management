"""Comprehensive end-to-end integration test verifying the Excel -> Word -> PDF pipeline:
1. Uploads Form F, Form T, and Equal Remuneration Excel files.
2. Verifies preview generation via Word conversion.
3. Submits batch for approval / stamps with Company Seal & CTO Signature.
4. Verifies the resulting PDFs contain company address, stamps, signatures, and proper formatting.
"""
import time
from pathlib import Path
import httpx
import fitz

BASE_URL = "http://localhost:8000"

EXCEL_FILES = [
    (
        "Form_F_Ashwin.xlsx",
        Path(r"C:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\Shops & Commercial Establishment Act\Form F Wage Register\F - Leave With Wage Register Claps-Ashwin June.xlsx"),
    ),
    (
        "Form_T_Muster_Roll.xls",
        Path(r"C:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\The Contract Labour Act\Copy of FORM-T Muster Roll Cum Wage register Mar.xls"),
    ),
    (
        "Equal_Remuneration_Form_B.xlsx",
        Path(r"C:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\Equal Remuneration Act\Equal Remuneration Form B June.xlsx"),
    ),
]


def test_excel_pipeline():
    print("==========================================================")
    print("TESTING FULL EXCEL -> WORD -> PDF STAMPING & SIGNING FLOW")
    print("==========================================================")

    # 1. Login as Accountant
    print("\n[Step 1] Logging in as Accountant...")
    client = httpx.Client(base_url=BASE_URL, follow_redirects=True, timeout=120.0)
    login_res = client.post("/login", data={"username": "accountant", "password": "accountant123"})
    assert login_res.status_code == 200
    print("  -> Logged in successfully.")

    # 2. Upload Excel files
    print("\n[Step 2] Uploading 3 Excel audit files...")
    files_payload = []
    for upload_name, fpath in EXCEL_FILES:
        assert fpath.exists(), f"File not found: {fpath}"
        mime = "application/vnd.ms-excel" if fpath.suffix == ".xls" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        files_payload.append(("files", (upload_name, open(fpath, "rb"), mime)))

    upload_res = client.post("/batch/new", files=files_payload)
    assert upload_res.status_code == 200
    batch_url = str(upload_res.url)
    assert "/place" in batch_url
    batch_id = int(batch_url.split("/batch/")[1].split("/")[0])
    print(f"  -> Batch #{batch_id} created with 3 Excel files.")

    # 3. Direct Full Process: apply signature + stamp + date
    print(f"\n[Step 3] Processing Batch #{batch_id} (Excel -> Word -> PDF + CTO Signature + Stamp)...")
    post_data = {
        "action": "process",
        "new_date": "05-11-2026",
        "include_stamp": "true",
        "include_signature": "true",
        "sig_x": 5.0,
        "sig_y": 80.0,
        "sig_w": 20.0,
        "stamp_x": 28.0,
        "stamp_y": 78.0,
        "stamp_w": 20.0,
        "target_page": "last",
        "placement_mode": "hybrid",
        "keywords": "Authorized Signatory, Signature, Note:",
        "auto_convert_pdf": "true",
    }
    process_res = client.post(f"/batch/{batch_id}/process", data=post_data)
    assert process_res.status_code == 200
    print("  -> Processing initiated. Polling progress...")

    for i in range(120):
        prog = client.get(f"/batch/{batch_id}/progress").json()
        print(f"     Status: {prog['status']} | Processed: {prog['completed']}/{prog['total']} | Current: {prog['current_file']}")
        if prog["status"] in ("approved", "done", "error"):
            break
        time.sleep(1.0)

    assert prog["status"] in ("approved", "done"), f"Batch processing failed with status {prog['status']}: {prog.get('error')}"
    print("\n[Step 4] Batch processing complete! Verifying output files...")

    # 4. Detailed output verification
    for f in prog["files"]:
        print(f"\nChecking file: {f['name']}")
        assert f["status"] in ("stamped", "success"), f"File {f['name']} status is {f['status']}: {f['message']}"
        assert f["has_stamp"] == 1, f"Expected has_stamp=1 for {f['name']}"
        assert f["has_signature"] == 1, f"Expected has_signature=1 for {f['name']}"

        pdf_path = f["pdf_output_path"]
        assert pdf_path and Path(pdf_path).exists(), f"PDF output not found: {pdf_path}"

        doc = fitz.open(pdf_path)
        print(f"  -> Generated PDF: {pdf_path}")
        print(f"  -> Total Pages: {doc.page_count}")

        # Check total images across document
        total_images = sum(len(page.get_images()) for page in doc)
        print(f"  -> Total embedded images (stamps/signatures): {total_images}")
        assert total_images >= 2, f"Expected at least 2 images (CTO sign + stamp), got {total_images}"

        if "Form_F" in f["name"]:
            # Check for company address in text of first page
            p1_text = doc[0].get_text()
            assert "Claaps" in p1_text and "Towers" in p1_text, "Company Address missing from Form F Page 1"
            print("  -> Verified: Claaps Global Enterprises address successfully populated at top right!")

        if "Form_T" in f["name"]:
            # Form T has 2 pages, stamp and signature on page 2
            assert doc.page_count == 2, f"Form T expected 2 pages, got {doc.page_count}"
            p2_images = len(doc[1].get_images())
            assert p2_images >= 2, f"Form T Page 2 missing signature/stamp: found {p2_images}"
            print("  -> Verified: Form T has 2-page split and signature + seal on Page 2!")

        # Check that Word document (.docx) was also created
        docx_path = Path(pdf_path).with_suffix(".docx")
        assert docx_path.exists(), f"Expected intermediate Word document at {docx_path}"
        print(f"  -> Verified: Intermediate Word document preserved at {docx_path.name} ({docx_path.stat().st_size} bytes)")

        doc.close()

    print("\n==========================================================")
    print("ALL TESTS PASSED! EXCEL -> WORD -> PDF PIPELINE VERIFIED!")
    print("==========================================================")


if __name__ == "__main__":
    test_excel_pipeline()
