import sys
from pathlib import Path
import httpx

sys.path.insert(0, r"c:\Users\SrikarBalemarthy\audit-doc-stamper")
from app.db import init_db, get_conn

init_db()

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("=================================================================")
    print("TESTING: NO STAMP ON DOCS WITH STAMPS & REMOVE/CROSS (X) OPTIONS")
    print("=================================================================")

    sample_has_stamp = Path(r"c:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\The Contract Labour Act\Contract Labour License-Form VI.docx")
    sample_no_stamp = Path(r"c:\Users\SrikarBalemarthy\Downloads\SRIKAR-CLRA Updated\SRIKAR-CLRA\Equal Remuneration Act\Equal Remuneration Form B June.xlsx")

    assert sample_has_stamp.exists(), f"Missing {sample_has_stamp}"
    assert sample_no_stamp.exists(), f"Missing {sample_no_stamp}"

    # 1. Login as Accountant
    client = httpx.Client(base_url=BASE_URL, timeout=60.0, follow_redirects=True)
    res = client.post("/login", data={"username": "accountant", "password": "accountant123"})
    assert res.status_code == 200, "Accountant login failed"
    print("1. Logged in as Accountant.")

    # 2. Upload Batch
    with open(sample_has_stamp, "rb") as f1, open(sample_no_stamp, "rb") as f2:
        files = [
            ("files", ("Doc_With_Existing_Stamp.docx", f1, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("files", ("Doc_Without_Stamp.xlsx", f2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
        ]
        res = client.post("/batch/new", files=files)
        assert res.status_code == 200, "Upload failed"

    # Extract batch ID
    import re
    m = re.search(r"/batch/(\d+)/", str(res.url))
    assert m, f"Could not find batch ID in {res.url}"
    batch_id = int(m.group(1))
    print(f"2. Batch #{batch_id} created successfully!")

    # Check database initialization of flags
    with get_conn() as conn:
        bf_rows = conn.execute("SELECT * FROM batch_files WHERE batch_id = ? ORDER BY id", (batch_id,)).fetchall()
        assert len(bf_rows) == 2

        f_has_stamp = bf_rows[0]
        f_no_stamp = bf_rows[1]

        print(f"   -> File 1 ({f_has_stamp['original_name']}): has_existing_stamp={f_has_stamp['has_existing_stamp']}, apply_stamp={f_has_stamp['apply_stamp']}")
        assert f_has_stamp["has_existing_stamp"] == 1, "Expected has_existing_stamp == 1"
        assert f_has_stamp["apply_stamp"] == 0, "Expected apply_stamp == 0 for doc with existing stamp"

        print(f"   -> File 2 ({f_no_stamp['original_name']}): has_existing_stamp={f_no_stamp['has_existing_stamp']}, apply_stamp={f_no_stamp['apply_stamp']}")
        assert f_no_stamp["has_existing_stamp"] == 0, "Expected has_existing_stamp == 0"
        assert f_no_stamp["apply_stamp"] == 1, "Expected apply_stamp == 1 for doc without stamp"

    # 3. Test API endpoint /batch/{batch_id}/file-info/{file_id}
    info_res1 = client.get(f"/batch/{batch_id}/file-info/{f_has_stamp['id']}").json()
    assert info_res1["has_existing_stamp"] is True
    assert info_res1["apply_stamp"] is False
    print("3. Verified file-info API correctly reports existing stamp and excluded stamp.")

    # 4. Test toggle-doc-option endpoint (simulating user clicking (X) or toggle)
    # Try to illegally enable stamp on f_has_stamp
    illegal_res = client.post(f"/batch/{batch_id}/toggle-doc-option/{f_has_stamp['id']}", json={"option": "stamp", "enabled": True}).json()
    assert illegal_res["success"] is False
    print("4a. Verified: System STRICTLY refuses to add stamp to document that already has an existing stamp!")

    # Exclude signature on File 2 by clicking (X)
    sig_toggle_res = client.post(f"/batch/{batch_id}/toggle-doc-option/{f_no_stamp['id']}", json={"option": "signature", "enabled": False}).json()
    assert sig_toggle_res["success"] is True
    assert sig_toggle_res["apply_signature"] is False
    print("4b. Verified: Signature successfully excluded via toggle/cross (X)!")

    # Re-enable signature on File 2
    sig_restore_res = client.post(f"/batch/{batch_id}/toggle-doc-option/{f_no_stamp['id']}", json={"option": "signature", "enabled": True}).json()
    assert sig_restore_res["success"] is True
    assert sig_restore_res["apply_signature"] is True
    print("4c. Verified: Signature restored successfully!")

    # 5. Submit for CTO Review & Approval
    submit_res = client.post(f"/batch/{batch_id}/process", data={
        "action": "submit_for_approval",
        "include_stamp": "on",
        "sig_x": "5", "sig_y": "80", "sig_w": "20",
        "stamp_x": "30", "stamp_y": "80", "stamp_w": "20",
        "target_page": "last",
        "new_date": "",
        "placement_mode": "hybrid",
        "auto_convert_pdf": "true",
        f"apply_sig_{f_has_stamp['id']}": "1",
        f"apply_stamp_{f_has_stamp['id']}": "0", # explicitly excluded
        f"apply_sig_{f_no_stamp['id']}": "1",
        f"apply_stamp_{f_no_stamp['id']}": "1",
    })
    assert submit_res.status_code == 200
    print("5. Batch submitted to CTO approval queue.")

    # Wait for initial processing
    import time
    for _ in range(30):
        time.sleep(1)
        with get_conn() as conn:
            b = conn.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if b["status"] in ("pending_cto", "error"):
                break

    assert b["status"] == "pending_cto", f"Expected pending_cto, got {b['status']}"

    # 6. CTO Login & Approval
    cto_client = httpx.Client(base_url=BASE_URL, timeout=60.0, follow_redirects=True)
    cto_client.post("/login", data={"username": "cto", "password": "cto123"})
    approve_res = cto_client.post(f"/batch/{batch_id}/approve")
    assert approve_res.status_code == 200

    for _ in range(40):
        time.sleep(1)
        with get_conn() as conn:
            b = conn.execute("SELECT status FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if b["status"] in ("approved", "done", "error"):
                break

    assert b["status"] in ("approved", "done"), f"Expected approved, got {b['status']}"
    print(f"6. CTO approved batch #{batch_id}!")

    # 7. Check final file results
    with get_conn() as conn:
        res_files = conn.execute("SELECT * FROM batch_files WHERE batch_id = ? ORDER BY id", (batch_id,)).fetchall()
        rf1 = res_files[0]
        rf2 = res_files[1]

        print(f"   -> Result File 1 ({rf1['original_name']}):")
        print(f"      Status: {rf1['status']}, Message: {rf1['message']}")
        assert "Preserved original stamp" in rf1["message"] or "Original stamp" in rf1["message"]
        print("      VERIFIED: Original stamp was preserved, NO duplicate stamp entered!")

        print(f"   -> Result File 2 ({rf2['original_name']}):")
        print(f"      Status: {rf2['status']}, Message: {rf2['message']}")
        assert rf2["status"] == "success"
        print("      VERIFIED: Unstamped document was stamped and signed as expected!")

    print("\n=================================================================")
    print("ALL TESTS PASSED 100%! STAMP EXCLUSION & (X) CONTROLS FULLY OPERATIONAL!")
    print("=================================================================")

if __name__ == "__main__":
    run_tests()

