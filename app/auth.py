from fastapi import Request, HTTPException
from passlib.context import CryptContext

from .db import get_conn

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def get_user_by_username(username: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def create_user(username: str, password: str, role: str = "hr", full_name: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, full_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                role = excluded.role,
                full_name = excluded.full_name
            """,
            (username, hash_password(password), role, full_name or username.upper()),
        )


def init_default_users() -> None:
    """Seeds the 3 required role accounts: CTO, HR, and Accountant."""
    defaults = [
        ("cto", "cto123", "cto", "Chief Technology Officer"),
        ("hr", "hr123", "hr", "HR Compliance Manager"),
        ("accountant", "accountant123", "accountant", "Statutory Accountant"),
    ]
    for username, pwd, role, fname in defaults:
        existing = get_user_by_username(username)
        if not existing:
            create_user(username, pwd, role=role, full_name=fname)
        else:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET role = ?, full_name = ? WHERE id = ?",
                    (role, fname, existing["id"]),
                )

    # Ensure demo account has administrative/HR role
    demo = get_user_by_username("demo")
    if demo:
        with get_conn() as conn:
            conn.execute(
                "UPDATE users SET role = 'admin', full_name = 'Audit Administrator' WHERE id = ?",
                (demo["id"],),
            )


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_role(roles: list[str]):
    def _role_checker(request: Request):
        user = require_user(request)
        user_role = user["role"] if "role" in user.keys() else "hr"
        if user_role not in roles and user_role != "admin":
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Requires one of roles: {', '.join(roles)}",
            )
        return user
    return _role_checker


def require_cto(request: Request):
    return require_role(["cto"])(request)


def require_accountant_or_hr(request: Request):
    return require_role(["accountant", "hr"])(request)
