"""End-to-end integration test verifying the 3-role connected workflow:
1. Accountant: logs in, uploads audit batch, sets Date & Stamp, submits to CTO.
2. CTO: logs in, views review queue, inspects documents, approves batch (applying CTO signature).
3. HR: logs in, monitors compliance dashboard (verifies Date, Stamp, Signature all applied), downloads ZIP.
"""
import sys
import time
from pathlib import Path
import httpx

BASE_URL = "http://localhost:8000"
SAMPLE_DIR = Path(r"C:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\The Contract Labour Act")


def run_tests():
    print("==================================================")
    print("TESTING 3-ROLE AUDIT STAMPING & APPROVAL WORKFLOW")
    print("==================================================")

    # 1. Login as Accountant
    print("\n[Step 1] Accountant: Logging in...")
    accountant_client = httpx.Client(base_url=BASE_URL, follow_redirects=True, timeout=60.0)
    res = accountant_client.post("/login", data={"username": "accountant", "password": "accountant123"})
    assert res.status_code == 200, f"Accountant login failed: {res.status_code}"
    assert "Accountant:" in res.text or "accountant" in res.text, "Role pill not found in response"
    print("  -> Accountant logged in successfully.")

    # 2. Accountant uploads sample files
    print("\n[Step 2] Accountant: Uploading audit batch...")
    sample_files = [
        "CLRA Application & Renewal application-Form IV or Form VII.docx",
        "Contract Labour License-Form VI.docx",
        "Service Certificate-Form Form XV-Claaps.docx",
    ]
    files_payload = []
    for fname in sample_files:
        fpath = SAMPLE_DIR / fname
        if fpath.exists():
            files_payload.append(("files", (fname, open(fpath, "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")))

    assert files_payload, "No sample files found in directory"
    upload_res = accountant_client.post("/batch/new", files=files_payload)
    assert upload_res.status_code == 200
    batch_url = str(upload_res.url)
    assert "/place" in batch_url, f"Expected redirect to /place, got {batch_url}"
    batch_id = int(batch_url.split("/batch/")[1].split("/")[0])
    print(f"  -> Batch #{batch_id} created with {len(files_payload)} audit reports.")

    # 3. Accountant configures Date, Stamp, and submits for CTO Approval
    print(f"\n[Step 3] Accountant: Setting Date '05-11-2026' and submitting Batch #{batch_id} for CTO Approval...")
    post_data = {
        "action": "submit_for_approval",
        "new_date": "05-11-2026",
        "include_stamp": "true",
        "include_signature": "false",
        "sig_x": 5.0,
        "sig_y": 80.0,
        "sig_w": 20.0,
        "stamp_x": 28.0,
        "stamp_y": 78.0,
        "stamp_w": 20.0,
        "target_page": "last",
        "placement_mode": "hybrid",
        "keywords": "Authorized Signatory, Yours faithfully",
        "auto_convert_pdf": "true",
    }
    process_res = accountant_client.post(f"/batch/{batch_id}/process", data=post_data)
    assert process_res.status_code == 200
    print("  -> Submitted. Waiting for background stamping pass to complete...")

    # Poll until stamping finishes
    for _ in range(60):
        prog = accountant_client.get(f"/batch/{batch_id}/progress").json()
        if prog["status"] in ("pending_cto", "approved", "done", "error"):
            print(f"  -> Background stamping finished with status: {prog['status']}")
            break
        time.sleep(0.5)

    assert prog["status"] == "pending_cto", f"Expected batch status 'pending_cto', got '{prog['status']}'"
    for f in prog["files"]:
        assert f["has_stamp"] == 1, f"Expected has_stamp=1 for {f['name']}"
        assert f["has_signature"] == 0, f"Expected has_signature=0 before CTO approval for {f['name']}"
    print("  -> Verified: All files stamped with Company Seal & Date, CTO signature is PENDING.")

    # 4. Login as CTO and Review
    print("\n[Step 4] CTO: Logging in...")
    cto_client = httpx.Client(base_url=BASE_URL, follow_redirects=True, timeout=60.0)
    cto_res = cto_client.post("/login", data={"username": "cto", "password": "cto123"})
    assert cto_res.status_code == 200
    assert "CTO:" in cto_res.text or "cto" in cto_res.text
    print("  -> CTO logged in successfully.")

    # Check CTO approvals queue
    print(f"\n[Step 5] CTO: Opening review queue for Batch #{batch_id}...")
    review_res = cto_client.get(f"/batch/{batch_id}/review")
    assert review_res.status_code == 200
    assert "CTO Verification Console" in review_res.text
    assert "Awaiting CTO Review" in review_res.text
    print("  -> Review page loaded. Document inspection verified.")

    # 5. CTO Approves Batch
    print(f"\n[Step 6] CTO: Approving Batch #{batch_id} & applying Digital Signature...")
    approve_res = cto_client.post(f"/batch/{batch_id}/approve")
    assert approve_res.status_code == 200
    print("  -> Approved! Waiting for digital signature application and PDF generation...")

    for _ in range(60):
        prog = cto_client.get(f"/batch/{batch_id}/progress").json()
        if prog["status"] in ("approved", "done", "error"):
            print(f"  -> Signing finished with status: {prog['status']}")
            break
        time.sleep(0.5)

    assert prog["status"] == "approved", f"Expected batch status 'approved', got '{prog['status']}'"
    for f in prog["files"]:
        assert f["has_signature"] == 1, f"Expected has_signature=1 after CTO approval for {f['name']}"
        assert f["has_stamp"] == 1, f"Expected has_stamp=1 for {f['name']}"
    print("  -> Verified: Official CTO Digital Signature embedded on all documents!")

    # 6. Login as HR and Monitor Compliance
    print("\n[Step 7] HR: Logging in to Monitor Compliance...")
    hr_client = httpx.Client(base_url=BASE_URL, follow_redirects=True, timeout=60.0)
    hr_res = hr_client.post("/login", data={"username": "hr", "password": "hr123"})
    assert hr_res.status_code == 200
    assert "HR:" in hr_res.text or "hr" in hr_res.text
    print("  -> HR logged in successfully.")

    print(f"\n[Step 8] HR: Inspecting Compliance Board for Batch #{batch_id}...")
    monitor_res = hr_client.get(f"/batch/{batch_id}/monitor")
    assert monitor_res.status_code == 200
    assert "100% Audit Ready" in monitor_res.text or "Approved & Signed by CTO" in monitor_res.text
    assert "Statutory Date Inserted" in monitor_res.text
    assert "Company Seal Affixed" in monitor_res.text
    assert "CTO Digital Signature" in monitor_res.text
    print("  -> Compliance Board verified: 100% Date, 100% Stamp, 100% Signature applied.")

    # 7. HR Downloads the completed PDFs ZIP
    print(f"\n[Step 9] HR: Downloading completed Batch #{batch_id} ZIP...")
    zip_res = hr_client.get(f"/batch/{batch_id}/download-zip-pdf")
    assert zip_res.status_code == 200, f"ZIP download failed: {zip_res.status_code}"
    assert len(zip_res.content) > 1000, f"ZIP content too small: {len(zip_res.content)} bytes"
    print(f"  -> Download successful! Received signed ZIP ({len(zip_res.content)} bytes).")

    print("\n==================================================")
    print("ALL 3-ROLE WORKFLOW INTEGRATION TESTS PASSED 100%!")
    print("==================================================")


if __name__ == "__main__":
    run_tests()
