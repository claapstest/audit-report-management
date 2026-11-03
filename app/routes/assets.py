from pathlib import Path

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from PIL import Image

from ..asset_version import ASSET_VERSION
from ..auth import require_user
from ..db import get_conn, DATA_DIR

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_version"] = ASSET_VERSION

ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg"}


def _asset_dir(user_id: int) -> Path:
    d = DATA_DIR / "assets" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_asset_path(user_id: int | None, kind: str) -> str | None:
    if user_id:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT file_path FROM assets WHERE user_id = ? AND kind = ?",
                (user_id, kind),
            ).fetchone()
        if row and Path(row["file_path"]).exists():
            return row["file_path"]

    # If signature, look for CTO-uploaded signature
    if kind == "signature":
        with get_conn() as conn:
            cto_row = conn.execute(
                """
                SELECT a.file_path FROM assets a
                JOIN users u ON u.id = a.user_id
                WHERE u.role = 'cto' AND a.kind = 'signature'
                ORDER BY a.updated_at DESC LIMIT 1
                """
            ).fetchone()
        if cto_row and Path(cto_row["file_path"]).exists():
            return cto_row["file_path"]

    # Look for most recent company asset of this kind
    with get_conn() as conn:
        latest = conn.execute(
            "SELECT file_path FROM assets WHERE kind = ? ORDER BY updated_at DESC LIMIT 1",
            (kind,),
        ).fetchone()
    if latest and Path(latest["file_path"]).exists():
        return latest["file_path"]

    # Fallback to predefined directories
    fallbacks = [
        DATA_DIR / "assets" / "1" / f"{kind}.png",
        DATA_DIR / "assets" / "2" / f"{kind}.png",
        DATA_DIR / "assets" / "default" / f"{kind}.png",
    ]
    for p in fallbacks:
        if p.exists():
            return str(p)

    return None


def clean_transparent_background(file_path: str, threshold: int = 220) -> None:
    """Removes near-white backgrounds from scans or photos of stamps/signatures."""
    try:
        with Image.open(file_path) as img:
            rgba = img.convert("RGBA")
            data = rgba.getdata()
            new_data = []
            for item in data:
                if item[0] > threshold and item[1] > threshold and item[2] > threshold:
                    new_data.append((255, 255, 255, 0))
                else:
                    new_data.append(item)
            rgba.putdata(new_data)
            rgba.save(file_path, "PNG")
    except Exception as exc:
        print(f"Failed to make transparent: {exc}")


def _save_asset(user_id: int, kind: str, upload: UploadFile, make_transparent: bool = False) -> str:
    dest = _asset_dir(user_id) / f"{kind}.png"
    content = upload.file.read()
    with dest.open("wb") as f:
        f.write(content)

    if make_transparent:
        clean_transparent_background(str(dest))

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO assets (user_id, kind, file_path, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, kind) DO UPDATE SET
                file_path = excluded.file_path,
                updated_at = datetime('now')
            """,
            (user_id, kind, str(dest)),
        )
    return str(dest)


@router.get("/assets")
def assets_page(request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    signature_path = get_asset_path(user["id"], "signature")
    stamp_path = get_asset_path(user["id"], "stamp")
    return templates.TemplateResponse(
        "assets.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "has_signature": bool(signature_path),
            "has_stamp": bool(stamp_path),
            "can_edit_signature": user_role in ("cto", "admin"),
            "can_edit_stamp": user_role in ("accountant", "hr", "admin"),
        },
    )


@router.post("/assets/signature")
def upload_signature(
    request: Request,
    user=Depends(require_user),
    file: UploadFile = File(...),
    make_transparent: bool = Form(False),
    next_url: str = Form("/assets"),
):
    if file.filename:
        _save_asset(user["id"], "signature", file, make_transparent=make_transparent)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/assets/stamp")
def upload_stamp(
    request: Request,
    user=Depends(require_user),
    file: UploadFile = File(...),
    make_transparent: bool = Form(False),
    next_url: str = Form("/assets"),
):
    if file.filename:
        _save_asset(user["id"], "stamp", file, make_transparent=make_transparent)
    return RedirectResponse(url=next_url, status_code=303)


@router.post("/api/assets/upload")
def api_upload_asset(
    request: Request,
    user=Depends(require_user),
    kind: str = Form(...),
    file: UploadFile = File(...),
    make_transparent: bool = Form(True),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    if kind not in ("signature", "stamp"):
        raise HTTPException(status_code=400, detail="Invalid asset kind")
    dest = _save_asset(user["id"], kind, file, make_transparent=make_transparent)
    import time
    return {
        "success": True,
        "kind": kind,
        "preview_url": f"/assets/preview/{kind}?t={int(time.time() * 1000)}"
    }


@router.post("/assets/clean-transparent/{kind}")
def clean_asset_transparent(kind: str, user=Depends(require_user)):
    path = get_asset_path(user["id"], kind)
    if path and Path(path).exists():
        clean_transparent_background(path)
    return RedirectResponse(url="/assets", status_code=303)


@router.get("/assets/preview/{kind}")
def preview_asset(kind: str, user=Depends(require_user)):
    path = get_asset_path(user["id"], kind)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path, media_type="image/png")
