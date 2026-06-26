# web/auth.py
import os
import time
import json
import secrets
import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from functools import wraps

from flask import Blueprint, request, redirect, make_response, session as flask_session

log = logging.getLogger("ModForge.Auth")

# Umgebungsvariablen
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DASHBOARD_BASE_URL = os.getenv(
    "DASHBOARD_BASE_URL", "http://mod-forge.up.railway.app"
).rstrip("/")

REDIRECT_URI = f"{DASHBOARD_BASE_URL}/dashboard/auth/callback"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "modforge_session"

# Persistente Session Store: Memory + MongoDB-Fallback.
# Dadurch bleibt Dashboard-Login nach Bot/Web-Neustart erhalten, solange Cookie + DB-Session gültig sind.
sessions = {}
SESSION_TTL = int(os.getenv("DASHBOARD_SESSION_TTL", str(30 * 24 * 3600)))
_SESSION_COL = None
_SESSION_DB_TRIED = False


def _sessions_col():
    global _SESSION_COL, _SESSION_DB_TRIED
    if _SESSION_DB_TRIED:
        return _SESSION_COL
    _SESSION_DB_TRIED = True
    mongo_url = os.getenv("MONGO_URL")
    if not mongo_url:
        return None
    try:
        from pymongo import MongoClient
        client = MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=2500,
            connectTimeoutMS=2500,
            socketTimeoutMS=5000,
            tlsAllowInvalidCertificates=True,
        )
        client.admin.command("ping")
        _SESSION_COL = client["ModForge"]["dashboard_sessions"]
        _SESSION_COL.create_index("sid", unique=True)
        _SESSION_COL.create_index("user.id")
        _SESSION_COL.create_index("expires_at")
    except Exception as e:
        log.warning(f"Dashboard session DB disabled: {e}")
        _SESSION_COL = None
    return _SESSION_COL


def _persist_session(sid: str, data: dict) -> None:
    sessions[sid] = data
    col = _sessions_col()
    if col is None:
        return
    try:
        doc = dict(data)
        doc["sid"] = sid
        doc["expires_at"] = time.time() + SESSION_TTL
        doc["updated_at"] = time.time()
        col.update_one({"sid": sid}, {"$set": doc, "$setOnInsert": {"created_at_db": time.time()}}, upsert=True)
    except Exception as e:
        log.debug(f"Session persist failed: {e}")


def _load_session(sid: str):
    data = sessions.get(sid)
    if data:
        return data
    col = _sessions_col()
    if col is None:
        return None
    try:
        doc = col.find_one({"sid": sid})
        if not doc:
            return None
        doc.pop("_id", None)
        doc.pop("sid", None)
        sessions[sid] = doc
        return doc
    except Exception as e:
        log.debug(f"Session load failed: {e}")
        return None


def _delete_session(sid: str) -> None:
    sessions.pop(sid, None)
    col = _sessions_col()
    if col is not None:
        try:
            col.delete_one({"sid": sid})
        except Exception:
            pass


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [sid for sid, data in sessions.items() if now - data.get("created_at", 0) > SESSION_TTL]
    for sid in expired:
        sessions.pop(sid, None)
    col = _sessions_col()
    if col is not None:
        try:
            col.delete_many({"expires_at": {"$lt": now}})
        except Exception:
            pass


def _cookie_secure() -> bool:
    return request.is_secure or request.headers.get("X-Forwarded-Proto", "").split(",")[0].strip() == "https"


auth_bp = Blueprint("auth", __name__, template_folder="templates")


def _make_session_id():
    return secrets.token_hex(32)


def _api_request(url, method="GET", data=None, headers=None):
    """HTTP-Request mit User-Agent (Discord blockiert ohne)."""
    headers = headers or {}
    headers["User-Agent"] = "ModForge-Dashboard (https://mod-forge.up.railway.app, 2.0)"

    body = None
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as e:
        error_body = e.read().decode("utf-8", errors="ignore")
        log.error(f"Discord API {e.code}: {error_body[:500]}")
        raise Exception(f"HTTP {e.code}: {error_body[:200]}")
    except URLError as e:
        log.error(f"URL Error: {e.reason}")
        raise Exception(f"URL error: {e.reason}")


@auth_bp.route("/dashboard/login")
def login():
    """Leitet zu Discord OAuth2 weiter."""
    _cleanup_sessions()
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        log.error(
            f"OAuth not configured: ID={bool(DISCORD_CLIENT_ID)} SECRET={bool(DISCORD_CLIENT_SECRET)}"
        )
        return (
            "Dashboard auth not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.",
            503,
        )

    state = secrets.token_urlsafe(16)
    flask_session["oauth_state"] = state

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds guilds.join",
        # Standard sicher: consent. Persistenz passiert über DB-Session + Browser-Cookie, nicht über erneutes OAuth.
        "prompt": request.args.get("prompt", "consent"),
        "state": state,
    }
    auth_url = f"https://discord.com/oauth2/authorize?{urlencode(params)}"
    log.info(f"OAuth2 login redirect → {auth_url[:120]}...")
    return redirect(auth_url, code=302)


@auth_bp.route("/dashboard/auth/callback")
def callback():
    """Verarbeitet den OAuth2-Callback von Discord."""
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    error_desc = request.args.get("error_description", "")
    session_state = flask_session.pop("oauth_state", None)

    # User hat abgelehnt
    if error:
        log.warning(f"OAuth2 denied: {error} – {error_desc}")
        return redirect(f"/login?error=Login abgebrochen: {error_desc or error}")

    # State-Prüfung
    if not code:
        log.warning("OAuth2 callback: kein code")
        return redirect(
            "/login?error=Kein Autorisierungs-Code erhalten. Bitte erneut versuchen."
        )

    if state != session_state:
        log.warning(f"OAuth2 state mismatch: got={state}, expected={session_state}")
        return redirect("/login?error=Session abgelaufen. Bitte erneut versuchen.")

    # --- Token abrufen ---
    try:
        log.info(f"Token exchange: redirect_uri={REDIRECT_URI}")
        token_data = _api_request(
            f"{DISCORD_API}/oauth2/token",
            method="POST",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
    except Exception as e:
        log.error(f"Token exchange failed: {e}")
        return redirect(f"/login?error=Token-Fehler: {str(e)[:100]}")

    access_token = token_data.get("access_token")
    if not access_token:
        log.error(f"No access_token in response: {token_data}")
        err_desc = token_data.get(
            "error_description", token_data.get("error", "Unbekannt")
        )
        return redirect(f"/login?error=Discord Token-Fehler: {err_desc}")

    # --- User-Profil laden ---
    try:
        user = _api_request(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        log.error(f"User fetch failed: {e}")
        return redirect("/login?error=Profil konnte nicht geladen werden.")

    # --- Serverliste laden ---
    try:
        guilds = _api_request(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except Exception as e:
        log.warning(f"Guilds fetch failed (continuing without): {e}")
        guilds = []

    # Avatar-URL
    avatar_hash = user.get("avatar")
    user_id = user.get("id", "0")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
        if avatar_hash
        else f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    )

    # Session erstellen + persistent in MongoDB speichern
    session_id = _make_session_id()
    refresh_token = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in") or SESSION_TTL)
    session_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": time.time() + expires_in,
        "created_at": time.time(),
        "last_seen": time.time(),
        "user": {
            "id": user_id,
            "username": user.get("username", "Discord User"),
            "global_name": user.get("global_name"),
            "avatar_url": avatar_url,
        },
        "guilds": guilds if isinstance(guilds, list) else [],
    }
    _persist_session(session_id, session_data)

    log.info(
        f"Login OK: {user.get('username')} ({user_id}), {len(guilds) if isinstance(guilds, list) else 0} guilds"
    )

    # Cookie setzen
    resp = make_response(redirect("/dashboard"))
    resp.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        path="/",
        secure=_cookie_secure(),
        max_age=SESSION_TTL,
    )
    return resp


@auth_bp.route("/dashboard/logout")
def logout():
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        _delete_session(sid)
    resp = make_response(redirect("/"))
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


def get_session():
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    session = _load_session(sid)
    if not session or time.time() - session.get("created_at", 0) > SESSION_TTL:
        _delete_session(sid)
        return None
    session["last_seen"] = time.time()
    # Memory + DB aktualisieren, damit aktive Browser-Logins nicht bei jedem Restart sterben.
    _persist_session(sid, session)
    return session


def refresh_session_guilds(sid: str = None):
    """Aktualisiert gespeicherte Discord-Guilds in DB/Memory, wenn Access Token gültig ist."""
    sid = sid or request.cookies.get(SESSION_COOKIE)
    data = _load_session(sid) if sid else None
    if not data:
        return None
    token = data.get("access_token")
    if not token:
        return data
    try:
        guilds = _api_request(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {token}"},
        )
        if isinstance(guilds, list):
            data["guilds"] = guilds
            data["guilds_refreshed_at"] = time.time()
            _persist_session(sid, data)
    except Exception as e:
        log.warning(f"Guild refresh failed: {e}")
    return data


def get_all_persisted_sessions(limit: int = 500):
    col = _sessions_col()
    if col is None:
        return [{"sid": sid, **data} for sid, data in sessions.items()]
    try:
        rows = list(col.find({}).sort("last_seen", -1).limit(limit))
        for row in rows:
            row.pop("_id", None)
        return rows
    except Exception as e:
        log.warning(f"Load persisted sessions failed: {e}")
        return []


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not get_session() and not flask_session.get("admin"):
            return redirect("/dashboard/login")
        return f(*args, **kwargs)

    return wrapper
