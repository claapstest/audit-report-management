from pathlib import Path
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ..asset_version import ASSET_VERSION
from ..auth import require_user
from ..db import get_conn

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["asset_version"] = ASSET_VERSION

_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_TRAILING_NOISE = re.compile(rf"[\s_-]*{_MONTH_RE}\.?([\s_-]*\d{{1,4}})?$", re.IGNORECASE)

# High-precision statutory compliance document aliases for automated matching
CATEGORY_ALIASES = [
    (
        "CLRA Application & Renewal application-Form IV or Form VII",
        [r"clra\s+application", r"form\s+iv\s+or\s+form\s+vii", r"renewal\s+application.*form"],
    ),
    (
        "Contract Labour License-Form VI",
        [r"contract\s+labour\s+license", r"form\s+vi\b(?!a)"],
    ),
    (
        "Copy of FORM-T Muster Roll Cum Wage register",
        [r"form[-_\s]*t\b", r"muster\s+roll\s+cum\s+wage"],
    ),
    (
        "Early_late check-in and check-out",
        [r"early[-_\s]*late\s+check[-_\s]*in", r"check[-_\s]*in\s+and\s+check[-_\s]*out"],
    ),
    (
        "Half-Yearly Return by Contractor (Form XXIV)",
        [r"half[-_\s]*yearly\s+return", r"form\s+xxiv"],
    ),
    (
        "Notice of Commencement & Completion-Form Form VIA",
        [r"notice\s+of\s+commencement", r"form\s+(?:form\s+)?via\b"],
    ),
    (
        "Service Certificate-Form Form XV-Claaps",
        [r"service\s+certificate", r"form\s+(?:form\s+)?xv\b"],
    ),
    (
        "Employment card-Form XIV",
        [r"employment\s+card", r"form\s+xiv\b", r"employment\s+card.*xiv"],
    ),
    (
        "Form XIX Wage Slip",
        [r"form\s+xix", r"wageslip", r"wage\s*slip"],
    ),
    (
        "Applied Material",
        [r"applied\s+material"],
    ),
    (
        "Bonus Act-Form C and Form D",
        [r"bonus\s+act", r"form\s+c\s+and\s+form\s+d"],
    ),
    (
        "CHILD LABOUR",
        [r"child\s+labour"],
    ),
    (
        "Monthly Return-Form IW",
        [r"monthly\s+return", r"form\s+iw\b"],
    ),
    (
        "Declaration for ESI",
        [r"declaration\s+for\s+esi", r"esi.*declaration"],
    ),
    (
        "Equal Remuneration",
        [r"equal\s+remuneration"],
    ),
    (
        "Labour Welfare Fund Act",
        [r"labour\s+welfare\s+fund", r"lwf\b"],
    ),
    (
        "Maternity Benefit Act",
        [r"maternity\s+act", r"maternity\s+benefit", r"muster\s+roll.*form\s+a", r"maternity.*muster"],
    ),
    (
        "Annual return Under Minimum wages act-Form U",
        [r"annual\s+return.*minimum\s+wages", r"minimum\s+wages.*form\s+u", r"form\s+u\b"],
    ),
    (
        "Minimum Wages Act",
        [r"minimum\s+wages", r"miminum\s+wages"],
    ),
    (
        "National & Festival Holidays Act",
        [r"national\s+(?:&|and)\s+festival\s+holidays"],
    ),
    (
        "Gratuity Settlement-Form L",
        [r"gratuity\s+settlement", r"payment\s+of\s+gratuity", r"form\s+l\b"],
    ),
    (
        "Bank Transfer Proof_Salary declaration",
        [r"bank\s+transfer\s+proof", r"salary\s+declaration"],
    ),
    (
        "PF Declaration",
        [r"pf\s+declaration"],
    ),
    (
        "Constitute",
        [r"constitute"],
    ),
    (
        "Sexual Harassment Of Women at Workplace",
        [r"sexual\s+harass", r"internal\s+complaints", r"awareness\s+program"],
    ),
    (
        "Leave policy",
        [r"leave\s+policy"],
    ),
    (
        "Form F Wage Register",
        [r"form\s+f\b", r"\bf\s*-\s*leave\s+with\s+wage", r"leave\s+with\s+wage\s+register"],
    ),
    (
        "Appointment Order Form Q",
        [r"appointment\s+order", r"form\s+q\b"],
    ),
]


def list_categories() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()


def _normalize_doc_name(name: str) -> str:
    """Strip extension and trailing month/date noise (e.g. '-Dec', ' June 26') so recurring
    monthly filenames still match their rule even as the trailing date changes each cycle."""
    stem = Path(name).stem
    stem = _TRAILING_NOISE.sub("", stem)
    return re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()


def match_category(filename: str):
    """Find the category that best matches an uploaded filename.
    First tests high-precision alias patterns, then falls back to normalized search."""
    fname_lower = filename.lower()
    norm_file = _normalize_doc_name(filename)

    with get_conn() as conn:
        # 1. Alias Pattern Matching
        for cat_name, patterns in CATEGORY_ALIASES:
            for pat in patterns:
                if re.search(pat, fname_lower, re.I):
                    row = conn.execute(
                        "SELECT * FROM categories WHERE name = ? OR match_name = ?",
                        (cat_name, cat_name),
                    ).fetchone()
                    if row:
                        return row

        # 2. Normalized Substring Fallback
        if not norm_file:
            return None

        rules = conn.execute(
            "SELECT * FROM categories WHERE match_name IS NOT NULL AND match_name != ''"
        ).fetchall()

        best = None
        best_len = 0
        for rule in rules:
            norm_rule = _normalize_doc_name(rule["match_name"])
            if not norm_rule:
                continue
            if norm_rule == norm_file or norm_rule in norm_file or norm_file in norm_rule:
                if len(norm_rule) > best_len:
                    best, best_len = rule, len(norm_rule)
        return best


@router.get("/categories")
def categories_page(request: Request, user=Depends(require_user)):
    return templates.TemplateResponse(
        "categories.html",
        {
            "request": request,
            "username": user["username"],
            "categories": list_categories(),
        },
    )


@router.post("/categories/{category_id}/task")
def update_task(category_id: int, request: Request, user=Depends(require_user), task: str = Form("")):
    with get_conn() as conn:
        conn.execute("UPDATE categories SET task=? WHERE id=?", (task.strip() or None, category_id))
    return RedirectResponse(url="/categories", status_code=303)
