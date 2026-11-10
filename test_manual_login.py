import sys
sys.path.insert(0, r"c:\Users\SrikarBalemarthy\audit-doc-stamper")
from fastapi.testclient import TestClient
from app.main import app
from app.db import init_db
from app.auth import init_default_users

init_db()
init_default_users()

client = TestClient(app)

# 1. Test GET /login
res = client.get("/login")
assert res.status_code == 200
html = res.text
assert "quickFill" not in html, "Found quickFill in HTML!"
assert "cto123" not in html, "Found hardcoded password in HTML!"
assert "accountant123" not in html
assert "hr123" not in html
assert 'placeholder="Enter your password"' in html
assert "selectRole" in html
print("1. GET /login: Clean login form with NO auto-login or prefilled passwords.")

# 2. Test Invalid Password
res_bad = client.post("/login", data={"username": "cto", "password": "wrongpassword"})
assert res_bad.status_code == 401
assert "Invalid username or password" in res_bad.text
print("2. POST /login with wrong password: Correctly rejected (401 Invalid username or password).")

# 3. Test Manual Valid Login for CTO
res_good_cto = client.post("/login", data={"username": "cto", "password": "cto123"}, follow_redirects=False)
assert res_good_cto.status_code == 303
assert res_good_cto.headers["Location"] == "/batches?filter=pending"
print("3. POST /login with manual CTO password: Authenticated & redirected to pending approvals.")

# 4. Test Manual Valid Login for Accountant
res_good_acc = client.post("/login", data={"username": "accountant", "password": "accountant123"}, follow_redirects=False)
assert res_good_acc.status_code == 303
assert res_good_acc.headers["Location"] == "/batch/new"
print("4. POST /login with manual Accountant password: Authenticated & redirected to batch creation.")

# 5. Test Manual Valid Login for HR
res_good_hr = client.post("/login", data={"username": "hr", "password": "hr123"}, follow_redirects=False)
assert res_good_hr.status_code == 303
assert res_good_hr.headers["Location"] == "/batches"
print("5. POST /login with manual HR password: Authenticated & redirected to audit monitor.")

print("\nALL LOGIN TESTS PASSED 100%!")

