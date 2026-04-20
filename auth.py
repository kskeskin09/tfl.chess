"""
auth.py — Custom authentication using bcrypt-hashed passwords.
No Supabase Auth is used; credentials are verified against the users table.
"""
from __future__ import annotations

import bcrypt
import streamlit as st

from config import ADMIN_USERNAME
from db import get_user


# ── Password utilities ────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of a plaintext password (use when adding users)."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── Session helpers ───────────────────────────────────────────────────────────

def is_logged_in() -> bool:
    return bool(st.session_state.get("user"))


def is_admin() -> bool:
    return st.session_state.get("is_admin", False)


def current_user() -> dict | None:
    return st.session_state.get("user")


def logout() -> None:
    for key in ("user", "is_admin"):
        st.session_state.pop(key, None)


# ── Login logic ───────────────────────────────────────────────────────────────

def try_login(username: str, password: str) -> tuple[bool, str]:
    """
    Attempt login.
    Returns (success: bool, message: str).
    Sets st.session_state['user'] and st.session_state['is_admin'] on success.
    """
    username = username.strip()

    # ── Admin login ──
    if username == ADMIN_USERNAME:
        admin_pw = st.secrets.get("ADMIN_PASSWORD", "")
        if password == admin_pw:
            st.session_state["user"] = {
                "name": ADMIN_USERNAME,
                "league": None,
                "points": None,
                "phone": None,
                "password": None,
            }
            st.session_state["is_admin"] = True
            return True, "Admin login successful."
        return False, "Wrong admin password."

    # ── Regular player login ──
    user = get_user(username)
    if not user:
        return False, "User not found."
    if not verify_password(password, user["password"]):
        return False, "Incorrect password."

    st.session_state["user"] = user
    st.session_state["is_admin"] = False
    return True, "Login successful."
