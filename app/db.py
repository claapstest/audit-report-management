from contextlib import contextmanager
from pathlib import Path
import sqlite3

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'hr',
    full_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('signature', 'stamp')),
    file_path TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, kind)
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'draft',
    new_date TEXT,
    date_pattern TEXT,
    sig_x REAL,
    sig_y REAL,
    sig_w REAL,
    stamp_x REAL,
    stamp_y REAL,
    stamp_w REAL,
    target_page TEXT DEFAULT 'last',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS batch_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id),
    original_name TEXT NOT NULL,
    input_path TEXT NOT NULL,
    output_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    message TEXT,
    has_existing_stamp INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    task TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_CATEGORIES = [
    "The Contract Labour Act",
    "Applied Materials",
    "Bonus Act-Form C and Form D",
    "CHILD LABOUR",
    "Employees Provident Fund Act & Scheme",
    "Employees State Insurance Act & Scheme",
    "Equal Remuneration Act",
    "Labour Welfare Fund Act",
    "Maternity Benefit Act",
    "Minimum Wages Act",
    "National & Festival Holidays Act",
    "Payment of Gratuity Act",
    "Payment of Wages Act",
    "PF Declaration",
    "Sexual Harassment Of Women at Workplace",
    "Shops & Commercial Establishment Act",
]

# Per-document rules derived from client's statutory compliance requirements.
# Tuple format: (name, needs_date, needs_pdf, target_page, date_mode, notes)
DOC_RULES = [
    (
        "CLRA Application & Renewal application-Form IV or Form VII",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Contract Labour License-Form VI",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Copy of FORM-T Muster Roll Cum Wage register",
        False,
        True,
        "2",
        "none",
        "Excel converted to PDF. Prunes empty pages into 2-page document. Sign and stamp placed on Page 2.",
    ),
    (
        "Early_late check-in and check-out",
        False,
        False,
        "last",
        "none",
        "Digital signature and seal adjacent at the bottom of the page only — no date change.",
    ),
    (
        "Half-Yearly Return by Contractor (Form XXIV)",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Notice of Commencement & Completion-Form Form VIA",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Service Certificate-Form Form XV-Claaps",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Employment card-Form XIV",
        True,
        True,
        "last",
        "wage_period",
        "Mention wage period under 'Wage Period' heading for every month. Digital signature and adjacent seal below Remarks. Convert to PDF.",
    ),
    (
        "Form XIX Wage Slip",
        False,
        True,
        "last",
        "none",
        "Digital signature and seal above 'Signature of the Contractor'. Convert to PDF.",
    ),
    (
        "Applied Material",
        True,
        True,
        "last",
        "top_only",
        "Date at top only. Digital signature and adjacent company seal. Convert to PDF.",
    ),
    (
        "Bonus Act-Form C and Form D",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "CHILD LABOUR",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Monthly Return-Form IW",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Declaration for ESI",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Equal Remuneration",
        False,
        True,
        "last",
        "none",
        "Excel converted to PDF. Digital signature and adjacent seal placed at bottom.",
    ),
    (
        "Labour Welfare Fund Act",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Maternity Benefit Act",
        True,
        True,
        "last",
        "month_year_top",
        "Change month & year at top ('For <Month> <Year>'). Signature & adjacent seal at end of page. Convert to PDF.",
    ),
    (
        "Annual return Under Minimum wages act-Form U",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Minimum Wages Act",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "National & Festival Holidays Act",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Gratuity Settlement-Form L",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Bank Transfer Proof_Salary declaration",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "PF Declaration",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Constitute",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Sexual Harassment Of Women at Workplace",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Leave policy",
        True,
        True,
        "last",
        "standard",
        "1. Date at top, 2. Date at bottom, 3. Digital signature and adjacent company seal, 4. Convert into PDF.",
    ),
    (
        "Form F Wage Register",
        False,
        True,
        "last",
        "none",
        "Excel converted to PDF. Company name & address at top right. Digital signature & seal at bottom.",
    ),
    (
        "Appointment Order Form Q",
        True,
        True,
        "last",
        "bottom_table",
        "Signatory date in table row 12. Digital signature above 'Signature of Employer.', seal above 'Seal of the Establishment.'. Convert to PDF.",
    ),
]


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)

        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "role" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'hr'")
        if "full_name" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

        columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_files)")}
        if "pdf_output_path" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN pdf_output_path TEXT")
        if "category_id" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN category_id INTEGER REFERENCES categories(id)")
        if "detected_page" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN detected_page INTEGER")
        if "detected_text" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN detected_text TEXT")
        if "is_fallback" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN is_fallback INTEGER DEFAULT 0")
        if "has_date" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN has_date INTEGER DEFAULT 0")
        if "has_stamp" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN has_stamp INTEGER DEFAULT 0")
        if "has_signature" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN has_signature INTEGER DEFAULT 0")
        if "stamped_path" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN stamped_path TEXT")
        if "signed_path" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN signed_path TEXT")
        if "has_existing_stamp" not in columns:
            conn.execute("ALTER TABLE batch_files ADD COLUMN has_existing_stamp INTEGER DEFAULT 0")

        batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batches)")}
        if "placement_mode" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN placement_mode TEXT DEFAULT 'hybrid'")
        if "keywords" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN keywords TEXT")
        if "auto_convert_pdf" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN auto_convert_pdf INTEGER DEFAULT 1")
        if "total_files" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN total_files INTEGER DEFAULT 0")
        if "processed_files" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN processed_files INTEGER DEFAULT 0")
        if "current_file" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN current_file TEXT DEFAULT ''")
        if "stage" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN stage TEXT DEFAULT 'draft'")
        if "submitted_by" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN submitted_by INTEGER REFERENCES users(id)")
        if "submitted_at" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN submitted_at TEXT")
        if "approved_by" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN approved_by INTEGER REFERENCES users(id)")
        if "approved_at" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN approved_at TEXT")
        if "rejection_reason" not in batch_columns:
            conn.execute("ALTER TABLE batches ADD COLUMN rejection_reason TEXT")

        cat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(categories)")}
        for col in ("match_name", "needs_date", "needs_signature", "needs_stamp", "needs_pdf", "target_page", "date_mode"):
            if col not in cat_columns:
                col_type = "TEXT" if col in ("match_name", "target_page", "date_mode") else "INTEGER"
                conn.execute(f"ALTER TABLE categories ADD COLUMN {col} {col_type}")

        existing = conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
        if existing == 0:
            conn.executemany(
                "INSERT INTO categories (name, task, sort_order) VALUES (?, NULL, ?)",
                [(name, i) for i, name in enumerate(DEFAULT_CATEGORIES)],
            )

        next_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM categories").fetchone()["n"]
        for i, (name, needs_date, needs_pdf, target_page, date_mode, notes) in enumerate(DOC_RULES):
            conn.execute(
                """
                INSERT INTO categories (name, task, sort_order, match_name, needs_date, needs_signature, needs_stamp, needs_pdf, target_page, date_mode)
                VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    task = excluded.task,
                    match_name = excluded.match_name,
                    needs_date = excluded.needs_date,
                    needs_signature = excluded.needs_signature,
                    needs_stamp = excluded.needs_stamp,
                    needs_pdf = excluded.needs_pdf,
                    target_page = excluded.target_page,
                    date_mode = excluded.date_mode
                """,
                (name, notes, next_sort + i, name, int(needs_date), int(needs_pdf), target_page, date_mode),
            )

        # Seed default CTO signature and company stamp into persistent data storage
        default_dir = DATA_DIR / "assets" / "default"
        default_dir.mkdir(parents=True, exist_ok=True)
        packaged_assets = Path(__file__).resolve().parent / "default_assets"
        if packaged_assets.exists():
            import shutil
            for asset_file in packaged_assets.glob("*.png"):
                dest = default_dir / asset_file.name
                if not dest.exists():
                    shutil.copy2(asset_file, dest)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
