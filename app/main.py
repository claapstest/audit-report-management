import secrets
from pathlib import Path

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .asset_version import ASSET_VERSION
from .db import init_db, DATA_DIR
from .auth import get_user_by_username, verify_password, current_user, init_default_users
from .routes import assets as assets_routes
from .routes import batch as batch_routes
from .routes import categories as categories_routes

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY_PATH = DATA_DIR / "secret_key.txt"


def _load_or_create_secret_key() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_KEY_PATH.exists():
        return SECRET_KEY_PATH.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key)
    return key


app = FastAPI(title="ARS - Audit Report Stamping")
app.add_middleware(SessionMiddleware, secret_key=_load_or_create_secret_key(), same_site="lax")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_version"] = ASSET_VERSION

app.include_router(assets_routes.router)
app.include_router(batch_routes.router)
app.include_router(categories_routes.router)


@app.on_event("startup")
def on_startup():
    init_db()
    init_default_users()


@app.exception_handler(HTTPException)
async def redirect_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in (302, 303) and exc.headers and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=exc.status_code)
    raise exc


def _role_redirect_url(role: str) -> str:
    if role == "cto":
        return "/batches?filter=pending"
    elif role == "hr":
        return "/batches"
    return "/batch/new"


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    user = current_user(request)
    if user:
        role = user["role"] if "role" in user.keys() else "hr"
        return RedirectResponse(url=_role_redirect_url(role), status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    user = current_user(request)
    if user:
        role = user["role"] if "role" in user.keys() else "hr"
        return RedirectResponse(url=_role_redirect_url(role), status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = get_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password"},
            status_code=401,
        )
    role = user["role"] if "role" in user.keys() else "hr"
    request.session["user_id"] = user["id"]
    request.session["username"] = user["username"]
    request.session["role"] = role
    return RedirectResponse(url=_role_redirect_url(role), status_code=303)


@app.get("/approvals")
def approvals_redirect(request: Request):
    return RedirectResponse(url="/batches?filter=pending", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
