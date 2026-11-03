import io
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, StreamingResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates

from ..asset_version import ASSET_VERSION
from ..auth import require_user
from ..db import get_conn, DATA_DIR
from .. import pdf_engine, docx_engine, docx_to_pdf, excel_engine
from ..stamp_detector import detect_existing_stamp
from .assets import get_asset_path
from .categories import list_categories, match_category

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_version"] = ASSET_VERSION

ALLOWED_EXT = {".pdf", ".docx", ".xlsx", ".xls"}


def _get_batch(batch_id: int, user_id: int | None = None):
    with get_conn() as conn:
        batch = conn.execute(
            """
            SELECT b.*,
                   COALESCE(u_sub.username, u_orig.username) AS submitted_by_username,
                   COALESCE(u_sub.full_name, u_orig.full_name, u_orig.username) AS submitted_by_fullname,
                   COALESCE(u_sub.role, u_orig.role, 'accountant') AS submitted_by_role,
                   u_app.username AS approved_by_username,
                   COALESCE(u_app.full_name, u_app.username) AS approved_by_fullname
            FROM batches b
            LEFT JOIN users u_sub ON u_sub.id = b.submitted_by
            LEFT JOIN users u_orig ON u_orig.id = b.user_id
            LEFT JOIN users u_app ON u_app.id = b.approved_by
            WHERE b.id = ?
            """,
            (batch_id,),
        ).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        files = conn.execute(
            """
            SELECT bf.*, c.name AS category_name, c.task AS category_task,
                   c.needs_date AS category_needs_date, c.needs_signature AS category_needs_signature,
                   c.needs_stamp AS category_needs_stamp, c.needs_pdf AS category_needs_pdf
            FROM batch_files bf
            LEFT JOIN categories c ON c.id = bf.category_id
            WHERE bf.batch_id = ?
            ORDER BY bf.id
            """,
            (batch_id,),
        ).fetchall()
    return batch, files


def _sanitize_filename(name: str) -> str:
    return Path(name).name.replace("..", "")


@router.get("/batches")
def list_batches(request: Request, filter: str = "", user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    with get_conn() as conn:
        batches = conn.execute(
            """
            SELECT b.*,
                   COALESCE(u_sub.username, u_orig.username) AS submitted_by_username,
                   COALESCE(u_sub.full_name, u_orig.full_name, u_orig.username) AS submitted_by_fullname,
                   COALESCE(u_sub.role, u_orig.role, 'accountant') AS submitted_by_role,
                   u_app.username AS approved_by_username,
                   COALESCE(u_app.full_name, u_app.username) AS approved_by_fullname,
                   COUNT(bf.id) AS file_count,
                   SUM(CASE WHEN bf.status = 'success' THEN 1 ELSE 0 END) AS success_count,
                   SUM(CASE WHEN bf.has_date = 1 THEN 1 ELSE 0 END) AS date_count,
                   SUM(CASE WHEN bf.has_stamp = 1 THEN 1 ELSE 0 END) AS stamp_count,
                   SUM(CASE WHEN bf.has_signature = 1 THEN 1 ELSE 0 END) AS signature_count
            FROM batches b
            LEFT JOIN users u_sub ON u_sub.id = b.submitted_by
            LEFT JOIN users u_orig ON u_orig.id = b.user_id
            LEFT JOIN users u_app ON u_app.id = b.approved_by
            LEFT JOIN batch_files bf ON bf.batch_id = b.id
            GROUP BY b.id
            ORDER BY b.id DESC
            LIMIT 50
            """
        ).fetchall()

    pending_count = sum(1 for b in batches if b["status"] == "pending_cto")

    # If CTO specifically or if filter requested
    filtered_batches = list(batches)
    if filter == "pending":
        filtered_batches = [b for b in batches if b["status"] == "pending_cto"]
    elif filter == "approved":
        filtered_batches = [b for b in batches if b["status"] in ("approved", "done")]

    return templates.TemplateResponse(
        "batches.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "batches": filtered_batches,
            "all_batches_count": len(batches),
            "pending_count": pending_count,
            "filter": filter,
            "is_cto": user_role in ("cto", "admin"),
        },
    )


@router.get("/batch/new")
def new_batch_form(request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    sig_path = get_asset_path(user["id"], "signature")
    stamp_path = get_asset_path(user["id"], "stamp")
    return templates.TemplateResponse(
        "new_batch.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "has_signature": bool(sig_path),
            "has_stamp": bool(stamp_path),
            "can_edit_signature": user_role in ("cto", "admin"),
            "can_edit_stamp": user_role in ("accountant", "hr", "admin"),
        },
    )


@router.post("/batch/new")
def create_batch(request: Request, user=Depends(require_user), files: list[UploadFile] = File(...)):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO batches (user_id, submitted_by, status) VALUES (?, ?, 'draft')",
            (user["id"], user["id"]),
        )
        batch_id = cur.lastrowid

    upload_dir = DATA_DIR / "uploads" / str(batch_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_any = False
    with get_conn() as conn:
        for f in files:
            name = _sanitize_filename(f.filename or "")
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_EXT or not name:
                continue
            dest = upload_dir / name
            with dest.open("wb") as out:
                out.write(f.file.read())
            matched = match_category(name)
            has_existing, stamp_detail = detect_existing_stamp(dest)
            conn.execute(
                """INSERT INTO batch_files (batch_id, original_name, input_path, category_id, has_existing_stamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (batch_id, name, str(dest), matched["id"] if matched else None, 1 if has_existing else 0),
            )
            saved_any = True

    if not saved_any:
        with get_conn() as conn:
            conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
        return RedirectResponse(url="/batch/new", status_code=303)

    return RedirectResponse(url=f"/batch/{batch_id}/place", status_code=303)


@router.get("/batch/{batch_id}/place")
def place_form(batch_id: int, request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    batch, files = _get_batch(batch_id)
    pdf_files = [f for f in files if f["original_name"].lower().endswith(".pdf")]
    docx_files = [f for f in files if f["original_name"].lower().endswith(".docx")]
    excel_files = [f for f in files if f["original_name"].lower().endswith((".xlsx", ".xls"))]
    previewable_files = files

    preview_file = previewable_files[0] if previewable_files else None
    page_count = 1
    if preview_file:
        p_pdf = _get_previewable_pdf_path(preview_file)
        if p_pdf and Path(p_pdf).exists():
            page_count = pdf_engine.get_page_count(p_pdf)

    raw_keywords = batch["keywords"] or ", ".join(pdf_engine.DEFAULT_KEYWORDS)

    return templates.TemplateResponse(
        "new_batch_place.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "batch_id": batch_id,
            "batch": batch,
            "files": files,
            "has_pdf": bool(pdf_files),
            "has_docx": bool(docx_files),
            "has_excel": bool(excel_files),
            "has_previewable": bool(previewable_files),
            "preview_file_id": preview_file["id"] if preview_file else None,
            "page_count": max(page_count, 1),
            "has_signature": bool(get_asset_path(None, "signature")),
            "has_stamp": bool(get_asset_path(None, "stamp")),
            "categories": list_categories(),
            "default_keywords": raw_keywords,
            "is_cto": user_role in ("cto", "admin"),
            "can_edit_signature": user_role in ("cto", "admin"),
            "can_edit_stamp": user_role in ("accountant", "hr", "admin"),
        },
    )


def _get_previewable_pdf_path(file_record: dict) -> str | None:
    # 1. Prefer generated/stamped PDF if already produced
    for key in ("pdf_output_path", "output_path"):
        val = file_record[key] if key in file_record.keys() else None
        if val and str(val).lower().endswith(".pdf") and Path(val).exists():
            return str(val)

    # 2. Check input file format
    ext = Path(file_record["original_name"]).suffix.lower()
    input_path = file_record["input_path"]
    if not input_path or not Path(input_path).exists():
        return None

    if ext == ".pdf":
        return input_path
    elif ext in (".xlsx", ".xls"):
        return excel_engine.get_or_create_preview_pdf(input_path)
    elif ext == ".docx":
        preview_pdf = Path(input_path).with_suffix(".preview.pdf")
        if preview_pdf.exists() and preview_pdf.stat().st_mtime >= Path(input_path).stat().st_mtime:
            return str(preview_pdf)
        ok, msg = docx_to_pdf.convert_to_pdf(input_path, str(preview_pdf))
        if ok and preview_pdf.exists():
            return str(preview_pdf)
    return None


@router.get("/batch/{batch_id}/file-pages")
def file_pages(batch_id: int, file_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id, user["id"])
    target = next((f for f in files if f["id"] == file_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="File not found")
    pdf_path = _get_previewable_pdf_path(target)
    if not pdf_path or not Path(pdf_path).exists():
        return JSONResponse({"page_count": 1, "is_previewable": False})
    return JSONResponse({
        "page_count": pdf_engine.get_page_count(pdf_path),
        "is_previewable": True
    })


@router.get("/batch/{batch_id}/file-info/{file_id}")
def file_info(batch_id: int, file_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id, user["id"])
    target = next((f for f in files if f["id"] == file_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="File not found")

    pdf_path = _get_previewable_pdf_path(target)
    total_pages = pdf_engine.get_page_count(pdf_path) if (pdf_path and Path(pdf_path).exists()) else 1

    target_page_num = total_pages
    target_cat_page = target["category_target_page"] if "category_target_page" in target.keys() else None
    if target["detected_page"]:
        target_page_num = target["detected_page"]
    elif target_cat_page and str(target_cat_page).isdigit():
        target_page_num = int(target_cat_page)

    return JSONResponse({
        "id": target["id"],
        "name": target["original_name"],
        "total_pages": max(1, total_pages),
        "target_page": min(max(1, target_page_num), max(1, total_pages)),
        "has_existing_stamp": bool(target["has_existing_stamp"]) if "has_existing_stamp" in target.keys() else False,
        "has_stamp": bool(target["has_stamp"]) if "has_stamp" in target.keys() else False,
        "has_signature": bool(target["has_signature"]) if "has_signature" in target.keys() else False,
        "status": target["status"],
    })


@router.get("/batch/{batch_id}/preview-image")
def preview_image(
    batch_id: int,
    request: Request,
    page: int = 1,
    file_id: int | None = None,
    user=Depends(require_user),
):
    batch, files = _get_batch(batch_id, user["id"])
    target_file = None
    if file_id:
        target_file = next((f for f in files if f["id"] == file_id), None)

    if not target_file:
        previewables = [f for f in files if f["original_name"].lower().endswith((".pdf", ".xlsx", ".xls", ".docx"))]
        target_file = previewables[0] if previewables else (files[0] if files else None)

    if not target_file:
        raise HTTPException(status_code=404, detail="No previewable document selected")

    pdf_to_render = _get_previewable_pdf_path(target_file)
    if not pdf_to_render or not Path(pdf_to_render).exists():
        raise HTTPException(status_code=500, detail="Could not render preview for this document")

    total_pages = pdf_engine.get_page_count(pdf_to_render)
    safe_page = max(0, min(page - 1, total_pages - 1))
    png_bytes = pdf_engine.render_page_png(pdf_to_render, page_index=safe_page)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "X-Total-Pages": str(total_pages),
            "X-Current-Page": str(safe_page + 1),
            "Cache-Control": "no-cache",
        },
    )


@router.get("/batch/{batch_id}/detect-keyword")
def detect_keyword(
    batch_id: int,
    request: Request,
    page: int = 1,
    file_id: int | None = None,
    keywords: str = "",
    user=Depends(require_user),
):
    batch, files = _get_batch(batch_id, user["id"])
    target_file = None
    if file_id:
        target_file = next((f for f in files if f["id"] == file_id), None)

    if not target_file:
        previewables = [f for f in files if f["original_name"].lower().endswith((".pdf", ".xlsx", ".xls"))]
        target_file = previewables[0] if previewables else None

    if not target_file:
        return JSONResponse({"matches": []})

    pdf_to_scan = _get_previewable_pdf_path(target_file)
    if not pdf_to_scan or not Path(pdf_to_scan).exists():
        return JSONResponse({"matches": []})

    kw_list = pdf_engine.parse_keywords(keywords)
    matches = pdf_engine.detect_keywords_on_page(pdf_to_scan, page_index=page - 1, keywords=kw_list)
    return JSONResponse({"matches": matches})


def _worker_process_batch(
    batch_id: int,
    user_id: int,
    include_signature: bool,
    include_stamp: bool,
    sig_x: float,
    sig_y: float,
    sig_w: float,
    stamp_x: float,
    stamp_y: float,
    stamp_w: float,
    target_page: str,
    new_date: str,
    date_pattern: str,
    image_width_pct: float,
    placement_mode: str,
    keywords_str: str,
    auto_convert_pdf: bool,
    category_overrides: dict,
    target_status: str = "done",
):
    try:
        raw_sig_path = get_asset_path(None, "signature") if include_signature else None
        raw_stamp_path = get_asset_path(None, "stamp") if include_stamp else None
        parsed_keywords = pdf_engine.parse_keywords(keywords_str)

        output_dir = DATA_DIR / "outputs" / str(batch_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        categories_by_id = {c["id"]: c for c in list_categories()}

        with get_conn() as conn:
            files = conn.execute(
                "SELECT * FROM batch_files WHERE batch_id = ? ORDER BY id", (batch_id,)
            ).fetchall()

        processed_count = 0
        for f in files:
            name = f["original_name"]
            input_path = f["input_path"]
            output_path = str(output_dir / name)
            ext = Path(name).suffix.lower()

            with get_conn() as conn:
                conn.execute(
                    "UPDATE batches SET current_file=?, processed_files=? WHERE id=?",
                    (name, processed_count, batch_id),
                )
                conn.execute(
                    "UPDATE batch_files SET status='processing' WHERE id=?", (f["id"],)
                )

            category_id = category_overrides.get(str(f["id"])) or f["category_id"]
            category = categories_by_id.get(category_id)

            def _effective(flag_name: str, fallback: bool) -> bool:
                val = category[flag_name] if category is not None else None
                return bool(val) if val is not None else fallback

            use_signature = _effective("needs_signature", include_signature)
            use_stamp = _effective("needs_stamp", include_stamp)
            use_date = _effective("needs_date", bool(new_date))
            auto_pdf = _effective("needs_pdf", auto_convert_pdf)

            # Avoid duplicate stamp if file already has an existing company stamp
            has_existing = bool(f["has_existing_stamp"]) if "has_existing_stamp" in f.keys() else False
            if has_existing:
                use_stamp = False

            sig_path = raw_sig_path if use_signature else None
            stamp_path = raw_stamp_path if use_stamp else None
            effective_date = new_date if use_date else ""

            # Check per-category target page (e.g. Form-T enforces Page 2)
            file_target_page = target_page
            if category and category["target_page"]:
                file_target_page = category["target_page"]

            meta: dict = {}
            pdf_output_path = None

            if ext == ".pdf":
                sig_dict = {"x": sig_x, "y": sig_y, "w": sig_w, "image_path": sig_path} if sig_path else None
                stamp_dict = {"x": stamp_x, "y": stamp_y, "w": stamp_w, "image_path": stamp_path} if stamp_path else None
                ok, message, meta = pdf_engine.process_pdf(
                    input_path,
                    output_path,
                    file_target_page,
                    sig_dict,
                    stamp_dict,
                    effective_date or None,
                    date_pattern or None,
                    placement_mode=placement_mode,
                    keywords=parsed_keywords,
                )
                if ok:
                    pdf_output_path = output_path
            elif ext in (".xlsx", ".xls"):
                pdf_target = str(output_dir / f"{Path(name).stem}.pdf")
                xlsx_target = str(output_dir / name)
                sig_dict = {"x": sig_x, "y": sig_y, "w": sig_w, "image_path": sig_path} if sig_path else None
                stamp_dict = {"x": stamp_x, "y": stamp_y, "w": stamp_w, "image_path": stamp_path} if stamp_path else None
                ok, message, meta = excel_engine.process_excel(
                    input_path=input_path,
                    output_pdf_path=pdf_target,
                    output_xlsx_path=xlsx_target,
                    target_page=file_target_page,
                    signature=sig_dict,
                    stamp=stamp_dict,
                    new_date=effective_date or None,
                    date_pattern=date_pattern or None,
                    placement_mode=placement_mode,
                    keywords=parsed_keywords,
                )
                output_path = pdf_target if ok else None
                pdf_output_path = pdf_target if ok else None
            elif ext == ".docx":
                ok, message, meta = docx_engine.process_docx(
                    input_path,
                    output_path,
                    sig_path,
                    stamp_path,
                    image_width_pct,
                    effective_date or None,
                    date_pattern or None,
                    keywords=parsed_keywords,
                )
                if ok and auto_pdf:
                    pdf_target = output_path + ".pdf"
                    pdf_ok, pdf_message = docx_to_pdf.convert_to_pdf(output_path, pdf_target)
                    if pdf_ok:
                        pdf_output_path = pdf_target
                    else:
                        message = f"{message} (PDF conversion warning: {pdf_message})"
            else:
                ok, message = False, "Unsupported file type"

            processed_count += 1
            has_sig_flag = 1 if (ok and sig_path) else 0
            has_stamp_flag = 1 if (ok and (stamp_path or has_existing)) else (1 if has_existing else 0)
            has_date_flag = 1 if (ok and effective_date) else 0

            if ok and has_existing:
                message = f"{message} (Preserved original stamp)" if message else "Preserved original stamp"

            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE batch_files
                    SET status=?, message=?, output_path=?, category_id=?, pdf_output_path=?,
                        detected_page=?, detected_text=?, is_fallback=?,
                        has_date=?, has_stamp=?, has_signature=?,
                        stamped_path=?, signed_path=?
                    WHERE id=?
                    """,
                    (
                        "success" if ok else "error",
                        message,
                        output_path if ok else None,
                        category_id,
                        pdf_output_path,
                        meta.get("detected_page"),
                        meta.get("detected_text"),
                        meta.get("is_fallback", 0),
                        has_date_flag,
                        has_stamp_flag,
                        has_sig_flag,
                        output_path if (ok and stamp_path) else None,
                        output_path if (ok and sig_path) else None,
                        f["id"],
                    ),
                )
                conn.execute(
                    "UPDATE batches SET processed_files=? WHERE id=?",
                    (processed_count, batch_id),
                )

        with get_conn() as conn:
            conn.execute(
                "UPDATE batches SET status=?, current_file='', processed_files=? WHERE id=?",
                (target_status, processed_count, batch_id),
            )
    except Exception as exc:
        print(f"Batch processing failed: {exc}")
        with get_conn() as conn:
            conn.execute(
                "UPDATE batches SET status='error', current_file='' WHERE id=?",
                (batch_id,),
            )


@router.post("/batch/{batch_id}/process")
async def process_batch(
    batch_id: int,
    request: Request,
    user=Depends(require_user),
    action: str = Form("submit_for_approval"),
    include_signature: bool = Form(False),
    include_stamp: bool = Form(True),
    sig_x: float = Form(5.0),
    sig_y: float = Form(80.0),
    sig_w: float = Form(20.0),
    stamp_x: float = Form(30.0),
    stamp_y: float = Form(80.0),
    stamp_w: float = Form(20.0),
    target_page: str = Form("last"),
    new_date: str = Form(""),
    date_pattern: str = Form(""),
    image_width_pct: float = Form(20.0),
    placement_mode: str = Form("hybrid"),
    keywords: str = Form(""),
    auto_convert_pdf: bool = Form(True),
):
    batch, files = _get_batch(batch_id)
    form = await request.form()
    submit_action = form.get("action", action)

    # Standard Accountant / HR flow: submit for CTO approval
    if submit_action == "submit_for_approval":
        eff_include_sig = False
        eff_include_stamp = True
        target_status = "pending_cto"
        status_msg = "Stamping Company Seal & Date for CTO Approval..."
    else:  # Direct full process
        eff_include_sig = bool(include_signature)
        eff_include_stamp = bool(include_stamp)
        target_status = "approved" if eff_include_sig else "done"
        status_msg = "Applying Signature, Stamp & Date..."

    # Category overrides from dropdown
    category_overrides = {}
    for f in files:
        raw_val = form.get(f"category_{f['id']}")
        if raw_val:
            try:
                category_overrides[str(f["id"])] = int(raw_val)
            except ValueError:
                pass

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE batches SET status='processing', new_date=?, date_pattern=?,
                sig_x=?, sig_y=?, sig_w=?, stamp_x=?, stamp_y=?, stamp_w=?, target_page=?,
                placement_mode=?, keywords=?, auto_convert_pdf=?, total_files=?, processed_files=0,
                current_file=?, submitted_by=?, submitted_at=datetime('now')
            WHERE id=?
            """,
            (
                new_date or None,
                date_pattern or None,
                sig_x, sig_y, sig_w,
                stamp_x, stamp_y, stamp_w,
                target_page,
                placement_mode,
                keywords,
                int(auto_convert_pdf),
                len(files),
                status_msg,
                user["id"],
                batch_id,
            ),
        )

    # Launch background thread for non-blocking batch execution
    worker_thread = threading.Thread(
        target=_worker_process_batch,
        args=(
            batch_id,
            user["id"],
            eff_include_sig,
            eff_include_stamp,
            sig_x, sig_y, sig_w,
            stamp_x, stamp_y, stamp_w,
            target_page,
            new_date,
            date_pattern,
            image_width_pct,
            placement_mode,
            keywords,
            auto_convert_pdf,
            category_overrides,
            target_status,
        ),
        daemon=True,
    )
    worker_thread.start()

    return RedirectResponse(url=f"/batch/{batch_id}/processing", status_code=303)


@router.get("/batch/{batch_id}/review")
def review_page(batch_id: int, request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    batch, files = _get_batch(batch_id)
    total_files = len(files)
    stamped_count = sum(1 for f in files if f["has_stamp"] or ("has_existing_stamp" in f.keys() and f["has_existing_stamp"]) or f["status"] in ("stamped", "success"))
    date_count = sum(1 for f in files if f["has_date"] or (f["category_needs_date"] and batch["new_date"]))
    signed_count = sum(1 for f in files if f["has_signature"])

    sig_path = get_asset_path(None, "signature")
    stamp_path = get_asset_path(None, "stamp")

    return templates.TemplateResponse(
        "review.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "batch_id": batch_id,
            "batch": batch,
            "files": files,
            "total_files": total_files,
            "stamped_count": stamped_count,
            "date_count": date_count,
            "signed_count": signed_count,
            "has_signature": bool(sig_path),
            "has_stamp": bool(stamp_path),
            "is_cto": user_role in ("cto", "admin"),
        },
    )


@router.post("/batch/{batch_id}/approve")
async def approve_batch(batch_id: int, request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    if user_role not in ("cto", "admin"):
        raise HTTPException(status_code=403, detail="Only CTO can approve and digitally sign batches.")

    batch, files = _get_batch(batch_id)
    if not files:
        raise HTTPException(status_code=400, detail="Batch has no files.")

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE batches
            SET status = 'processing', approved_by = ?, approved_at = datetime('now'),
                processed_files = 0, current_file = 'Applying CTO Digital Signature...'
            WHERE id = ?
            """,
            (user["id"], batch_id),
        )

    # Launch signing worker with full signature and stamp
    worker_thread = threading.Thread(
        target=_worker_process_batch,
        args=(
            batch_id,
            user["id"],
            True,  # include_signature
            True,  # include_stamp
            batch["sig_x"] or 5.0,
            batch["sig_y"] or 80.0,
            batch["sig_w"] or 20.0,
            batch["stamp_x"] or 30.0,
            batch["stamp_y"] or 80.0,
            batch["stamp_w"] or 20.0,
            batch["target_page"] or "last",
            batch["new_date"] or "",
            batch["date_pattern"] or "",
            20.0,
            batch["placement_mode"] or "hybrid",
            batch["keywords"] or "",
            bool(batch["auto_convert_pdf"]),
            {},
            "approved",
        ),
        daemon=True,
    )
    worker_thread.start()

    return RedirectResponse(url=f"/batch/{batch_id}/processing", status_code=303)


@router.post("/batch/{batch_id}/reject")
async def reject_batch(
    batch_id: int,
    request: Request,
    rejection_reason: str = Form(""),
    user=Depends(require_user),
):
    user_role = user["role"] if "role" in user.keys() else "hr"
    if user_role not in ("cto", "admin"):
        raise HTTPException(status_code=403, detail="Only CTO can reject batches.")

    with get_conn() as conn:
        conn.execute(
            "UPDATE batches SET status = 'changes_requested', rejection_reason = ? WHERE id = ?",
            (rejection_reason or "Changes requested by CTO.", batch_id),
        )
    return RedirectResponse(url=f"/batch/{batch_id}/monitor", status_code=303)


@router.get("/batch/{batch_id}/monitor")
def monitor_page(batch_id: int, request: Request, user=Depends(require_user)):
    user_role = user["role"] if "role" in user.keys() else "hr"
    batch, files = _get_batch(batch_id)

    total_files = len(files)
    stamped_count = sum(1 for f in files if f["has_stamp"] or ("has_existing_stamp" in f.keys() and f["has_existing_stamp"]) or f["status"] in ("stamped", "success"))
    date_count = sum(1 for f in files if f["has_date"] or (f["category_needs_date"] and batch["new_date"]))
    signed_count = sum(1 for f in files if f["has_signature"])

    return templates.TemplateResponse(
        "monitor.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user["full_name"] if "full_name" in user.keys() else user["username"],
            "batch_id": batch_id,
            "batch": batch,
            "files": files,
            "total_files": total_files,
            "stamped_count": stamped_count,
            "date_count": date_count,
            "signed_count": signed_count,
            "is_cto": user_role in ("cto", "admin"),
        },
    )


@router.get("/batch/{batch_id}/view-pdf/{file_id}")
def view_file_pdf(batch_id: int, file_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    match = next((f for f in files if f["id"] == file_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="File not found")

    pdf_path = match["pdf_output_path"]
    if not pdf_path or not Path(pdf_path).exists():
        if match["output_path"] and match["output_path"].lower().endswith(".pdf") and Path(match["output_path"]).exists():
            pdf_path = match["output_path"]
        else:
            pdf_path = _get_previewable_pdf_path(match)

    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF preview not available for this file")

    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/batch/{batch_id}/processing")
def processing_page(batch_id: int, request: Request, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    if batch["status"] in ("done", "approved", "pending_cto", "changes_requested"):
        return RedirectResponse(url=f"/batch/{batch_id}/monitor", status_code=303)
    user_role = user["role"] if "role" in user.keys() else "hr"
    user_fullname = user["full_name"] if "full_name" in user.keys() and user["full_name"] else user["username"]
    return templates.TemplateResponse(
        "processing.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user_fullname,
            "batch_id": batch_id,
            "batch": batch,
            "files": files,
        },
    )


@router.get("/batch/{batch_id}/progress")
def batch_progress(batch_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    total = len(files)
    completed = sum(1 for f in files if f["status"] in ("success", "stamped", "error"))
    pct = round((completed / total) * 100, 1) if total > 0 else 0

    return JSONResponse({
        "status": batch["status"],
        "total": total,
        "completed": completed,
        "percent": pct,
        "current_file": batch["current_file"] or "",
        "files": [
            {
                "id": f["id"],
                "name": f["original_name"],
                "status": f["status"],
                "message": f["message"] or "",
                "detected_text": f["detected_text"],
                "detected_page": f["detected_page"],
                "is_fallback": bool(f["is_fallback"]),
                "has_date": bool(f["has_date"]),
                "has_stamp": bool(f["has_stamp"]),
                "has_signature": bool(f["has_signature"]),
                "has_existing_stamp": bool(f["has_existing_stamp"]) if "has_existing_stamp" in f.keys() else False,
                "pdf_output_path": f["pdf_output_path"],
                "output_path": f["output_path"],
            }
            for f in files
        ],
    })


@router.get("/batch/{batch_id}/results")
def results_page(batch_id: int, request: Request, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    success_count = sum(1 for f in files if f["status"] in ("success", "stamped"))
    error_count = sum(1 for f in files if f["status"] == "error")
    detected_count = sum(1 for f in files if f["detected_text"] and not f["is_fallback"])
    fallback_count = sum(1 for f in files if f["is_fallback"])
    user_role = user["role"] if "role" in user.keys() else "hr"
    user_fullname = user["full_name"] if "full_name" in user.keys() and user["full_name"] else user["username"]

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "user": user,
            "username": user["username"],
            "role": user_role,
            "full_name": user_fullname,
            "batch_id": batch_id,
            "batch": batch,
            "files": files,
            "success_count": success_count,
            "error_count": error_count,
            "detected_count": detected_count,
            "fallback_count": fallback_count,
        },
    )


@router.get("/batch/{batch_id}/download/{file_id}")
def download_file(batch_id: int, file_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    match = next((f for f in files if f["id"] == file_id), None)
    if not match or not match["output_path"] or not Path(match["output_path"]).exists():
        raise HTTPException(status_code=404, detail="File not available")
    return FileResponse(match["output_path"], filename=match["original_name"])


def _ensure_pdf_path(file_row) -> str:
    """Return a path to the PDF version of a processed file, converting if needed."""
    pdf_path = file_row["pdf_output_path"]
    if pdf_path and Path(pdf_path).exists():
        return pdf_path

    if file_row["output_path"] and file_row["output_path"].lower().endswith(".pdf") and Path(file_row["output_path"]).exists():
        return file_row["output_path"]

    if file_row["original_name"].lower().endswith(".pdf"):
        return file_row["output_path"]

    ext = Path(file_row["original_name"]).suffix.lower()
    if ext in (".xlsx", ".xls"):
        pdf_path = str(Path(file_row["output_path"] or file_row["input_path"]).with_suffix(".pdf"))
        ok, message = excel_engine.convert_excel_to_pdf(file_row["input_path"], pdf_path)
    else:
        pdf_path = file_row["output_path"] + ".pdf"
        ok, message = docx_to_pdf.convert_to_pdf(file_row["output_path"], pdf_path)

    if not ok:
        raise HTTPException(status_code=500, detail=message)
    with get_conn() as conn:
        conn.execute(
            "UPDATE batch_files SET pdf_output_path=? WHERE id=?", (pdf_path, file_row["id"])
        )
    return pdf_path


@router.get("/batch/{batch_id}/download-pdf/{file_id}")
def download_as_pdf(batch_id: int, file_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    match = next((f for f in files if f["id"] == file_id), None)
    if not match or not match["output_path"] or not Path(match["output_path"]).exists():
        raise HTTPException(status_code=404, detail="File not available")

    pdf_path = _ensure_pdf_path(match)
    download_name = Path(match["original_name"]).with_suffix(".pdf").name
    return FileResponse(pdf_path, filename=download_name, media_type="application/pdf")


@router.get("/batch/{batch_id}/download-zip")
def download_zip(batch_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f["output_path"] and Path(f["output_path"]).exists():
                zf.write(f["output_path"], arcname=f["original_name"])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=audit-batch-{batch_id}-signed.zip"},
    )


def _unique_arcname(name: str, used: dict) -> str:
    if name not in used:
        used[name] = 0
        return name
    used[name] += 1
    stem, suffix = Path(name).stem, Path(name).suffix
    return f"{stem} ({used[name]}){suffix}"


@router.get("/batch/{batch_id}/download-zip-pdf")
def download_zip_pdf(batch_id: int, user=Depends(require_user)):
    batch, files = _get_batch(batch_id)
    ready = [f for f in files if f["output_path"] and Path(f["output_path"]).exists()]
    buf = io.BytesIO()
    used_names: dict = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ready:
            try:
                pdf_path = _ensure_pdf_path(f)
                arcname = _unique_arcname(Path(f["original_name"]).with_suffix(".pdf").name, used_names)
                zf.write(pdf_path, arcname=arcname)
            except Exception as e:
                print(f"Skipping PDF zip entry for {f['original_name']}: {e}")
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=audit-batch-{batch_id}-all-pdf.zip"},
    )
