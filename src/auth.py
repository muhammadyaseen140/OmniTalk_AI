"""
Authentication for OmniTalk AI.

- Email + password sign up / sign in (bcrypt hashed, stored in SQLite)
- Forgot password with a 6-digit code (SMTP email, or demo mode if SMTP is not set)
- "Continue with Google" through Streamlit's built-in OIDC login (st.login)
- Brute-force protection (account lock after repeated failed sign-ins)
"""
import os
import re
import smtplib
import sqlite3
import secrets
import time
from contextlib import contextmanager
from email.message import EmailMessage

import bcrypt
import streamlit as st

APP_NAME = "OmniTalk AI"

MAX_FAILED_ATTEMPTS = 5
LOCK_SECONDS = 5 * 60
RESET_CODE_SECONDS = 15 * 60
MAX_RESET_ATTEMPTS = 5

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class AuthError(Exception):
    """Raised with a user-friendly message."""


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def _db_path() -> str:
    return os.getenv("AUTH_DB_PATH", "users.db")


@contextmanager
def _db():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT,
                provider TEXT NOT NULL DEFAULT 'email',
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS reset_codes (
                email TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                expires_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0
            )"""
        )


@st.cache_resource
def _ensure_db() -> bool:
    init_db()
    return True


# --------------------------------------------------------------------------- #
# Validation & hashing
# --------------------------------------------------------------------------- #
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def check_email(email: str) -> str:
    email = normalize_email(email)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Please enter a valid email address.")
    return email


def check_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters long.")
    if len(password.encode()) > 72:
        raise AuthError("Password must be at most 72 characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("Password must contain at least one letter and one number.")


def _hash(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def _verify(value: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode(), hashed.encode())
    except ValueError:
        return False


_DUMMY_HASH = _hash("dummy-password-for-timing")


def _public(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "provider": row["provider"]}


# --------------------------------------------------------------------------- #
# Account operations
# --------------------------------------------------------------------------- #
def sign_up(name: str, email: str, password: str, confirm: str) -> dict:
    name = (name or "").strip()
    if len(name) < 2:
        raise AuthError("Please enter your full name.")
    if len(name) > 60:
        raise AuthError("Name is too long (max 60 characters).")
    email = check_email(email)
    check_password(password)
    if password != confirm:
        raise AuthError("Passwords do not match.")

    with _db() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this email already exists. Try signing in.")
        c.execute(
            "INSERT INTO users (email, name, password_hash, provider, created_at) VALUES (?, ?, ?, 'email', ?)",
            (email, name, _hash(password), time.time()),
        )
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return _public(row)


def authenticate(email: str, password: str) -> dict:
    email = normalize_email(email)
    generic = AuthError("Invalid email or password.")
    if not email or not password:
        raise AuthError("Please enter your email and password.")

    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            _verify(password, _DUMMY_HASH)  # keep timing similar
            raise generic

        now = time.time()
        if row["locked_until"] > now:
            minutes = int((row["locked_until"] - now) // 60) + 1
            raise AuthError(f"Too many failed attempts. Try again in {minutes} minute(s).")

        if not row["password_hash"]:
            raise AuthError("This account uses Google sign-in. Please continue with Google.")

        if _verify(password, row["password_hash"]):
            c.execute("UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = ?", (row["id"],))
            return _public(row)

        attempts = row["failed_attempts"] + 1
        locked_until = now + LOCK_SECONDS if attempts >= MAX_FAILED_ATTEMPTS else 0
        if locked_until:
            attempts = 0
        c.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, row["id"]),
        )
    if locked_until:
        raise AuthError("Too many failed attempts. Your account is locked for 5 minutes.")
    raise generic


def upsert_google_user(email: str, name: str) -> dict:
    email = normalize_email(email)
    name = (name or email.split("@")[0]).strip()[:60]
    with _db() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users (email, name, password_hash, provider, created_at) VALUES (?, ?, NULL, 'google', ?)",
                (email, name, time.time()),
            )
            row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return {"id": row["id"], "email": row["email"], "name": row["name"], "provider": "google"}


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #
def start_password_reset(email: str) -> str | None:
    """Creates a 6-digit code. Returns None if no password account exists (caller must not reveal this)."""
    email = check_email(email)
    with _db() as c:
        row = c.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()
        if row is None or not row["password_hash"]:
            return None
        code = f"{secrets.randbelow(10**6):06d}"
        c.execute(
            "INSERT OR REPLACE INTO reset_codes (email, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0)",
            (email, _hash(code), time.time() + RESET_CODE_SECONDS),
        )
    return code


def complete_password_reset(email: str, code: str, new_password: str, confirm: str) -> None:
    email = check_email(email)
    invalid = AuthError("Invalid or expired code.")
    code = (code or "").strip()
    if not code:
        raise AuthError("Please enter the 6-digit code.")
    check_password(new_password)
    if new_password != confirm:
        raise AuthError("Passwords do not match.")

    with _db() as c:
        row = c.execute("SELECT * FROM reset_codes WHERE email = ?", (email,)).fetchone()
        if row is None or row["expires_at"] < time.time() or row["attempts"] >= MAX_RESET_ATTEMPTS:
            raise invalid
        if not _verify(code, row["code_hash"]):
            c.execute("UPDATE reset_codes SET attempts = attempts + 1 WHERE email = ?", (email,))
            c.commit()
            raise invalid
        c.execute(
            "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = 0 WHERE email = ?",
            (_hash(new_password), email),
        )
        c.execute("DELETE FROM reset_codes WHERE email = ?", (email,))


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def send_reset_email(email: str, code: str) -> bool:
    """Sends the code by SMTP. Returns False when SMTP is not configured (demo mode)."""
    if not smtp_configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = f"Your {APP_NAME} password reset code"
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER"))
    msg["To"] = email
    msg.set_content(
        f"Hi,\n\nYour {APP_NAME} password reset code is: {code}\n\n"
        f"It expires in {RESET_CODE_SECONDS // 60} minutes. "
        "If you didn't request this, you can safely ignore this email.\n"
    )
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587")), timeout=15) as server:
        server.starttls()
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        server.send_message(msg)
    return True


# --------------------------------------------------------------------------- #
# Google (Streamlit native OIDC)
# --------------------------------------------------------------------------- #
def google_enabled() -> bool:
    if not hasattr(st, "login"):
        return False
    try:
        return "google" in st.secrets["auth"]
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Session helpers
# --------------------------------------------------------------------------- #
def current_user() -> dict | None:
    if google_enabled() and getattr(st.user, "is_logged_in", False):
        email = getattr(st.user, "email", None)
        if email:
            if st.session_state.get("_google_synced") != email:
                st.session_state["_google_user"] = upsert_google_user(email, getattr(st.user, "name", ""))
                st.session_state["_google_synced"] = email
            return st.session_state["_google_user"]
    return st.session_state.get("auth_user")


def logout() -> None:
    was_google = (current_user() or {}).get("provider") == "google" and google_enabled()
    st.session_state.clear()
    if was_google:
        st.logout()
    else:
        st.rerun()


def _set_view(view: str) -> None:
    st.session_state["auth_view"] = view


def _flash(kind: str, message: str) -> None:
    st.session_state["auth_flash"] = (kind, message)


def _show_flash() -> None:
    flash = st.session_state.pop("auth_flash", None)
    if flash:
        {"success": st.success, "error": st.error, "info": st.info}[flash[0]](flash[1])


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"] { display: none; }
.block-container { max-width: 1100px; padding-top: 3.5rem; }
[data-testid="stForm"] { border: none; padding: 0; }
.brand { font-size: 1.5rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 2.2rem; }
.brand span { background: linear-gradient(90deg, #6366F1, #A855F7);
              -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.hero-title { font-size: 2.7rem; font-weight: 800; line-height: 1.12; letter-spacing: -0.03em; }
.hero-title span { background: linear-gradient(90deg, #6366F1, #A855F7);
                   -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.hero-sub { font-size: 1.05rem; opacity: .75; margin: 1rem 0 1.8rem; max-width: 30rem; }
.feature { display: flex; gap: .85rem; margin: 1.05rem 0; align-items: flex-start; }
.feature .ico { font-size: 1.25rem; line-height: 1.5; }
.feature b { display: block; }
.feature small { opacity: .7; font-size: .9rem; }
.divider { display: flex; align-items: center; opacity: .6; font-size: .8rem; margin: 1.1rem 0; }
.divider::before, .divider::after { content: ""; flex: 1; border-bottom: 1px solid currentColor; opacity: .3; }
.divider span { padding: 0 .8rem; text-transform: uppercase; letter-spacing: .06em; }
.legal { font-size: .78rem; opacity: .6; text-align: center; margin-top: 1rem; }
</style>
"""


def _hero() -> None:
    st.markdown(f'<div class="brand">🎙️ <span>{APP_NAME}</span></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-title">Talk to any <span>video or audio</span>.</div>'
        '<div class="hero-sub">Turn YouTube videos and recordings into searchable knowledge: '
        "transcripts, instant summaries, and a chatbot that answers from the source.</div>"
        '<div class="feature"><div class="ico">⚡</div><div><b>Instant summaries</b>'
        "<small>Executive summaries of hours of content in seconds.</small></div></div>"
        '<div class="feature"><div class="ico">💬</div><div><b>Chat with your media</b>'
        "<small>Ask follow-up questions and see the exact sources.</small></div></div>"
        '<div class="feature"><div class="ico">🌍</div><div><b>Any language</b>'
        "<small>Translate to English or keep the original language.</small></div></div>"
        '<div class="feature"><div class="ico">🔒</div><div><b>Private by design</b>'
        "<small>Your API key and data stay in your own session.</small></div></div>",
        unsafe_allow_html=True,
    )


def _google_button() -> None:
    if google_enabled():
        if st.button("Continue with Google", icon=":material/account_circle:", use_container_width=True, key="g_btn"):
            st.login("google")
    else:
        st.button(
            "Continue with Google",
            icon=":material/account_circle:",
            use_container_width=True,
            disabled=True,
            help="Google sign-in is not configured yet. See the README for setup.",
            key="g_btn_off",
        )
    st.markdown('<div class="divider"><span>or continue with email</span></div>', unsafe_allow_html=True)


def _view_signin() -> None:
    st.markdown("### Welcome back 👋")
    st.caption("Sign in to continue to your workspace.")
    _show_flash()
    _google_button()

    with st.form("signin_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", placeholder="Your password")
        submit = st.form_submit_button("Sign in", type="primary", use_container_width=True)
    if submit:
        try:
            st.session_state["auth_user"] = authenticate(email, password)
        except AuthError as e:
            st.error(str(e))
        else:
            st.rerun()

    c1, c2 = st.columns(2)
    c1.button("Forgot password?", on_click=_set_view, args=("forgot",), use_container_width=True, key="to_forgot")
    c2.button("Create account", on_click=_set_view, args=("signup",), use_container_width=True, key="to_signup")


def _view_signup() -> None:
    st.markdown("### Create your account")
    st.caption("Start chatting with your media in under a minute.")
    _google_button()

    with st.form("signup_form"):
        name = st.text_input("Full name", placeholder="Jane Doe")
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password", help="At least 8 characters, with a letter and a number.")
        confirm = st.text_input("Confirm password", type="password")
        agree = st.checkbox("I agree to the Terms of Service and Privacy Policy")
        submit = st.form_submit_button("Create account", type="primary", use_container_width=True)
    if submit:
        try:
            if not agree:
                raise AuthError("Please accept the Terms of Service and Privacy Policy to continue.")
            st.session_state["auth_user"] = sign_up(name, email, password, confirm)
        except AuthError as e:
            st.error(str(e))
        else:
            st.rerun()

    st.button("Already have an account? Sign in", on_click=_set_view, args=("signin",), use_container_width=True, key="to_signin")


def _view_forgot() -> None:
    st.markdown("### Forgot your password?")
    st.caption("Enter your email and we'll send you a 6-digit reset code.")

    with st.form("forgot_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        submit = st.form_submit_button("Send reset code", type="primary", use_container_width=True)
    if submit:
        try:
            code = start_password_reset(email)
            st.session_state["reset_email"] = normalize_email(email)
            st.session_state["demo_code"] = None
            if code:
                sent = send_reset_email(st.session_state["reset_email"], code)
                if not sent:
                    st.session_state["demo_code"] = code
        except AuthError as e:
            st.error(str(e))
        except Exception:
            st.error("We couldn't send the email right now. Please try again later.")
        else:
            _flash("info", "If an account exists for that email, a reset code has been sent.")
            _set_view("reset")
            st.rerun()

    st.button("← Back to sign in", on_click=_set_view, args=("signin",), use_container_width=True, key="back_signin1")


def _view_reset() -> None:
    email = st.session_state.get("reset_email")
    if not email:
        _set_view("forgot")
        st.rerun()

    st.markdown("### Set a new password")
    st.caption(f"Enter the code sent to **{email}** and choose a new password.")
    _show_flash()
    if st.session_state.get("demo_code"):
        st.warning(f"Demo mode (email is not configured). Your reset code is **{st.session_state['demo_code']}**.")

    with st.form("reset_form"):
        code = st.text_input("6-digit code", max_chars=6, placeholder="123456")
        password = st.text_input("New password", type="password", help="At least 8 characters, with a letter and a number.")
        confirm = st.text_input("Confirm new password", type="password")
        submit = st.form_submit_button("Reset password", type="primary", use_container_width=True)
    if submit:
        try:
            complete_password_reset(email, code, password, confirm)
        except AuthError as e:
            st.error(str(e))
        else:
            st.session_state.pop("reset_email", None)
            st.session_state.pop("demo_code", None)
            _flash("success", "Password updated. You can now sign in.")
            _set_view("signin")
            st.rerun()

    c1, c2 = st.columns(2)
    c1.button("Resend code", on_click=_set_view, args=("forgot",), use_container_width=True, key="resend")
    c2.button("← Back to sign in", on_click=_set_view, args=("signin",), use_container_width=True, key="back_signin2")


def render_auth_page() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.session_state.setdefault("auth_view", "signin")

    left, right = st.columns([1.15, 1], gap="large")
    with left:
        _hero()
    with right:
        with st.container(border=True):
            {
                "signin": _view_signin,
                "signup": _view_signup,
                "forgot": _view_forgot,
                "reset": _view_reset,
            }.get(st.session_state["auth_view"], _view_signin)()
        st.markdown(
            f'<div class="legal">© {APP_NAME}. Your password is encrypted and never stored in plain text.</div>',
            unsafe_allow_html=True,
        )


def require_login() -> dict:
    """Call right after st.set_page_config(). Shows the auth page and stops unless a user is signed in."""
    _ensure_db()
    user = current_user()
    if user:
        return user
    render_auth_page()
    st.stop()
