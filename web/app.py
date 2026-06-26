from flask import Flask
import os
import threading
import logging
from datetime import datetime, timezone

# Flask-SocketIO – gevent (eventlet ist deprecated)
try:
    from flask_socketio import SocketIO
    _HAS_SOCKETIO = True
except ImportError:
    _HAS_SOCKETIO = False
    SocketIO = None

from .config import SESSION_SECRET
from .auth import auth_bp

log = logging.getLogger("ModForge.Web.App")

flask_app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)
flask_app.secret_key = SESSION_SECRET
# Dashboard-/Admin-Cookies sollen Neustarts überleben; Login-Session selbst liegt für Discord zusätzlich in MongoDB.
flask_app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30

# SocketIO: gevent wenn verfügbar, sonst sicherer Threading-Fallback.
if _HAS_SOCKETIO:
    try:
        socketio = SocketIO(flask_app, cors_allowed_origins="*", async_mode="gevent")
        log.info("SocketIO läuft mit gevent.")
    except ValueError:
        socketio = SocketIO(flask_app, cors_allowed_origins="*", async_mode="threading")
        log.warning("gevent nicht verfügbar – SocketIO nutzt threading-Fallback.")
else:
    socketio = None
    log.warning("Flask-SocketIO nicht installiert – Live-Status deaktiviert.")

# Auth-Blueprint (OAuth2) registrieren
flask_app.register_blueprint(auth_bp)

# Deine bestehenden Routen (Landing, Dashboard, Live …)
from . import routes as _routes  # noqa: E402
_ = _routes  # Routen-Import bewusst: registriert Flask-Endpoints
# ───────────────────────────────────────────────────────────
# HEALTH CHECK (Railway Monitoring)
# ───────────────────────────────────────────────────────────
@flask_app.route("/health")
def health():
    """Health-Check für Railway / Uptime-Monitoring."""
    try:
        from bot.bot import BOT_REF
        bot_ok = BOT_REF is not None and getattr(BOT_REF, "is_ready", lambda: False)()
    except Exception:
        bot_ok = False
    from bot.config import get_uptime
    return {
        "status": "ok",
        "bot": bot_ok,
        "uptime": get_uptime(),
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ───────────────────────────────────────────────────────────
# Live-Status-Emitter
#
# Vorher wurden hier *zufällige* Demo-Werte gesendet, was die
# Live-Seite irreführend gemacht hat. Wir nutzen jetzt:
#   • den echten Bot-Status (Ready / Latenz / Guild-Count)
#   • die echte Activity-Queue aus bot.config.ACTIVITY
#   • einen plausiblen Protection-Score aus der DB-Konfiguration
# ───────────────────────────────────────────────────────────
def _module_active(cfg: dict, key: str) -> bool:
    mod = cfg.get(key, {}) if isinstance(cfg, dict) else {}
    return bool(isinstance(mod, dict) and mod.get("enabled"))


def _collect_status() -> dict:
    """Sammelt den Live-Status aus den echten ModForge-Quellen."""
    try:
        from bot.bot import BOT_REF
    except Exception:
        BOT_REF = None

    bot_online = bool(
        BOT_REF is not None and getattr(BOT_REF, "is_ready", lambda: False)()
    )
    latency_ms = 0
    guild_count = 0
    member_count = 0

    if bot_online:
        try:
            latency_ms = round((BOT_REF.latency or 0) * 1000, 1)
        except Exception:
            latency_ms = 0
        try:
            guild_count = len(BOT_REF.guilds)
            member_count = sum((g.member_count or 0) for g in BOT_REF.guilds)
        except Exception:
            pass

    # Protection-Score: prozentualer Anteil aktiver Module über alle Guilds.
    # Wenn der Bot offline ist, geben wir 0 zurück – ehrlicher als 95 % aus dem Nichts.
    protection = {"raid": 0, "spam": 0, "scam": 0, "invite": 0}
    if bot_online and getattr(BOT_REF, "db", None) is not None:
        try:
            guilds = list(BOT_REF.guilds)
            n = max(1, len(guilds))
            counters = {"raid": 0, "spam": 0, "scam": 0, "invite": 0}
            for g in guilds:
                cfg = BOT_REF.db.get_config(g.id) or {}
                if _module_active(cfg, "anti_raid"):
                    counters["raid"] += 1
                if _module_active(cfg, "anti_spam"):
                    counters["spam"] += 1
                if _module_active(cfg, "anti_scam"):
                    counters["scam"] += 1
                am = cfg.get("automod", {}) if isinstance(cfg, dict) else {}
                if isinstance(am, dict) and am.get("invite_filter"):
                    counters["invite"] += 1
            protection = {k: int(round(v * 100 / n)) for k, v in counters.items()}
        except Exception as e:
            log.debug(f"protection-score error: {e}")

    # Letzte Aktivitäten aus dem Ring-Buffer
    activity = []
    try:
        from bot.config import ACTIVITY

        activity = ACTIVITY.snapshot(20)
    except Exception:
        activity = []

    return {
        "systems": {
            "bot": bot_online,
            "database": bool(
                BOT_REF is not None and getattr(BOT_REF, "db", None) is not None
            ),
            "api": True,
            "raid": bot_online,
            "automod": bot_online,
        },
        "bot": {
            "ready": bot_online,
            "latency_ms": latency_ms,
            "guilds": guild_count,
            "members": member_count,
        },
        "protection": protection,
        "activity": activity,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def background_emitter():
    if socketio is None:
        return
    while True:
        socketio.sleep(3)  # alle 3 Sekunden
        try:
            socketio.emit("status_update", _collect_status())
        except Exception as e:
            log.debug(f"status_update emit failed: {e}")


if _HAS_SOCKETIO and socketio is not None:
    @socketio.on("connect")
    def handle_connect():
        # Sofortigen Snapshot schicken, damit der Client nicht 3 s warten muss.
        try:
            socketio.emit("status_update", _collect_status())
        except Exception:
            pass

    @socketio.on("disconnect")
    def handle_disconnect():
        # Bewusst kein Logging-Spam.
        pass


_emitter_started = False
_emitter_lock = threading.Lock()


def _ensure_emitter():
    global _emitter_started
    if socketio is None:
        return
    with _emitter_lock:
        if _emitter_started:
            return
        _emitter_started = True
        socketio.start_background_task(background_emitter)


def run_flask():
    port = int(os.getenv("PORT", "7860"))
    _ensure_emitter()
    if _HAS_SOCKETIO and socketio is not None:
        # gevent WSGI server (zuverlässig)
        socketio.run(flask_app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
    else:
        # Fallback: normaler Flask-Server ohne SocketIO
        flask_app.run(host="0.0.0.0", port=port, debug=False)


def keep_alive():
    threading.Thread(target=run_flask, daemon=True).start()
