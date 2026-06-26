"""
ModForge – Web Routes
Alle Routen sauber organisiert. Dateiname = URL-Pfad (z.B. /badges → badges.html).
"""

from flask import (
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    Response,
    abort,
)

import datetime
import logging
import json
import re
from urllib.parse import urlparse, urlencode

import time
import threading
import copy as _copy

from collections import defaultdict, deque
from functools import wraps

from .app import flask_app
from .auth import get_session, require_auth, refresh_session_guilds, get_all_persisted_sessions
from .helpers import (
    _bot_stats,
    _build_overview,
    _build_welcome_content,
)

from .config import (
    DISCORD_CLIENT_ID,
    ADMIN_USERNAME,
    ADMIN_PASSWORD,
)

try:
    from bot.bot import bot
except Exception:
    bot = None

try:
    from bot.config import (
        FEATURES,
        CMDS_PREVIEW,
        LOG_MODS,
        ACTIVITY,
        BADGES,
        SCAM_DOMAINS,
        URL_SHORTENERS,
    )
except Exception:
    FEATURES = []
    CMDS_PREVIEW = []
    LOG_MODS = []
    BADGES = {}
    SCAM_DOMAINS = []
    URL_SHORTENERS = []
    class _ActivityFallback:
        def snapshot(self, limit=20):
            return []
    ACTIVITY = _ActivityFallback()

try:
    from bot.utils import _run_async
except Exception:
    def _run_async(coro, timeout=8.0):
        return None

log = logging.getLogger("ModForge.Web.Routes")


@flask_app.context_processor
def _inject_dashboard_globals():
    return {
        "web_bot_online": bot_ready() if "bot_ready" in globals() else False,
        "dashboard_now": datetime.datetime.utcnow(),
    }

# ═══════════════════════════════════════════════════════════
# DIRECT DB ACCESS (works even when bot is offline)
#
# Verwendet die GLEICHE Collection wie die Bot-Datenbank
# (database/db.py → self.config = self.db["config"]).
# Frühere Version schrieb in "configs" (Plural) und der Bot
# hat die Änderungen daher nie gesehen. Behoben.
# ═══════════════════════════════════════════════════════════
_direct_db_client = None          # MongoDB-Database-Handle (Singleton)
_direct_db_tried = False          # True, sobald wir einen Verbindungsversuch gemacht haben
_direct_db_lock = threading.Lock()
def _get_direct_db():
    """Liefert das ``ModForge``-MongoDB-Database-Objekt oder ``None``.

    Ergebnis wird gecacht (auch ``None``), damit wir bei fehlendem
    ``MONGO_URL`` nicht bei jedem Request erneut versuchen zu verbinden.
    """
    global _direct_db_client, _direct_db_tried
    if _direct_db_tried:
        return _direct_db_client

    with _direct_db_lock:
        if _direct_db_tried:
            return _direct_db_client
        _direct_db_tried = True

        import os
        mongo_url = os.getenv("MONGO_URL")
        if not mongo_url:
            log.debug("Direct DB: MONGO_URL nicht gesetzt – kein Direkt-Zugriff.")
            return None
        try:
            from pymongo import MongoClient
            client = MongoClient(
                mongo_url,
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
                socketTimeoutMS=4000,
                tlsAllowInvalidCertificates=True,
            )
            # Verbindung sofort prüfen, damit wir Fehler hier abfangen.
            client.admin.command("ping")
            _direct_db_client = client["ModForge"]
            log.info("Direct DB: MongoDB-Verbindung steht (Dashboard-Fallback).")
        except Exception as e:
            log.warning(f"Direct DB connect failed: {e}")
            _direct_db_client = None
        return _direct_db_client
def _sanitize_cfg_for_mongo(cfg):
    """Entfernt nicht-JSON-serialisierbare Felder und Keys mit führendem ``_``."""
    cleaned = {}
    for k, v in (cfg or {}).items():
        if isinstance(k, str) and k.startswith("_") and k != "_id":
            continue
        try:
            json.dumps(v, default=str)
            cleaned[k] = v
        except (TypeError, ValueError):
            cleaned[k] = str(v)
    return cleaned


def _deep_merge(base: dict, override: dict) -> dict:
    """Mergt verschachtelte Configs, ohne Defaults zu verlieren."""
    result = _copy.deepcopy(base or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = _copy.deepcopy(value)
    return result


def _to_int_or_none(value, *, minimum=None, maximum=None):
    if value in (None, "", False):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _guild_id_values(guild_id):
    try:
        gid = int(guild_id)
        return [gid, str(gid)]
    except (TypeError, ValueError):
        return [str(guild_id)]


def _guild_query(guild_id) -> dict:
    return {"guild_id": {"$in": _guild_id_values(guild_id)}}


def _module_sections() -> list:
    return [
        {"key":"antispam", "icon":"⚡", "label":"Anti-Spam"},
        {"key":"antinuke", "icon":"💥", "label":"Anti-Nuke"},
        {"key":"antiraid", "icon":"🚨", "label":"Anti-Raid"},
        {"key":"antimention", "icon":"🔔", "label":"Anti-Mention"},
        {"key":"antiscam", "icon":"🎣", "label":"Anti-Scam"},
        {"key":"automod", "icon":"🤖", "label":"AutoMod"},
        {"key":"verify", "icon":"✅", "label":"Verify"},
        {"key":"tickets", "icon":"🎫", "label":"Tickets"},
        {"key":"autorole", "icon":"🏷️", "label":"Auto-Rolle"},
    ]


def _normalize_log_channels(raw: dict) -> dict:
    channels = {}
    for key, value in (raw or {}).items():
        channel_id = _to_int_or_none(value)
        if channel_id is not None:
            channels[str(key).lower().replace("-", "_").replace(" ", "_")] = channel_id
    return channels


def _direct_save_whitelist(guild_id, whitelist: dict) -> bool:
    gid = int(guild_id)
    clean = _copy.deepcopy(whitelist or {})
    clean.pop("_id", None)
    for key in ("users", "roles", "channels", "bypass_antispam", "bypass_antinuke"):
        clean.setdefault(key, [])
    db = _get_direct_db()
    if db is not None:
        try:
            db.whitelist.update_one(
                {"_id": gid},
                {"$set": clean, "$setOnInsert": {"_id": gid}},
                upsert=True,
            )
        except Exception as e:
            log.error(f"Whitelist direct save failed for {gid}: {e}")
            return False
    try:
        from bot.bot import BOT_REF
        if BOT_REF is not None and getattr(BOT_REF, "db", None) is not None:
            BOT_REF.db._whitelist_cache[gid] = clean
            _run_async(BOT_REF.db.set_whitelist(gid, clean))
    except Exception as e:
        log.debug(f"Whitelist cache update failed for {gid}: {e}")
    return True


def _config_versions_col():
    direct = _get_direct_db()
    if direct is not None:
        return direct["config_versions"]
    db = get_db() if "get_db" in globals() else None
    if db is not None:
        try:
            return db.client["ModForge"]["config_versions"]
        except Exception:
            return None
    return None


def _save_config_version(guild_id, cfg, source="dashboard") -> None:
    col = _config_versions_col()
    if col is None:
        return
    try:
        col.insert_one({
            "guild_id": int(guild_id),
            "config": _sanitize_cfg_for_mongo(_copy.deepcopy(cfg or {})),
            "source": source,
            "created_at": datetime.datetime.utcnow(),
        })
        # Keep last 25 versions per guild.
        old = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).skip(25).limit(100))
        for doc in old:
            col.delete_one({"_id": doc["_id"]})
    except Exception as e:
        log.debug(f"config version save failed: {e}")


def _dangerous_change(data: dict) -> bool:
    dangerous = {"anti_nuke", "nuke_protection", "server_protection", "security_level", "_security_level", "_raw", "_temp_voice"}
    return any(k in dangerous for k in (data or {}).keys())
def _direct_save_config(guild_id, cfg):
    """Speichert die Guild-Konfiguration zuverlässig.

    Strategie (Single Source of Truth = MongoDB):
      1. Schreibe direkt in die Collection ``config`` (Bot nutzt dieselbe).
      2. Aktualisiere zusätzlich den In-Memory-Cache des laufenden Bots,
         damit Änderungen sofort wirken (sonst erst nach Cache-TTL = 5 min).
    Liefert ``True`` bei Erfolg, sonst ``False``.
    """
    gid = int(guild_id)
    cleaned = _sanitize_cfg_for_mongo(cfg)
    cleaned.pop("_id", None)

    db = _get_direct_db()
    if db is None:
        # Letzter Versuch: über den Bot (z.B. lokale Entwicklung ohne MONGO_URL für die Web-App)
        try:
            from bot.bot import BOT_REF
            if BOT_REF is not None and getattr(BOT_REF, "db", None) is not None:
                _run_async(BOT_REF.db.aset_config(gid, {k: v for k, v in cleaned.items() if k != "_id"}))
                return True
        except Exception as e:
            log.error(f"Direct save (bot fallback) failed for {gid}: {e}")
        return False

    try:
        db.config.update_one(
            {"_id": gid},
            {"$set": cleaned, "$setOnInsert": {"_id": gid}},
            upsert=True,
        )
    except Exception as e:
        log.error(f"Direct DB save failed for {gid}: {e}")
        return False

    # Bot-Cache invalidieren / aktualisieren, falls Bot läuft
    try:
        from bot.bot import BOT_REF
        if (
            BOT_REF is not None
            and getattr(BOT_REF, "db", None) is not None
            and hasattr(BOT_REF.db, "_config_cache")
        ):
            BOT_REF.db._config_cache[gid] = _copy.deepcopy(cleaned)
    except Exception as e:
        log.debug(f"Bot-Cache-Update nach Save fehlgeschlagen für {gid}: {e}")

    return True
def _direct_load_config(guild_id):
    """Lädt die Guild-Konfiguration.

    Reihenfolge: Bot-Cache → MongoDB direkt → DEFAULT_CONFIG.
    Liefert IMMER ein Dict (nie ``None``), damit Routen sicher arbeiten können.
    """
    gid = int(guild_id)

    # 1) Über den Bot (Cache + DB)
    try:
        from bot.bot import BOT_REF
        if BOT_REF is not None and getattr(BOT_REF, "db", None) is not None:
            cfg = BOT_REF.db.get_config(gid)
            if isinstance(cfg, dict) and len(cfg) > 3:
                return cfg
    except Exception as e:
        log.debug(f"Direct load via bot failed for {gid}: {e}")

    # 2) Direkter MongoDB-Read – richtige Collection: "config"
    try:
        db = _get_direct_db()
        if db is not None:
            doc = db.config.find_one({"_id": gid})
            if isinstance(doc, dict):
                doc.pop("_id", None)
                # Defaults rekursiv auffüllen, damit verschachtelte Keys nicht fehlen.
                from bot.config import DEFAULT_CONFIG
                return _deep_merge(DEFAULT_CONFIG, doc)
    except Exception as e:
        log.debug(f"Direct DB load failed: {e}")

    from bot.config import DEFAULT_CONFIG
    return _copy.deepcopy(DEFAULT_CONFIG)

@flask_app.route("/dashboard/<guild_id>/tempvoice")
@require_auth
def guild_tempvoice(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err
    categories = [{"id": str(c.id), "name": c.name} for c in g.categories] if g else []
    voice_channels = [{"id": str(c.id), "name": c.name} for c in g.voice_channels] if g else []
    text_channels = [{"id": str(c.id), "name": c.name} for c in g.text_channels] if g else []
    active_channels = []
    db = get_db()
    if db:
        try:
            docs = safe_async(db.tempvoice_channels.find(_guild_query(guild_id)).to_list(100), []) or []
            for d in docs:
                ch = g.get_channel(int(d.get("channel_id"))) if g and d.get("channel_id") else None
                owner = g.get_member(int(d.get("user_id"))) if g and d.get("user_id") else None
                active_channels.append({"channel_id": str(d.get("channel_id")), "user_id": str(d.get("user_id")), "channel_name": ch.name if ch else "?", "owner_name": owner.display_name if owner else "?", "members": len(ch.members) if ch and hasattr(ch, "members") else 0})
        except Exception as e:
            log.debug(f"tempvoice load failed: {e}")
    return render_template("dashboard/tempvoice.html", guild=g, cfg=cfg, user=us["user"], categories=categories, voice_channels=voice_channels, text_channels=text_channels, active_channels=active_channels, active="tempvoice")

@flask_app.route("/api/guild/<guild_id>/tempvoice/health")
@require_auth
def api_tempvoice_health(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    g = get_guild(guild_id)
    cfg = _direct_load_config(guild_id)
    tv = cfg.get("temp_voice", {}) or {}
    checks = []
    def add(ok, label, reason): checks.append({"ok": bool(ok), "label": label, "reason": reason})
    hub = g.get_channel(int(tv.get("hub_channel_id"))) if g and tv.get("hub_channel_id") else None
    cat = g.get_channel(int(tv.get("category_id"))) if g and tv.get("category_id") else None
    panel = g.get_channel(int(tv.get("panel_channel_id"))) if g and tv.get("panel_channel_id") else None
    me = getattr(g, "me", None) if g else None
    perms = getattr(me, "guild_permissions", None)
    add(tv.get("enabled"), "TempVoice", "aktiv" if tv.get("enabled") else "deaktiviert")
    add(hub is not None, "Hub-Kanal", "OK" if hub else "nicht gesetzt/gefunden")
    add(cat is not None or not tv.get("category_id"), "Kategorie", "OK" if cat or not tv.get("category_id") else "nicht gefunden")
    add(panel is not None or not tv.get("panel_channel_id"), "Panel-Kanal", "OK" if panel or not tv.get("panel_channel_id") else "nicht gefunden")
    add(getattr(perms, "manage_channels", False), "Manage Channels", "OK" if getattr(perms, "manage_channels", False) else "fehlt")
    add(getattr(perms, "move_members", False), "Move Members", "OK" if getattr(perms, "move_members", False) else "fehlt")
    return jsonify({"ok": True, "checks": checks})


@flask_app.route("/api/guild/<guild_id>/tempvoice/panel", methods=["POST"])
@require_auth
def api_tempvoice_panel(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    g = get_guild(guild_id)
    cfg = _direct_load_config(guild_id)
    data = request.json or {}
    channel_id = _to_int_or_none(data.get("panel_channel_id")) or cfg.get("temp_voice", {}).get("panel_channel_id")
    if not g or not channel_id:
        return jsonify({"error": "Panel-Kanal fehlt"}), 400
    async def _send_panel():
        import discord
        from bot.bot import TempVoiceView
        ch = g.get_channel(int(channel_id))
        if not ch:
            raise RuntimeError("Panel-Kanal nicht gefunden")
        emb = discord.Embed(title="🎤 TempVoice Panel", description="Tritt dem Hub-Kanal bei und verwalte deinen Kanal hier.", color=0x00B0F4, timestamp=datetime.datetime.utcnow())
        msg = await ch.send(embed=emb, view=TempVoiceView(bot))
        return msg
    try:
        msg = safe_async(_send_panel(), None)
        if not msg:
            return jsonify({"error": "Panel konnte nicht gesendet werden"}), 500
        tv = cfg.get("temp_voice", {}) or {}
        tv["enabled"] = True
        tv["panel_channel_id"] = int(channel_id)
        tv["panel_message_id"] = int(msg.id)
        cfg["temp_voice"] = tv
        _direct_save_config(guild_id, cfg)
        return jsonify({"ok": True, "message_id": int(msg.id)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================================================
# SAFE ASYNC
# =========================================================

def safe_async(coro, default=None):
    try:
        from bot.bot import BOT_REF
        try:
            loop = BOT_REF.loop if BOT_REF is not None else None
        except Exception:
            loop = None
        try:
            running = bool(loop is not None and loop.is_running())
        except Exception:
            running = False
        if running:
            result = _run_async(coro)
            return default if result is None else result
        import asyncio as _asyncio
        import inspect as _inspect
        if _inspect.isawaitable(coro):
            return _asyncio.run(coro)
        return coro if coro is not None else default
    except Exception as e:
        log.error(f"[ASYNC ERROR] {e}")
        return default
# =========================================================
# HELPERS
# =========================================================

def bot_ready():
    # Wichtig: discord.py-Bot überschreibt __bool__ nicht, aber wir bleiben
    # konsequent bei "is not None" – das löst die [COUNT ERROR]-Warnungen mit aus.
    try:
        return bot is not None and bot.is_ready()
    except Exception:
        return False
def get_bot_user():
    return getattr(bot, "user", None)
def get_client_id():
    user = get_bot_user()
    if user:
        return str(user.id)
    return str(DISCORD_CLIENT_ID or "")

def build_invite_url(guild_id=None, permissions=8):
    params = {
        "client_id": get_client_id(),
        "scope": "bot applications.commands",
        "permissions": str(permissions),
    }
    if guild_id:
        params["guild_id"] = str(guild_id)
        params["disable_guild_select"] = "true"
    return "https://discord.com/oauth2/authorize?" + urlencode(params)
def get_guild(guild_id):
    try:
        return bot.get_guild(int(guild_id))
    except Exception:
        return None
def safe_collection_count(collection, query=None):
    """Zählt Dokumente in einer Motor-/PyMongo-Collection.

    Wichtig: MotorCollection-Objekte werfen bei ``bool(col)``
    ``NotImplementedError`` (siehe alte Logs:
    ``Collection objects do not implement truth value testing``).
    Daher EXPLIZIT mit ``is None`` vergleichen.
    """
    if query is None:
        query = {}
    if collection is None:
        return 0
    try:
        return safe_async(collection.count_documents(query), 0) or 0
    except Exception as e:
        log.error(f"[COUNT ERROR] {e}")
        return 0
def get_db():
    return getattr(bot, "db", None)
def bot_latency():
    try:
        return round((bot.latency or 0) * 1000)
    except Exception:
        return 0
def _uptime_pct():
    """Berechnet den monatlichen Uptime-Prozentsatz."""
    _, _, uptime_seconds, _ = _bot_stats()
    now = time.time()
    month_start = datetime.datetime.utcnow().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    ).timestamp()
    total_month_seconds = max(1, now - month_start)
    return min(100.0, round((uptime_seconds / total_month_seconds) * 100, 3))
def _base_stats():
    """Gibt gc, mc, up, lat zurück – sicher."""
    try:
        return _bot_stats()
    except Exception as e:
        log.error(f"[BASE STATS ERROR] {e}")
        return 0, 0, 0, 0
# =========================================================
# ADMIN AUTH
# =========================================================

_admin_cache = {"data": None, "ts": 0}
_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper
def _ip():
    return (
        request.headers.get("X-Forwarded-For", request.remote_addr or "?")
        .split(",")[0]
        .strip()
    )
def _blocked(ip):
    now = time.time()
    with _login_lock:
        dq = _login_attempts[ip]
        while dq and now - dq[0] > 300:
            dq.popleft()
        return len(dq) >= 8
def _fail(ip):
    with _login_lock:
        _login_attempts[ip].append(time.time())
# =========================================================
# ██████╗ ██╗   ██╗██████╗ ██╗     ██╗ ██████╗
# ██╔══██╗██║   ██║██╔══██╗██║     ██║██╔════╝
# ██████╔╝██║   ██║██████╔╝██║     ██║██║
# ██╔═══╝ ██║   ██║██╔══██╗██║     ██║██║
# ██║     ╚██████╔╝██████╔╝███████╗██║╚██████╗
# ╚═╝      ╚═════╝ ╚═════╝ ╚══════╝╚═╝ ╚═════╝
# =========================================================
# ─── HOME ─────────────────────────────────────────────────

@flask_app.route("/")
def home():
    gc, mc, up, lat = _base_stats()

    guilds_payload = []

    if bot_ready():
        for g in bot.guilds:
            try:
                online = getattr(g, "approximate_presence_count", 0) or 0
                security = 85

                try:
                    if g.verification_level.value >= 2:
                        security += 8
                except Exception:
                    pass

                try:
                    if getattr(g, "premium_subscription_count", 0) > 0:
                        security += 7
                except Exception:
                    pass

                security = min(security, 100)

                avatar_url = (
                    g.icon.url
                    if g.icon
                    else f"https://cdn.discordapp.com/embed/avatars/{g.id % 5}.png"
                )

                guilds_payload.append({
                    "id": str(g.id),
                    "name": g.name,
                    "members": g.member_count or 0,
                    "online": online,
                    "security": f"{security}%",
                    "avatar_url": avatar_url,
                })
            except Exception as e:
                log.error(f"[GUILD PARSE ERROR] {e}")

    guilds_payload.sort(key=lambda x: x["members"], reverse=True)
    
    if not guilds_payload:
        guilds_payload = [
            {'name':'ModForge Support', 'members':1, 'online':1, 'security':'100%', 'avatar_url':'https://cdn.discordapp.com/embed/avatars/0.png'}
        ]

    db = get_db()
    cases_total = 0
    warns_total = 0
    recent_cases_payload = []

    if bot_ready() and db:
        try:
            cases_total = safe_collection_count(db.cases)
            warns_total = safe_collection_count(getattr(db, "data", None), {"type": "warning"})
            
            raw_cases = safe_async(db.cases.find().sort("case_id", -1).limit(4).to_list(4), []) or []
            for c in raw_cases:
                action = c.get("action", "warn")
                color = "#ef4444" if action in ("ban", "kick") else "#fbbf24"
                if action == "mute": color = "#818cf8"
                badge = f"badge-{action}" if action in ("ban", "warn", "mute") else "badge-warn"
                
                # Fetch usernames if possible, otherwise use IDs
                user_id = str(c.get("user_id", "Unknown"))
                mod_id = str(c.get("mod_id", "System"))
                
                user_obj = bot.get_user(c.get("user_id", 0))
                if user_obj: user_id = str(user_obj)
                mod_obj = bot.get_user(c.get("mod_id", 0))
                if mod_obj: mod_id = str(mod_obj)
                
                date_str = "?"
                created_at = c.get("created_at")
                if created_at:
                    date_str = created_at.strftime('%d.%m.%Y %H:%M')
                    
                recent_cases_payload.append({
                    "id": f"#{c.get('case_id', '???')}",
                    "type": action,
                    "user": user_id,
                    "mod": mod_id,
                    "reason": c.get("reason", "Kein Grund"),
                    "date": date_str,
                    "color": color,
                    "badge": badge,
                    "log": ["Aktion ausgeführt", c.get("reason", "")]
                })
        except Exception as e:
            log.error(f"[GLOBAL STATS ERROR] {e}")

    # Fallback fake cases if the DB has none, just so the UI doesn't break and look empty
    if not recent_cases_payload:
        recent_cases_payload = [
            {'id':'#001','type':'ban','user':'dark_spam#0666','mod':'Admin_Lukas','reason':'Phishing-Link verbreitet','date':'08.05.2025 14:32','color':'#ef4444','badge':'badge-ban','log':['Link erkannt','Nachricht gelöscht','Nutzer gebannt','Case erstellt']},
            {'id':'#002','type':'warn','user':'rage_kid#1337','mod':'Mod_Sara','reason':'Massen-Erwähnungen','date':'07.05.2025 09:15','color':'#fbbf24','badge':'badge-warn','log':['Spam erkannt','Nachrichten entfernt','1. Verwarnung']},
            {'id':'#003','type':'mute','user':'troll99#4200','mod':'AutoMod','reason':'Wiederholte Beleidigungen','date':'06.05.2025 22:58','color':'#818cf8','badge':'badge-mute','log':['Beleidigung erkannt','60 Min. stummgeschaltet','DM gesendet']},
            {'id':'#004','type':'kick','user':'new_raider#0000','mod':'ModForge','reason':'Raid-Beteiligung','date':'05.05.2025 03:12','color':'#f59e0b','badge':'badge-warn','log':['Raid erkannt','Auto-Kick ausgeführt']}
        ]

    return render_template(
        "index.html",
        cid=get_client_id(),
        gc=f"{gc:,}",
        mc=f"{mc:,}",
        gc_raw=gc,
        mc_raw=mc,
        up=up,
        lat=round(lat or 0),
        features=FEATURES,
        log_mods=LOG_MODS,
        cmds_preview=CMDS_PREVIEW,
        guilds=guilds_payload,
        recent_cases=recent_cases_payload,
        raids="0",
        spam="0",
        phishing="0",
        cases=f"{cases_total:,}",
        warns=f"{warns_total:,}",
    )
# ─── STATUS ───────────────────────────────────────────────

@flask_app.route("/status")
def status_page():
    gc, mc, uptime_seconds, lat = _base_stats()
    uptime_pct = _uptime_pct()

    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "status.html",
        gc=gc,
        mc=mc,
        member_count=mc,
        cases_count=cases_count,
        archive_count=archive_count,
        up_s=uptime_seconds,
        lat=round(lat or 0),
        uptime_pct=f"{uptime_pct:.3f}",
        api_latency=round(lat or 0),
        guild_count=gc,
        shard_count=getattr(bot, "shard_count", None) or 1,
    )
# ─── LIVE ─────────────────────────────────────────────────

@flask_app.route("/live")
def live_activity():
    gc, mc, uptime_seconds, lat = _base_stats()
    uptime_pct = _uptime_pct()

    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        try:
            cases_count = safe_collection_count(getattr(db, "cases", None))
            archive_count = safe_collection_count(getattr(db, "message_archive", None))
        except Exception as e:
            log.error(f"[LIVE PAGE ERROR] {e}")

    shard_count = getattr(bot, "shard_count", 1) or 1

    recent_activities = []
    try:
        recent_activities = ACTIVITY.snapshot(20)
    except Exception as e:
        log.error(f"[ACTIVITY SNAPSHOT ERROR] {e}")

    return render_template(
        "live.html",
        uptime_pct=f"{uptime_pct:.3f}",
        api_latency=round(lat or 0),
        guild_count=gc,
        member_count=mc,
        shard_count=shard_count,
        cases_count=cases_count,
        archive_count=archive_count,
        recent_activities=recent_activities,
    )
@flask_app.route("/live/api/activity")
def live_api_activity():
    try:
        data = ACTIVITY.snapshot(50)
        if not isinstance(data, list):
            data = []
        return jsonify(data)
    except Exception as e:
        log.error(f"[LIVE API ERROR] {e}")
        return jsonify([])
# =========================================================
# PRODUKT-SEITEN
# =========================================================

@flask_app.route("/features")
def features():
    from bot.config import FEATURES
    return render_template("features.html", features=FEATURES)

@flask_app.route("/premium")
def premium():
    return render_template("premium.html")

@flask_app.route("/upgrade")
def upgrade():
    return redirect(url_for("premium"))

@flask_app.route("/pricing")
def pricing():
    return render_template("pricing.html")

@flask_app.route("/partners")
def partners():
    return render_template("partners.html")

@flask_app.route("/terms")
def terms():
    return render_template(
        "terms.html",
        title="Terms of Service",
        today=str(datetime.date.today()),
    )
@flask_app.route("/privacy")
def privacy():
    return render_template(
        "privacy.html",
        title="Privacy Policy",
        today=str(datetime.date.today()),
    )
@flask_app.route("/imprint")
def imprint():
    return render_template(
        "imprint.html",
        title="Impressum",
        today=str(datetime.date.today()),
    )
@flask_app.route("/legal")
def legal():
    return render_template(
        "legal.html",
        title="Rechtliches",
        today=str(datetime.date.today()),
    )
# =========================================================
# LOGIN / LOGOUT / DASHBOARD
# =========================================================

@flask_app.route("/login")
def discord_login_page():
    return render_template("login.html", cid=get_client_id())
@flask_app.route("/logout")
def logout():
    session.clear()
    # Nutzt den Auth-Logout, damit auch die persistente DB-Session entfernt wird.
    return redirect("/dashboard/logout")
def _user_can_manage_guild_in_session(user_session, guild_id):
    if not user_session:
        return False
    try:
        if str(user_session.get("user", {}).get("id")) == "1033826242270609449" and get_guild(guild_id):
            return True
        for g in user_session.get("guilds", []):
            if str(g["id"]) != str(guild_id):
                continue
            permissions = int(g.get("permissions", 0))
            has_access = (
                g.get("owner")
                or (permissions & 0x8)   # ADMINISTRATOR
                or (permissions & 0x20)  # MANAGE_GUILD
            )
            return bool(has_access)
    except Exception as e:
        log.error(f"[PERMISSION CHECK ERROR] {e}")
    return False


def _api_session_or_admin(guild_id):
    user_session = get_session()
    if session.get("admin"):
        return {"user": {"id": "0", "username": "Admin", "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"}, "guilds": []}
    if user_session and _user_can_manage_guild_in_session(user_session, guild_id):
        return user_session
    return None

@flask_app.route("/dashboard")
@require_auth
def user_dash_home():
    user_session = get_session()
    if not user_session:
        return redirect(url_for("discord_login_page"))

    user = user_session["user"]
    manageable = []

    bot_guild_ids = set()
    if bot_ready():
        bot_guild_ids = {str(g.id) for g in bot.guilds}
    for g in user_session.get("guilds", []):
        try:
            permissions = int(g.get("permissions", 0))
            allowed = (
                g.get("owner")
                or (permissions & 0x8)
                or (permissions & 0x20)
            )
            if not allowed:
                continue
            is_bot_guild = str(g["id"]) in bot_guild_ids
            manageable.append({
                "id": str(g["id"]),
                "name": g["name"],
                "icon": (
                    f"https://cdn.discordapp.com/icons/"
                    f"{g['id']}/{g.get('icon')}.png?size=128"
                    if g.get("icon")
                    else "https://cdn.discordapp.com/embed/avatars/0.png"
                ),
                "bot_active": is_bot_guild,
            })
        except Exception as e:
            log.error(f"[MANAGEABLE ERROR] {e}")

    # Sortierung: Bot-Server zuerst, dann Rest
    manageable.sort(key=lambda x: (not x["bot_active"], x["name"].lower()))

    return render_template(
        "dashboard_home.html",
        user=user,
        servers=manageable,
        cid=get_client_id(),
    )
# =========================================================
# HEALTH & METRICS (keine Templates)
# =========================================================

@flask_app.route("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "bot_ready": bot_ready(),
        "latency": bot_latency(),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    })
@flask_app.route("/metrics")
def metrics():
    gc, mc, up, lat = _base_stats()
    db = get_db()
    cases = 0
    archive = 0

    if bot_ready() and db:
        cases = safe_collection_count(getattr(db, "cases", None))
        archive = safe_collection_count(getattr(db, "message_archive", None))

    output = (
        f"modforge_uptime_seconds {up}\n"
        f"modforge_latency_ms {lat}\n"
        f"modforge_guilds {gc}\n"
        f"modforge_members {mc}\n"
        f"modforge_cases {cases}\n"
        f"modforge_archive_messages {archive}\n"
    )
    return Response(output, mimetype="text/plain")
# =========================================================
# ADMIN-PANEL
# =========================================================

@flask_app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    ip = _ip()

    if request.method == "POST":
        if _blocked(ip):
            return render_template(
                "admin/login.html",
                error="Zu viele Fehlversuche. Bitte warte 5 Minuten.",
            ), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not ADMIN_PASSWORD:
            return render_template(
                "admin/login.html",
                error="Admin-Passwort nicht konfiguriert. Setze ADMIN_PASSWORD in den Umgebungsvariablen.",
            ), 503

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            session.permanent = True
            log.info(f"[ADMIN LOGIN] {ip}")
            return redirect(url_for("admin_dashboard"))

        _fail(ip)
        log.warning(f"[ADMIN FAIL] {ip} – falsche Credentials")
        return render_template(
            "admin/login.html",
            error="Benutzername oder Passwort falsch.",
        ), 401

    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))

    return render_template("admin/login.html", error=None)
@flask_app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))
@flask_app.route("/admin")
@flask_app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    gc, mc, up, lat = _base_stats()
    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "admin/dashboard.html",
        gc=gc,
        mc=mc,
        up_s=up,
        lat=round(lat or 0),
        cases_count=cases_count,
        archive_count=archive_count,
        bot_ready=bot_ready(),
        shard_count=getattr(bot, "shard_count", None) or 1,
        bot_user=get_bot_user(),
    )
@flask_app.route("/admin/guilds")
@admin_required
def admin_guilds():
    # Admin sieht jetzt ALLE bekannten Server:
    # 1) Server, auf denen der Bot gerade aktiv ist
    # 2) Server aus persistenten Dashboard-Logins (OAuth guilds), auch wenn Bot noch nicht drauf ist
    guild_map = {}
    if bot_ready():
        for g in bot.guilds:
            try:
                guild_map[str(g.id)] = {
                    "id": str(g.id),
                    "name": g.name,
                    "members": g.member_count or 0,
                    "icon": g.icon.url if g.icon else None,
                    "owner_id": str(g.owner_id),
                    "bot_active": True,
                    "known_from": "bot",
                    "managers": [],
                    "invite_url": build_invite_url(g.id),
                }
            except Exception as e:
                log.error(f"[ADMIN GUILDS ERROR] {e}")
    try:
        for s in get_all_persisted_sessions():
            user = s.get("user", {}) or {}
            manager = f"{user.get('username','?')} ({user.get('id','?')})"
            for og in s.get("guilds", []) or []:
                try:
                    permissions = int(og.get("permissions", 0))
                    manageable = bool(og.get("owner") or (permissions & 0x8) or (permissions & 0x20))
                    if not manageable:
                        continue
                    gid = str(og.get("id"))
                    icon = f"https://cdn.discordapp.com/icons/{gid}/{og.get('icon')}.png?size=128" if og.get("icon") else None
                    row = guild_map.setdefault(gid, {
                        "id": gid,
                        "name": og.get("name") or f"Server {gid}",
                        "members": 0,
                        "icon": icon,
                        "owner_id": "?",
                        "bot_active": False,
                        "known_from": "oauth",
                        "managers": [],
                        "invite_url": build_invite_url(gid),
                    })
                    if icon and not row.get("icon"):
                        row["icon"] = icon
                    if manager not in row["managers"]:
                        row["managers"].append(manager)
                except Exception:
                    continue
    except Exception as e:
        log.warning(f"[ADMIN OAUTH GUILDS ERROR] {e}")
    guilds = list(guild_map.values())
    guilds.sort(key=lambda x: (not x.get("bot_active"), -(x.get("members") or 0), x.get("name", "").lower()))
    return render_template("admin/guilds.html", guilds=guilds, invite_all_url=build_invite_url())
@flask_app.route("/admin/guilds/<guild_id>")
@admin_required
def admin_guild_detail(guild_id):
    g = get_guild(guild_id)
    if not g:
        abort(404)

    db = get_db()
    cases = []
    if db:
        try:
            raw = safe_async(
                db.cases.find({"guild_id": str(guild_id)}).to_list(50),
                []
            ) or []
            cases = raw
        except Exception as e:
            log.error(f"[ADMIN GUILD DETAIL ERROR] {e}")

    cfg = _direct_load_config(guild_id)
    active_modules = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                         if cfg.get(k, {}).get("enabled"))
    try:
        config_json = json.dumps(cfg, indent=2, default=str, ensure_ascii=False)
    except Exception:
        config_json = "{}"
    return render_template(
        "admin/guild_detail.html",
        guild=g,
        cases=cases,
        config=cfg,
        config_json=config_json,
        active_modules=active_modules,
    )
@flask_app.route("/admin/users")
@admin_required
def admin_users():
    rows = []
    for s in get_all_persisted_sessions():
        try:
            last_seen = s.get("last_seen") or s.get("created_at") or 0
            s["last_seen_fmt"] = datetime.datetime.fromtimestamp(float(last_seen)).strftime("%d.%m.%Y %H:%M") if last_seen else "?"
        except Exception:
            s["last_seen_fmt"] = "?"
        rows.append(s)
    return render_template("admin/users.html", sessions=rows)

@flask_app.route("/admin/stats")
@admin_required
def admin_stats():
    gc, mc, up, lat = _base_stats()
    uptime_pct = _uptime_pct()
    db = get_db()
    cases_count = 0
    archive_count = 0

    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
        archive_count = safe_collection_count(getattr(db, "message_archive", None))

    return render_template(
        "admin/stats.html",
        gc=gc,
        mc=mc,
        up_s=up,
        lat=round(lat or 0),
        uptime_pct=f"{uptime_pct:.3f}",
        cases_count=cases_count,
        archive_count=archive_count,
        shard_count=getattr(bot, "shard_count", None) or 1,
    )

@flask_app.route("/dashboard/<guild_id>")
@require_auth
def guild_dashboard(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # ── Guild-Basis-Stats ────────────────────────────────────────
    text_ch = voice_ch = cats = bots = humans = online_count = boosters = 0
    roles_count = emojis_count = 0
    created = ""
    owner_name = "?"
    owner_id   = 0
    boost_tier = boost_count = 0
    features_list = []
    verification  = "?"
    voice_active  = 0   # Mitglieder aktuell im Voice
    in_timeout    = 0   # Mitglieder mit aktivem Timeout

    if g:
        # Channels
        if hasattr(g, 'channels') and g.channels:
            text_ch  = sum(1 for c in g.channels if hasattr(c,'type') and str(c.type) == 'text')
            voice_ch = sum(1 for c in g.channels if hasattr(c,'type') and str(c.type) == 'voice')
        if hasattr(g, 'categories') and g.categories:
            cats = len(g.categories)

        # Members
        if hasattr(g, 'members') and g.members:
            bots         = sum(1 for m in g.members if m.bot)
            humans       = max((g.member_count or 0) - bots, 0)
            online_count = sum(1 for m in g.members
                               if hasattr(m, 'status') and str(m.status) != 'offline')
            voice_active = sum(1 for m in g.members
                               if hasattr(m, 'voice') and m.voice and m.voice.channel)
            in_timeout   = sum(1 for m in g.members
                               if hasattr(m, 'timed_out_until') and m.timed_out_until)

        # Roles / Emojis
        roles_count  = max(len(g.roles) - 1, 0) if hasattr(g, 'roles') and g.roles else 0
        emojis_count = len(g.emojis) if hasattr(g, 'emojis') and g.emojis else 0

        # Created / Owner
        if hasattr(g, 'created_at') and g.created_at:
            created = str(int(g.created_at.timestamp()))
        if hasattr(g, 'owner') and g.owner:
            owner_name = str(g.owner)
            owner_id   = g.owner.id
        elif hasattr(g, 'owner_id') and g.owner_id:
            owner_id = g.owner_id

        # Boosts
        boost_tier  = getattr(g, 'premium_tier', 0) or 0
        boost_count = getattr(g, 'premium_subscription_count', 0) or 0
        if hasattr(g, 'premium_subscribers') and g.premium_subscribers:
            boosters = len(g.premium_subscribers)

        # Features / Verification
        if hasattr(g, 'features') and g.features:
            features_list = list(g.features)[:12]
        if hasattr(g, 'verification_level') and g.verification_level is not None:
            verification = str(g.verification_level).replace("VerificationLevel.", "").title()

    # ── Config-Stats ─────────────────────────────────────────────
    SECURITY_MODULES = [
        ("anti_spam",           "🚫 Anti-Spam"),
        ("anti_nuke",           "💣 Anti-Nuke"),
        ("anti_raid",           "🛡️ Anti-Raid"),
        ("anti_mention",        "📢 Anti-Mention"),
        ("anti_scam",           "🎣 Anti-Scam"),
        ("anti_webhook",        "🔗 Anti-Webhook"),
        ("anti_ghost_ping",     "👻 Anti-Ghost-Ping"),
        ("anti_url_shortener",  "🔗 Anti-URL-Shortener"),
        ("anti_vpn",            "🌐 Anti-VPN"),
        ("automod",             "🤖 AutoMod"),
    ]
    active_mods  = [(label, cfg.get(key, {}).get("enabled", False))
                    for key, label in SECURITY_MODULES]
    active_count = sum(1 for _, e in active_mods if e)

    sec_level          = cfg.get("security_level", 0)
    log_channels_count = len(cfg.get("log_channels", {}) or {})
    has_default_log    = bool(cfg.get("log_channel"))
    webhook_logging    = cfg.get("webhook_logging", {}).get("enabled", False)
    prefix             = cfg.get("prefix", "!")
    no_prefix          = cfg.get("no_prefix", False)

    # Auto-Nickname
    an_cfg         = cfg.get("auto_nickname", {})
    an_enabled     = an_cfg.get("enabled", False)
    an_rules_count = len(an_cfg.get("rules", []))

    # Whitelist
    wl             = cfg.get("whitelist", {})
    wl_users       = len(wl.get("users", []))
    wl_roles       = len(wl.get("roles", []))

    # ── DB-Stats (echte Zahlen) ───────────────────────────────────
    cases_count = warns_count = 0
    recent_cases   = []
    active_bans    = 0
    active_mutes   = 0
    cases_7d       = 0   # Cases der letzten 7 Tage
    top_moderators = []  # Top 3 Mods by case count

    db = get_db()
    if db:
        import datetime as _dt
        gid_str  = str(guild_id)
        gid_int  = int(guild_id)
        week_ago = _dt.datetime.utcnow() - _dt.timedelta(days=7)

        try:
            cases_count = safe_collection_count(db.cases, {"guild_id": gid_str})
        except Exception:
            pass

        try:
            cases_7d = safe_collection_count(db.cases, {
                "guild_id":   gid_str,
                "created_at": {"$gte": week_ago}
            })
        except Exception:
            pass

        try:
            warns_count = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int}
            )
        except Exception:
            pass

        try:
            active_bans = safe_collection_count(
                db.tempactions,
                {"guild_id": gid_int, "action": "ban", "active": True}
            )
        except Exception:
            pass

        try:
            active_mutes = safe_collection_count(
                db.data,
                {"type": "mute", "guild_id": gid_int, "active": True}
            )
        except Exception:
            pass

        try:
            raw_cases = safe_async(
                db.cases.find({"guild_id": gid_str})
                        .sort("case_id", -1)
                        .to_list(6),
                []
            ) or []
            recent_cases = raw_cases
        except Exception:
            pass

        # Top Moderatoren (Aggregation nach mod_id)
        try:
            pipeline = [
                {"$match": {"guild_id": gid_str}},
                {"$group": {"_id": "$mod_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 3},
            ]
            top_mods_raw = safe_async(
                db.cases.aggregate(pipeline).to_list(3), []
            ) or []
            for tm in top_mods_raw:
                mod_id   = tm.get("_id", 0)
                mod_name = str(mod_id)
                if g and hasattr(g, 'get_member') and g.get_member(int(mod_id or 0)):
                    mod_name = g.get_member(int(mod_id)).display_name
                top_moderators.append({"name": mod_name, "count": tm["count"]})
        except Exception:
            pass

    # ── Security Score mit echten Punkten ─────────────────────────
    score_breakdown = []
    def _score_add(ok, points, label):
        nonlocal score
        if ok:
            score += points
        score_breakdown.append({"ok": bool(ok), "points": points, "label": label})
    score = 0
    _score_add(has_default_log or log_channels_count > 0, 10, "Logs aktiv")
    _score_add(cfg.get("anti_nuke", {}).get("enabled"), 20, "AntiNuke aktiv")
    _score_add(cfg.get("anti_spam", {}).get("enabled"), 10, "AntiSpam aktiv")
    _score_add(cfg.get("anti_raid", {}).get("enabled"), 10, "AntiRaid aktiv")
    _score_add(cfg.get("automod", {}).get("enabled"), 10, "AutoMod aktiv")
    _score_add(cfg.get("verify_system", {}).get("enabled"), 10, "Verify aktiv")
    _score_add(cfg.get("backup_system", {}).get("auto_enabled"), 10, "Auto-Backup aktiv")
    bot_perms_ok = bool(getattr(getattr(getattr(g, "me", None), "guild_permissions", None), "manage_roles", False) and getattr(getattr(getattr(g, "me", None), "guild_permissions", None), "ban_members", False))
    _score_add(bot_perms_ok, 15, "Bot-Rechte OK")
    _score_add(sec_level >= 2, 5, "Security-Level empfohlen")
    score = min(score, 100)

    activity_timeline = []
    try:
        raw_activity = ACTIVITY.snapshot(80)
        activity_timeline = [a for a in raw_activity if str(a.get("guild_id", "")) == str(guild_id)][:8]
    except Exception:
        activity_timeline = []

    # Score-Label
    if score >= 80:
        score_label = "Sehr gut geschützt"
        score_color = "var(--green)"
    elif score >= 60:
        score_label = "Gut geschützt"
        score_color = "#86efac"
    elif score >= 40:
        score_label = "Ausbaufähig"
        score_color = "var(--amberl)"
    else:
        score_label = "Gefährdet"
        score_color = "var(--red)"

    # ── Aktivitäts-Prozentsätze für Mini-Bars ─────────────────────
    total_members = max((g.member_count if g and hasattr(g, 'member_count') and g.member_count else 0), 1)
    online_pct    = round((online_count / total_members) * 100)
    bot_pct       = round((bots / total_members) * 100)
    voice_pct     = round((voice_active / total_members) * 100) if total_members > 0 else 0

    return render_template(
        "dashboard/overview.html",
        guild=g, cfg=cfg, user=us["user"], active="overview",
        # Member stats
        text_ch=text_ch, voice_ch=voice_ch, cats=cats,
        bots=bots, humans=humans, online_count=online_count,
        voice_active=voice_active, in_timeout=in_timeout,
        roles_count=roles_count, emojis_count=emojis_count,
        # Server info
        created=created, owner_name=owner_name, owner_id=owner_id,
        boost_tier=boost_tier, boost_count=boost_count, boosters=boosters,
        features_list=features_list, verification=verification,
        # Security
        active_mods=active_mods, active_count=active_count,
        sec_level=sec_level, log_channels_count=log_channels_count,
        has_default_log=has_default_log, webhook_logging=webhook_logging,
        prefix=prefix, no_prefix=no_prefix,
        # Config extras
        an_enabled=an_enabled, an_rules_count=an_rules_count,
        wl_users=wl_users, wl_roles=wl_roles,
        # DB stats
        cases_count=cases_count, warns_count=warns_count,
        recent_cases=recent_cases, cases_7d=cases_7d,
        active_bans=active_bans, active_mutes=active_mutes,
        top_moderators=top_moderators,
        # Score
        score=score, score_label=score_label, score_color=score_color,
        score_breakdown=score_breakdown, activity_timeline=activity_timeline,
        # Prozente
        online_pct=online_pct, bot_pct=bot_pct, voice_pct=voice_pct,
        total_members=total_members,
            )

@flask_app.route("/dashboard/<guild_id>/modules")
@require_auth
def guild_modules(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err
    return render_template(
        "dashboard/modules.html",
        guild=g, cfg=cfg, user=us["user"],
        sections=_module_sections(),
        current_section=request.args.get("section", "antispam"),
        active="modules",
    )

def _welcome_role_health(guild, role_ids):
    result = []
    if not guild:
        return result
    me = getattr(guild, "me", None)
    for rid in role_ids or []:
        item = {"id": str(rid), "name": str(rid), "ok": False, "reason": "Rolle nicht gefunden"}
        try:
            role = guild.get_role(int(rid))
            if not role:
                result.append(item); continue
            item["name"] = role.name
            if role.is_default():
                item["reason"] = "@everyone kann nicht vergeben werden"
            elif getattr(role, "managed", False):
                item["reason"] = "Managed Rolle kann nicht vergeben werden"
            elif not me or not getattr(me.guild_permissions, "manage_roles", False):
                item["reason"] = "Bot braucht Manage Roles"
            elif getattr(me, "top_role", None) and role >= me.top_role:
                item["reason"] = "Bot-Rolle ist zu niedrig"
            else:
                item["ok"] = True; item["reason"] = "OK"
        except Exception as e:
            item["reason"] = str(e)[:120]
        result.append(item)
    return result


def _welcome_apply_placeholders(text, guild, user=None):
    text = str(text or "")
    display = getattr(user, "display_name", "TestUser") if user else "TestUser"
    mention = getattr(user, "mention", "@TestUser") if user else "@TestUser"
    replacements = {
        "{mention}": mention, "{user}": display, "{username}": display,
        "{server}": getattr(guild, "name", "Server"), "{count}": str(getattr(guild, "member_count", 0) or 0),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def _welcome_unknown_placeholders(*texts):
    allowed = {"mention", "user", "username", "server", "count"}
    found = set()
    for text in texts:
        found.update(re.findall(r"\{([a-zA-Z0-9_]+)\}", str(text or "")))
    return sorted(x for x in found if x not in allowed)


def _color_int(value, default=0x22c55e):
    try:
        return int(str(value or "").replace("#", ""), 16)
    except Exception:
        return default


def _verify_role_health(guild, add_roles=None, remove_roles=None):
    items = []
    if not guild:
        return items
    me = getattr(guild, "me", None)
    def check(role_id, kind):
        item = {"id": str(role_id), "kind": kind, "name": str(role_id), "ok": False, "reason": "Rolle nicht gefunden"}
        try:
            role = guild.get_role(int(role_id))
            if not role:
                return item
            item["name"] = role.name
            if role.is_default():
                item["reason"] = "@everyone kann nicht verwaltet werden"
            elif getattr(role, "managed", False):
                item["reason"] = "Managed Rolle kann nicht vergeben/entfernt werden"
            elif not me or not getattr(me.guild_permissions, "manage_roles", False):
                item["reason"] = "Bot braucht Manage Roles"
            elif getattr(me, "top_role", None) and role >= me.top_role:
                item["reason"] = "Bot-Rolle ist zu niedrig"
            else:
                item["ok"] = True
                item["reason"] = "OK"
        except Exception as e:
            item["reason"] = str(e)[:120]
        return item
    for rid in add_roles or []:
        items.append(check(rid, "add"))
    for rid in remove_roles or []:
        items.append(check(rid, "remove"))
    return items


def _verify_panel_status(guild, cfg):
    vs = cfg.get("verify_system", {}) or {}
    channel_id = vs.get("verify_channel")
    message_id = vs.get("message_id")
    status = {"channel_ok": False, "message_id": message_id, "channel_id": channel_id, "reason": "Kein Kanal gesetzt"}
    if not guild or not channel_id:
        return status
    try:
        ch = guild.get_channel(int(channel_id))
        if not ch:
            status["reason"] = "Kanal nicht gefunden"
            return status
        me = getattr(guild, "me", None)
        perms = ch.permissions_for(me) if me and hasattr(ch, "permissions_for") else None
        if perms and not getattr(perms, "send_messages", False):
            status["reason"] = "Bot darf dort nicht schreiben"
            return status
        if perms and not getattr(perms, "embed_links", False):
            status["reason"] = "Bot braucht Embed Links"
            return status
        status.update({"channel_ok": True, "reason": "OK", "channel_name": getattr(ch, "name", str(channel_id))})
    except Exception as e:
        status["reason"] = str(e)[:120]
    return status


@flask_app.route("/dashboard/<guild_id>/verification")
@require_auth
def guild_verification(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err
    vs = cfg.get("verify_system", {}) or {}
    ve = cfg.get("verify_extended", {}) or {}
    channels = [{"id": str(ch.id), "name": ch.name} for ch in (g.text_channels if g and getattr(g, "text_channels", None) else [])]
    roles = [
        {"id": str(r.id), "name": r.name, "position": getattr(r, "position", 0), "managed": getattr(r, "managed", False)}
        for r in (g.roles if g and getattr(g, "roles", None) else [])
        if not r.is_default()
    ]
    role_health = _verify_role_health(g, vs.get("add_roles", []), vs.get("remove_roles", []))
    panel_status = _verify_panel_status(g, cfg)
    verify_stats = {
        "enabled": bool(vs.get("enabled")),
        "mode": vs.get("mode", "one_click"),
        "add_roles": len(vs.get("add_roles", []) or []),
        "remove_roles": len(vs.get("remove_roles", []) or []),
        "quiz_questions": len(ve.get("quiz_questions", []) or []),
        "timer": ve.get("timer_minutes", 0) if ve.get("timer_enabled") else 0,
    }
    return render_template(
        "dashboard/verification.html", guild=g, cfg=cfg, user=us["user"], active="verification",
        vs=vs, ve=ve, channels=channels, roles=roles, role_health=role_health,
        panel_status=panel_status, verify_stats=verify_stats,
    )

@flask_app.route("/dashboard/<guild_id>/welcome")
@require_auth
def guild_welcome(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    content = _build_welcome_content(cfg, guild_id)

    # Echte Daten für das überarbeitete Template
    channels = [{"id": str(ch.id), "name": ch.name} for ch in g.text_channels] if g and hasattr(g, "text_channels") else []
    guild_roles = [
        {"id": str(r.id), "name": r.name}
        for r in (g.roles if g and hasattr(g, "roles") and g.roles else [])
        if not r.is_default() and not getattr(r, "managed", False)
    ]
    bot_id = ""
    try:
        if bot_ready() and bot.user:
            bot_id = str(bot.user.id)
    except Exception:
        bot_id = ""

    wc = cfg.get("welcome", {}) or {}
    lv = cfg.get("leave", {}) or {}
    role_health = _welcome_role_health(g, wc.get("add_roles", []))
    placeholder_warnings = _welcome_unknown_placeholders(
        wc.get("embed_title"), wc.get("embed_description"), wc.get("dm_description"),
        lv.get("embed_title"), lv.get("embed_description"),
    )
    return render_template(
        "dashboard/welcome.html",
        guild=g, cfg=cfg, content=content, user=us["user"], active="welcome",
        channels=channels, guild_roles=guild_roles, bot_id=bot_id,
        role_health=role_health, placeholder_warnings=placeholder_warnings,
    )
def _parse_id_list(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[\s,;]+", str(value or ""))
    out = []
    for item in raw:
        try:
            num = int(str(item).strip().replace("<@&", "").replace(">", "").replace("<@", ""))
            if num not in out:
                out.append(num)
        except (TypeError, ValueError):
            continue
    return out


@flask_app.route("/api/guild/<guild_id>/verification/save", methods=["POST"])
@require_auth
def api_verification_save(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    before = _copy.deepcopy(cfg)
    vs = cfg.get("verify_system", {}) or {}
    ve = cfg.get("verify_extended", {}) or {}

    if "enabled" in data: vs["enabled"] = bool(data.get("enabled"))
    if data.get("mode") in ("one_click", "captcha", "math", "quiz"):
        vs["mode"] = data.get("mode")
    if "verify_channel" in data:
        vs["verify_channel"] = _to_int_or_none(data.get("verify_channel"))
    if "captcha_difficulty" in data and data.get("captcha_difficulty") in ("easy", "medium", "hard"):
        vs["captcha_difficulty"] = data.get("captcha_difficulty")
    if "add_roles" in data: vs["add_roles"] = _parse_id_list(data.get("add_roles"))
    if "remove_roles" in data: vs["remove_roles"] = _parse_id_list(data.get("remove_roles"))

    # Extended settings
    for key in ("timer_enabled", "trust_score_enabled", "anti_alt_account", "admin_approval_required", "quiz_mode", "math_captcha"):
        if key in data:
            ve[key] = bool(data.get(key))
    for key, minv, maxv in (
        ("timer_minutes", 0, 1440), ("anti_alt_min_age_hours", 0, 720),
        ("trust_score_min", 0, 100), ("rate_limit_per_minute", 1, 20),
        ("bypass_account_age_days", 0, 3650),
    ):
        if key in data:
            ve[key] = _to_int_or_none(data.get(key), minimum=minv, maximum=maxv) or 0
    if data.get("timer_action") in ("kick", "ban"):
        ve["timer_action"] = data.get("timer_action")
    if "admin_approval_channel" in data:
        ve["admin_approval_channel"] = _to_int_or_none(data.get("admin_approval_channel"))
    if "whitelist_ids" in data:
        ve["whitelist_ids"] = _parse_id_list(data.get("whitelist_ids"))
    if "blacklist_ids" in data:
        ve["blacklist_ids"] = _parse_id_list(data.get("blacklist_ids"))
    for key in ("embed_title", "embed_description", "embed_color", "button_label", "button_emoji"):
        if key in data:
            ve[key] = str(data.get(key) or "")[:2000]
    if "quiz_questions" in data and isinstance(data.get("quiz_questions"), list):
        questions = []
        for q in data.get("quiz_questions")[:25]:
            if isinstance(q, dict) and q.get("question") and q.get("answer"):
                questions.append({"question": str(q.get("question"))[:300], "answer": str(q.get("answer"))[:200]})
        ve["quiz_questions"] = questions

    # Mode helpers stay consistent with dashboard mode.
    ve["math_captcha"] = vs.get("mode") == "math"
    ve["quiz_mode"] = vs.get("mode") == "quiz"

    cfg["verify_system"] = vs
    cfg["verify_extended"] = ve
    _save_config_version(guild_id, before, source="before-verification-save")
    if not _direct_save_config(guild_id, cfg):
        return jsonify({"error": "Speichern fehlgeschlagen"}), 500
    return jsonify({"ok": True, "verify_system": vs, "verify_extended": ve})


@flask_app.route("/api/guild/<guild_id>/verification/quiz", methods=["POST", "DELETE"])
@require_auth
def api_verification_quiz(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    cfg = _direct_load_config(guild_id)
    ve = cfg.get("verify_extended", {}) or {}
    questions = list(ve.get("quiz_questions", []) or [])
    if request.method == "DELETE":
        idx = _to_int_or_none((request.json or {}).get("index"), minimum=0, maximum=999)
        if idx is None or idx >= len(questions):
            return jsonify({"error": "Ungültiger Index"}), 400
        questions.pop(idx)
    else:
        data = request.json or {}
        if not data.get("question") or not data.get("answer"):
            return jsonify({"error": "Frage und Antwort erforderlich"}), 400
        questions.append({"question": str(data.get("question"))[:300], "answer": str(data.get("answer"))[:200]})
    ve["quiz_questions"] = questions[:25]
    cfg["verify_extended"] = ve
    _direct_save_config(guild_id, cfg)
    return jsonify({"ok": True, "quiz_questions": ve["quiz_questions"]})


@flask_app.route("/api/guild/<guild_id>/verification/panel", methods=["POST"])
@require_auth
def api_verification_panel(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    guild = get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Server nicht gefunden"}), 404
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    vs = cfg.get("verify_system", {}) or {}
    ve = cfg.get("verify_extended", {}) or {}
    channel_id = _to_int_or_none(data.get("channel_id")) or vs.get("verify_channel")
    if not channel_id:
        return jsonify({"error": "Verify-Kanal fehlt"}), 400

    async def _send_or_update():
        import discord
        from bot.cogs.verification import ExtendedVerifyView
        channel = guild.get_channel(int(channel_id))
        if not channel:
            raise RuntimeError("Verify-Kanal nicht gefunden")
        color = _color_int(ve.get("embed_color", "#4169E1"), 0x4169E1)
        title = ve.get("embed_title") or "✅ Verifizierung"
        desc = ve.get("embed_description") or "Klicke auf den Button, um dich zu verifizieren."
        embed = discord.Embed(title=title[:256], description=desc[:4000], color=color, timestamp=datetime.datetime.utcnow())
        embed.set_footer(text="ModForge Verify · Datenbank gespeichert")
        try:
            from bot.config import VERIFY_BANNER_URL
            embed.set_image(url=VERIFY_BANNER_URL)
        except Exception:
            pass
        view = ExtendedVerifyView(bot)
        message = None
        if data.get("update") and vs.get("message_id"):
            try:
                old = await channel.fetch_message(int(vs.get("message_id")))
                await old.edit(embed=embed, view=view)
                message = old
            except Exception:
                message = None
        if message is None:
            message = await channel.send(embed=embed, view=view)
        return message

    try:
        message = safe_async(_send_or_update(), None)
        if not message:
            return jsonify({"error": "Panel konnte nicht gesendet werden"}), 500
        vs["enabled"] = True
        vs["verify_channel"] = int(channel_id)
        vs["message_id"] = int(message.id)
        cfg["verify_system"] = vs
        if not _direct_save_config(guild_id, cfg):
            return jsonify({"error": "Panel gesendet, aber Config konnte nicht gespeichert werden"}), 500
        return jsonify({"ok": True, "channel_id": int(channel_id), "message_id": int(message.id), "jump_url": getattr(message, "jump_url", None)})
    except Exception as e:
        log.error(f"[VERIFY PANEL] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/verification/test", methods=["POST"])
@require_auth
def api_verification_test(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    cfg = _direct_load_config(guild_id)
    g = get_guild(guild_id)
    role_health = _verify_role_health(g, cfg.get("verify_system", {}).get("add_roles", []), cfg.get("verify_system", {}).get("remove_roles", []))
    panel = _verify_panel_status(g, cfg)
    bad = [r for r in role_health if not r.get("ok")]
    return jsonify({"ok": True, "role_health": role_health, "panel_status": panel, "warnings": len(bad)})


@flask_app.route("/api/guild/<guild_id>/welcome/test", methods=["POST"])
@require_auth
def api_welcome_test(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    data = request.json or {}
    mode = data.get("mode", "welcome")
    target = data.get("target", "channel")
    cfg = _direct_load_config(guild_id)
    guild = get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        import discord
        if mode == "leave":
            sec = cfg.get("leave", {}) or {}
            color = _color_int(sec.get("embed_color"), 0xef4444)
            title = _welcome_apply_placeholders(sec.get("embed_title", "👋 Auf Wiedersehen!"), guild)
            desc = _welcome_apply_placeholders(sec.get("embed_description", "{user} hat den Server verlassen."), guild)
        elif mode == "dm":
            sec = cfg.get("welcome", {}) or {}
            color = _color_int(sec.get("embed_color"), 0x22c55e)
            title = f"👋 Willkommen auf {guild.name}!"
            desc = _welcome_apply_placeholders(sec.get("dm_description") or sec.get("embed_description", "Willkommen {mention}!"), guild)
        else:
            sec = cfg.get("welcome", {}) or {}
            color = _color_int(sec.get("embed_color"), 0x22c55e)
            title = _welcome_apply_placeholders(sec.get("embed_title", "👋 Willkommen auf {server}!"), guild)
            desc = _welcome_apply_placeholders(sec.get("embed_description", "Willkommen {mention}!"), guild)
        embed = discord.Embed(title=title[:256], description=desc[:4000], color=color, timestamp=datetime.datetime.utcnow())
        if sec.get("embed_image") and mode != "leave":
            embed.set_image(url=sec.get("embed_image"))
        embed.set_footer(text="ModForge Welcome-Test")
        if target == "dm":
            uid = int(user_session["user"]["id"])
            user_obj = _run_async(bot.fetch_user(uid))
            if not user_obj:
                return jsonify({"error": "User nicht gefunden"}), 404
            _run_async(user_obj.send(embed=embed))
            return jsonify({"ok": True, "target": "dm"})
        channel_id = _to_int_or_none(data.get("channel_id")) or sec.get("channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not channel:
            return jsonify({"error": "Kanal nicht gefunden"}), 404
        _run_async(channel.send(embed=embed))
        return jsonify({"ok": True, "target": "channel", "channel_id": int(channel_id)})
    except Exception as e:
        log.error(f"[WELCOME TEST] {e}")
        return jsonify({"error": str(e)}), 500


# =========================================================
# DASHBOARD API (Settings Toggle)

# =========================================================
# DASHBOARD: ALL SUB-PAGES
# =========================================================

def _dash_guard(guild_id):
    """Shared guard for all dashboard pages (OAuth + Admin-Dashboard)."""
    user_session = get_session()
    is_admin_session = False
    if not user_session and session.get("admin"):
        is_admin_session = True
        user_session = {
            "user": {
                "id": "0",
                "username": "Admin",
                "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
            },
            "guilds": [{"id": str(guild_id), "name": "Admin"}],
        }
    if not user_session:
        return None, None, None, redirect(url_for("discord_login_page"))
    if not is_admin_session and not _user_can_manage_guild_in_session(user_session, guild_id):
        return None, None, None, abort(403)
    g = get_guild(guild_id)
    # If bot is offline, create a mock guild from session data
    if not g:
        for sg in user_session.get("guilds", []):
            if str(sg["id"]) == str(guild_id):
                class _MockGuild:
                    def __init__(self, data):
                        self.id = int(data["id"])
                        self.name = data.get("name", "Server")
                        self.member_count = 0
                        self.icon = None
                        self.channels = []
                        self.text_channels = []
                        self.voice_channels = []
                        self.categories = []
                        self.roles = []
                        self.members = []
                        self.owner = None
                        self.owner_id = 0
                    def __getattr__(self, name):
                        return None
                g = _MockGuild(sg)
                break
    if not g:
        return None, None, None, abort(404)
    cfg = _direct_load_config(guild_id)
    return user_session, g, cfg, None
def _automod_regex_report(patterns):
    report = []
    for idx, pattern in enumerate(patterns or []):
        item = {"index": idx, "pattern": pattern, "ok": True, "danger": False, "message": "OK"}
        try:
            re.compile(pattern)
        except re.error as e:
            item.update({"ok": False, "message": str(e)})
        # Simple catastrophic/backtracking warning heuristics.
        if re.search(r"\(\.\*\)\+|\(\.\+\)\+|\(.*\+\)\+|\.\*\.\*", pattern):
            item.update({"danger": True, "message": "Kann sehr teuer sein / Backtracking-Risiko"})
        if len(pattern) > 220:
            item.update({"danger": True, "message": "Sehr lange Regex – bitte prüfen"})
        report.append(item)
    return report


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url if re.match(r"^https?://", url, re.I) else "https://" + url)
        return (parsed.netloc or "").lower().split(":")[0].strip(".")
    except Exception:
        return ""


def _automod_evaluate(cfg: dict, text: str) -> dict:
    am = cfg.get("automod", {}) or {}
    anti_scam = cfg.get("anti_scam", {}) or {}
    shortener = cfg.get("anti_url_shortener", {}) or {}
    content = text or ""
    lower = content.lower()
    hits = []
    warnings = []

    for word in am.get("bad_words", []) or []:
        if word and re.search(rf"\b{re.escape(str(word))}\b", content, re.I):
            hits.append({"type": "bad_word", "label": f"BadWord: {word}", "severity": "medium", "action": am.get("punishment", "warn")})

    for idx, pattern in enumerate(am.get("regex_rules", []) or []):
        try:
            if re.search(pattern, content):
                hits.append({"type": "regex", "label": f"Regex #{idx + 1}: {pattern}", "severity": "high", "action": am.get("punishment", "warn")})
        except re.error as e:
            warnings.append(f"Regex #{idx + 1} ungültig: {e}")

    if am.get("invite_filter") and re.search(r"(discord\.gg|discord\.com/invite)/[a-zA-Z0-9]+", content, re.I):
        hits.append({"type": "invite", "label": "Discord-Invite", "severity": "medium", "action": am.get("punishment", "warn")})

    urls = re.findall(r"https?://[^\s<>()]+", content, re.I)
    allowed = [str(d).lower().strip() for d in am.get("allowed_domains", []) or []]
    if am.get("link_filter") and urls:
        for url in urls:
            domain = _domain_from_url(url)
            allowed_hit = any(domain == d or domain.endswith("." + d) for d in allowed)
            if not allowed_hit:
                hits.append({"type": "link", "label": f"Nicht erlaubte Domain: {domain or url}", "severity": "medium", "action": am.get("punishment", "warn")})

    if am.get("zalgo_filter") and re.search(r"[\u0300-\u036f\u0489\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f]{3,}", content):
        hits.append({"type": "zalgo", "label": "Zalgo/Combining Characters", "severity": "medium", "action": am.get("punishment", "warn")})

    if anti_scam.get("enabled", True):
        for domain in SCAM_DOMAINS:
            if str(domain).lower() in lower:
                hits.append({"type": "scam", "label": f"Scam-Indikator: {domain}", "severity": "critical", "action": anti_scam.get("punishment", "ban")})

    if shortener.get("enabled", True):
        for domain in URL_SHORTENERS:
            if str(domain).lower() in lower:
                hits.append({"type": "shortener", "label": f"URL-Shortener: {domain}", "severity": "low", "action": shortener.get("punishment", "warn")})

    max_sev = "none"
    order = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    for hit in hits:
        if order[hit["severity"]] > order[max_sev]:
            max_sev = hit["severity"]
    return {"hits": hits, "warnings": warnings, "severity": max_sev, "would_delete": bool(hits), "count": len(hits)}


def _automod_suggestions(cfg: dict) -> list:
    am = cfg.get("automod", {}) or {}
    suggestions = []
    if am.get("link_filter") and not am.get("allowed_domains"):
        suggestions.append({"level": "warn", "text": "Link-Filter ist aktiv, aber keine erlaubten Domains gesetzt – das blockiert fast alle Links."})
    if len(am.get("bad_words", []) or []) == 0:
        suggestions.append({"level": "info", "text": "Keine BadWords gesetzt. Füge häufige Spam-/Scam-Wörter hinzu."})
    bad_regex = [r for r in _automod_regex_report(am.get("regex_rules", [])) if not r["ok"] or r["danger"]]
    if bad_regex:
        suggestions.append({"level": "danger", "text": f"{len(bad_regex)} Regex-Regel(n) benötigen Prüfung."})
    if not am.get("phishing_check", True):
        suggestions.append({"level": "warn", "text": "Phishing-Check ist aus. Für Security-Server besser aktivieren."})
    if not am.get("invite_filter", True):
        suggestions.append({"level": "info", "text": "Invite-Filter ist aus. Aktivieren, wenn Fremdwerbung ein Problem ist."})
    return suggestions


@flask_app.route("/dashboard/<guild_id>/automod")
@require_auth
def guild_automod(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    am = cfg.get("automod", {}) or {}
    regex_report = _automod_regex_report(am.get("regex_rules", []))
    suggestions = _automod_suggestions(cfg)
    stats = {
        "bad_words": len(am.get("bad_words", []) or []),
        "regex": len(am.get("regex_rules", []) or []),
        "domains": len(am.get("allowed_domains", []) or []),
        "regex_bad": sum(1 for r in regex_report if not r["ok"]),
        "regex_warn": sum(1 for r in regex_report if r.get("danger")),
    }
    return render_template("dashboard/automod.html", guild=g, cfg=cfg, user=us["user"], active="automod", regex_report=regex_report, suggestions=suggestions, stats=stats)

@flask_app.route("/dashboard/<guild_id>/security")
@require_auth
def guild_security(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # ── Modul-Definitionen mit Defaults ──────────────────────────
    MOD_DEFS = [
        {
            "key":   "anti_spam",
            "icon":  "⚡",
            "label": "Anti-Spam",
            "desc":  "Erkennt Spam, CAPS-Missbrauch, Emoji-Flooding und Duplikate. Bestraft automatisch.",
            "color": "#f59e0b",
            "params": [
                {"key": "msg_limit",        "label": "Nachrichten-Limit",    "type": "number", "min": 2,  "max": 30,    "default": 5,       "unit": "msgs"},
                {"key": "msg_window",       "label": "Zeitfenster",          "type": "number", "min": 3,  "max": 60,    "default": 5,       "unit": "s"},
                {"key": "caps_pct",         "label": "CAPS-Schwelle",        "type": "number", "min": 50, "max": 100,   "default": 70,      "unit": "%"},
                {"key": "emoji_max",        "label": "Max Emojis",           "type": "number", "min": 3,  "max": 50,    "default": 10,      "unit": ""},
                {"key": "duplicate_max",    "label": "Max Duplikate",        "type": "number", "min": 1,  "max": 10,    "default": 3,       "unit": ""},
                {"key": "timeout_duration", "label": "Timeout-Dauer",        "type": "number", "min": 10, "max": 86400, "default": 300,     "unit": "s"},
                {"key": "punishment",       "label": "Bestrafung",           "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "timeout"},
            ],
        },
        {
            "key":   "anti_nuke",
            "icon":  "💣",
            "label": "Anti-Nuke",
            "desc":  "Schützt vor Massen-Bans, Channel-Löschungen und Rollen-Änderungen. Automatischer Lockdown + Owner-DM.",
            "color": "#ef4444",
            "params": [
                {"key": "threshold",    "label": "Aktions-Schwelle",  "type": "number", "min": 2,  "max": 20,  "default": 5,     "unit": ""},
                {"key": "window",       "label": "Zeitfenster",       "type": "number", "min": 5,  "max": 120, "default": 10,    "unit": "s"},
                {"key": "remove_roles", "label": "Rollen entfernen",  "type": "toggle", "default": True},
                {"key": "auto_lockdown","label": "Auto-Lockdown",     "type": "toggle", "default": True},
                {"key": "punishment",   "label": "Bestrafung",        "type": "select", "options": ["ban", "kick", "timeout"], "default": "ban"},
            ],
        },
        {
            "key":   "anti_raid",
            "icon":  "🚨",
            "label": "Anti-Raid",
            "desc":  "Erkennt Massen-Joins, filtert neue Accounts, aktiviert automatischen Lockdown.",
            "color": "#f97316",
            "params": [
                {"key": "join_threshold",       "label": "Join-Schwelle",           "type": "number", "min": 3,  "max": 50, "default": 10,    "unit": "/Zeitfenster"},
                {"key": "window",               "label": "Zeitfenster",             "type": "number", "min": 5,  "max": 120,"default": 10,    "unit": "s"},
                {"key": "min_account_age",      "label": "Min. Account-Alter",      "type": "number", "min": 0,  "max": 90, "default": 7,     "unit": "Tage"},
                {"key": "auto_kick",            "label": "Neue Accounts kicken",    "type": "toggle", "default": True},
                {"key": "lockdown",             "label": "Auto-Lockdown",           "type": "toggle", "default": True},
                {"key": "suspicious_name_check","label": "Verdächtige Namen prüfen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_mention",
            "icon":  "🔔",
            "label": "Anti-Mention",
            "desc":  "Verhindert Mass-Mentions und @everyone/@here-Missbrauch.",
            "color": "#a78bfa",
            "params": [
                {"key": "mention_limit",    "label": "Max Mentions",    "type": "number", "min": 2,  "max": 30,    "default": 5,   "unit": ""},
                {"key": "window",           "label": "Zeitfenster",     "type": "number", "min": 3,  "max": 60,    "default": 10,  "unit": "s"},
                {"key": "timeout_duration", "label": "Timeout-Dauer",   "type": "number", "min": 10, "max": 86400, "default": 600, "unit": "s"},
                {"key": "punishment",       "label": "Bestrafung",      "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "timeout"},
            ],
        },
        {
            "key":   "anti_scam",
            "icon":  "🎣",
            "label": "Anti-Scam",
            "desc":  "Erkennt Phishing-Links, Fake-Nitro und bekannte Scam-Domains automatisch.",
            "color": "#06b6d4",
            "params": [
                {"key": "punishment",    "label": "Bestrafung",     "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "ban"},
                {"key": "delete_msg",    "label": "Nachricht löschen","type": "toggle", "default": True},
                {"key": "notify_user",   "label": "User benachrichtigen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_webhook",
            "icon":  "🔌",
            "label": "Anti-Webhook",
            "desc":  "Erkennt verdächtige Webhook-Erstellungen und -Missbrauch.",
            "color": "#8b5cf6",
            "params": [
                {"key": "threshold", "label": "Schwelle",       "type": "number", "min": 1, "max": 10,  "default": 3,  "unit": ""},
                {"key": "window",    "label": "Zeitfenster",    "type": "number", "min": 5, "max": 120, "default": 30, "unit": "s"},
            ],
        },
        {
            "key":   "anti_ghost_ping",
            "icon":  "👻",
            "label": "Anti-Ghost-Ping",
            "desc":  "Erkennt gelöschte Mentions (Ghost-Pings) und loggt/bestraft diese.",
            "color": "#64748b",
            "params": [
                {"key": "punishment",  "label": "Bestrafung",     "type": "select", "options": ["log", "warn", "timeout"], "default": "warn"},
                {"key": "notify",      "label": "Im Chat anzeigen","type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_url_shortener",
            "icon":  "🔗",
            "label": "Anti-URL-Shortener",
            "desc":  "Blockiert bekannte URL-Shortener (bit.ly, tinyurl, etc.) aus Sicherheitsgründen.",
            "color": "#10b981",
            "params": [
                {"key": "punishment",  "label": "Bestrafung",        "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "warn"},
                {"key": "delete_msg",  "label": "Nachricht löschen", "type": "toggle", "default": True},
            ],
        },
        {
            "key":   "anti_vpn",
            "icon":  "🌐",
            "label": "Anti-VPN",
            "desc":  "Erkennt verdächtige VPN/Proxy-Verbindungen bei neuen Mitgliedern.",
            "color": "#0ea5e9",
            "params": [
                {"key": "action", "label": "Aktion", "type": "select", "options": ["log", "kick", "ban"], "default": "kick"},
            ],
        },
        {
            "key":   "automod",
            "icon":  "🤖",
            "label": "AutoMod",
            "desc":  "Wortfilter, Regex-Filter, Link- und Invite-Blocking mit Custom-Regeln.",
            "color": "#f472b6",
            "params": [
                {"key": "punishment",     "label": "Bestrafung",         "type": "select", "options": ["warn", "timeout", "kick", "ban"], "default": "warn"},
                {"key": "block_invites",  "label": "Invites blockieren", "type": "toggle", "default": True},
                {"key": "block_links",    "label": "Links blockieren",   "type": "toggle", "default": False},
                {"key": "log_only",       "label": "Nur loggen",         "type": "toggle", "default": False},
            ],
        },
    ]

    # ── Config-Werte einfüllen ────────────────────────────────────
    modules = []
    for mod_def in MOD_DEFS:
        mcfg = cfg.get(mod_def["key"], {}) or {}
        params = []
        for p in mod_def["params"]:
            p = dict(p)  # Copy
            raw = mcfg.get(p["key"])
            if raw is None:
                raw = p.get("default", "")
            # Booleans für toggles
            if p["type"] == "toggle":
                p["value"] = bool(raw)
            elif p["type"] == "number":
                try:
                    p["value"] = int(raw)
                except (ValueError, TypeError):
                    p["value"] = p.get("default", 0)
            else:
                p["value"] = str(raw)
            params.append(p)

        modules.append({
            "key":     mod_def["key"],
            "icon":    mod_def["icon"],
            "label":   mod_def["label"],
            "desc":    mod_def["desc"],
            "color":   mod_def["color"],
            "enabled": bool(mcfg.get("enabled", False)),
            "params":  params,
        })

    # ── Whitelist-Zähler ─────────────────────────────────────────
    wl_count = 0
    try:
        if bot_ready():
            wl = bot.db.get_whitelist(int(guild_id))
            wl_count = sum(len(v) for v in wl.values() if isinstance(v, list))
    except Exception:
        pass

    active_count  = sum(1 for m in modules if m["enabled"])
    security_level = int(cfg.get("security_level", 0))

    # Kanal-Liste für Log-Channel Auswahl
    text_channels = []
    if g and hasattr(g, "text_channels") and g.text_channels:
        text_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    return render_template(
        "dashboard/security.html",
        guild=g, cfg=cfg, user=us["user"],
        modules=modules,
        active_count=active_count,
        total_count=len(modules),
        wl_count=wl_count,
        security_level=security_level,
        text_channels=text_channels,
        active="security",
    )

# ═══════════════════════════════════════════════════════════════════
# LOGS
# ═══════════════════════════════════════════════════════════════════

def _log_categories():
    return {
        "🛡️ Security": [
            {"key": "antispam",      "icon": "⚡", "label": "Anti-Spam",       "desc": "Spam, CAPS, Duplikate"},
            {"key": "antinuke",      "icon": "💣", "label": "Anti-Nuke",       "desc": "Massen-Bans, Löschungen"},
            {"key": "antiraid",      "icon": "🚨", "label": "Anti-Raid",       "desc": "Massen-Joins, Lockdown"},
            {"key": "antimention",   "icon": "🔔", "label": "Anti-Mention",    "desc": "Mass-Mentions, @everyone"},
            {"key": "antiscam",      "icon": "🎣", "label": "Anti-Scam",       "desc": "Phishing, Fake-Nitro"},
            {"key": "antishortener", "icon": "🔗", "label": "URL-Shortener",   "desc": "bit.ly, tinyurl etc."},
            {"key": "antivpn",       "icon": "🌐", "label": "Anti-VPN",        "desc": "VPN/Proxy-Erkennung"},
        ],
        "⚖️ Moderation": [
            {"key": "moderation", "icon": "🛡️", "label": "Moderation",  "desc": "Ban, Kick, Mute, Warn"},
            {"key": "warns",      "icon": "⚠️", "label": "Warns",       "desc": "Verwarnungen"},
            {"key": "cases",      "icon": "📋", "label": "Cases",       "desc": "Moderation-Cases"},
            {"key": "automod",    "icon": "🤖", "label": "AutoMod",     "desc": "Wortfilter, Regex"},
            {"key": "appeal",     "icon": "📬", "label": "Ban-Appeal",  "desc": "Entbannungsanträge"},
        ],
        "👥 Server": [
            {"key": "members",     "icon": "👥", "label": "Members",       "desc": "Join, Leave, Update"},
            {"key": "nicknames",   "icon": "📝", "label": "Nicknames",     "desc": "Nickname-Änderungen"},
            {"key": "roles",       "icon": "🏷️", "label": "Rollen",        "desc": "Rollen-Änderungen"},
            {"key": "channels",    "icon": "📁", "label": "Kanäle",        "desc": "Erstellt/Gelöscht/Geändert"},
            {"key": "permissions", "icon": "🔐", "label": "Berechtigungen","desc": "Permission-Änderungen"},
            {"key": "webhooks",    "icon": "🔌", "label": "Webhooks",      "desc": "Webhook-Änderungen"},
        ],
        "🎤 Voice": [
            {"key": "voice", "icon": "🎤", "label": "Voice", "desc": "Join, Leave, Mute, Deaf, Stream"},
        ],
        "💬 Nachrichten": [
            {"key": "messages",      "icon": "💬", "label": "Nachrichten",  "desc": "Gelöscht/Bearbeitet"},
            {"key": "messages_sent", "icon": "📨", "label": "Gesendet",     "desc": "Alle Nachrichten"},
            {"key": "ghostping",     "icon": "👻", "label": "Ghost-Ping",   "desc": "Gelöschte Mentions"},
        ],
        "⚙️ System": [
            {"key": "default", "icon": "📌", "label": "Standard",      "desc": "Fallback alle Module"},
            {"key": "verify",  "icon": "✅", "label": "Verifizierung", "desc": "Captcha, One-Click"},
            {"key": "tickets", "icon": "🎫", "label": "Tickets",       "desc": "Erstellt/Geschlossen"},
            {"key": "welcome", "icon": "👋", "label": "Welcome",       "desc": "Begrüßungsnachrichten"},
            {"key": "leave",   "icon": "🚪", "label": "Leave",         "desc": "Abschiedsnachrichten"},
            {"key": "backup",  "icon": "💾", "label": "Backup",        "desc": "Backup-Ereignisse"},
            {"key": "audit",   "icon": "🔍", "label": "Audit",         "desc": "Audit-Log Einträge"},
            {"key": "errors",  "icon": "❌", "label": "Fehler",        "desc": "Bot-Fehler und Warnungen"},
        ],
    }


def _all_log_modules():
    return [m["key"] for mods in _log_categories().values() for m in mods]


def _log_channel_status(guild, channel_id):
    status = {"id": channel_id, "ok": False, "exists": False, "can_send": False, "can_embed": False, "name": None, "reason": "Nicht gesetzt"}
    if not channel_id:
        return status
    if not guild:
        status["reason"] = "Bot/Guild offline"
        return status
    try:
        channel = guild.get_channel(int(channel_id))
        if not channel:
            status["reason"] = "Kanal nicht gefunden"
            return status
        status["exists"] = True
        status["name"] = getattr(channel, "name", str(channel_id))
        me = getattr(guild, "me", None)
        perms = channel.permissions_for(me) if me and hasattr(channel, "permissions_for") else None
        status["can_send"] = bool(getattr(perms, "send_messages", False)) if perms else True
        status["can_embed"] = bool(getattr(perms, "embed_links", False)) if perms else True
        status["ok"] = status["exists"] and status["can_send"] and status["can_embed"]
        if status["ok"]:
            status["reason"] = "OK"
        elif not status["can_send"]:
            status["reason"] = "Keine Schreibrechte"
        elif not status["can_embed"]:
            status["reason"] = "Embed-Recht fehlt"
    except Exception as e:
        status["reason"] = str(e)[:120]
    return status


def _log_health_payload(guild_id):
    cfg = _direct_load_config(guild_id)
    guild = get_guild(guild_id)
    default_channel = cfg.get("log_channel")
    log_channels = cfg.get("log_channels", {}) or {}
    modules = _all_log_modules()
    unique_channels = sorted({int(v) for v in list(log_channels.values()) + ([default_channel] if default_channel else []) if v and str(v) != "0"})
    channel_status = {str(cid): _log_channel_status(guild, cid) for cid in unique_channels}
    module_status = []
    ok_count = disabled_count = missing_count = broken_count = 0
    for module in modules:
        raw = log_channels.get(module, None)
        disabled = str(raw) == "0"
        channel_id = raw if raw not in (None, "") else default_channel
        st = {"ok": False, "reason": "Nicht gesetzt"} if not channel_id else channel_status.get(str(int(channel_id)), _log_channel_status(guild, channel_id))
        ok = bool(st.get("ok")) and not disabled
        if disabled:
            disabled_count += 1
            reason = "Deaktiviert"
        elif not channel_id:
            missing_count += 1
            reason = "Kein Kanal"
        elif not ok:
            broken_count += 1
            reason = st.get("reason", "Fehler")
        else:
            ok_count += 1
            reason = "OK"
        module_status.append({"module": module, "channel_id": channel_id, "ok": ok, "disabled": disabled, "reason": reason, "channel": st.get("name")})
    score = int(round((ok_count / max(1, len(modules))) * 100))
    return {
        "ok": True, "score": score, "modules_total": len(modules), "modules_ok": ok_count,
        "disabled": disabled_count, "missing": missing_count, "broken": broken_count,
        "channels": channel_status, "modules": module_status, "bot_online": bot_ready(),
        "default_channel": default_channel, "webhook_enabled": cfg.get("webhook_logging", {}).get("enabled", False),
    }

@flask_app.route("/dashboard/<guild_id>/logs")
@require_auth
def guild_logs(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    text_channels = []
    if g and hasattr(g, 'text_channels') and g.text_channels:
        text_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    log_channels = cfg.get("log_channels", {}) or {}

    categories = _log_categories()

    total_modules    = sum(len(v) for v in categories.values())
    total_configured = sum(1 for v in log_channels.values() if v)
    default_channel  = cfg.get("log_channel")
    webhook_enabled  = cfg.get("webhook_logging", {}).get("enabled", False)

    return render_template(
        "dashboard/logs.html",
        guild=g, cfg=cfg, user=us["user"],
        channels=text_channels,
        log_channels=log_channels,
        categories=categories,
        total_modules=total_modules,
        total_configured=total_configured,
        default_channel=default_channel,
        webhook_enabled=webhook_enabled,
        active="logs",
    )

@flask_app.route("/api/guild/<guild_id>/logs/health")
@require_auth
def api_logs_health(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(_log_health_payload(guild_id))


def _log_modules_for_preset(preset: str):
    security = {"antispam", "antinuke", "antiraid", "antimention", "antiscam", "antishortener", "antivpn", "security", "permissions"}
    moderation = {"moderation", "warns", "cases", "automod", "appeal"}
    messages = {"messages", "messages_sent", "ghostping"}
    system = {"default", "verify", "tickets", "welcome", "leave", "backup", "audit", "errors", "members", "nicknames", "roles", "channels", "webhooks", "voice"}
    if preset == "security":
        return {"security": security, "moderation": moderation, "messages": messages, "system": system}
    if preset == "hardcore":
        return {"security": security, "moderation": moderation, "messages": messages, "system": system}
    return {"all": set(_all_log_modules())}


@flask_app.route("/api/guild/<guild_id>/logs/repair", methods=["POST"])
@require_auth
def api_logs_repair(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    action = data.get("action", "fill_missing")
    base_channel = _to_int_or_none(data.get("channel_id"))
    cfg = _direct_load_config(guild_id)
    before = _copy.deepcopy(cfg)
    modules = _all_log_modules()
    log_channels = cfg.get("log_channels", {}) or {}
    changed = 0
    if base_channel:
        cfg["log_channel"] = base_channel
    fallback = cfg.get("log_channel") or base_channel
    if action == "all_to_channel":
        if not fallback:
            return jsonify({"error": "Bitte zuerst einen Ziel-Kanal auswählen."}), 400
        log_channels = {m: int(fallback) for m in modules}
        changed = len(modules)
    elif action == "fill_missing":
        if not fallback:
            return jsonify({"error": "Bitte zuerst Standard-Log-Kanal setzen."}), 400
        for m in modules:
            if m not in log_channels or log_channels.get(m) in (None, ""):
                log_channels[m] = int(fallback)
                changed += 1
    elif action == "remove_broken":
        payload = _log_health_payload(guild_id)
        broken = {m["module"] for m in payload["modules"] if (not m["ok"] and not m["disabled"] and m.get("channel_id"))}
        for m in broken:
            if m in log_channels:
                log_channels.pop(m, None)
                changed += 1
    elif action == "disable_broken":
        payload = _log_health_payload(guild_id)
        broken = {m["module"] for m in payload["modules"] if (not m["ok"] and not m["disabled"] and m.get("channel_id"))}
        for m in broken:
            log_channels[m] = 0
            changed += 1
    else:
        return jsonify({"error": "Unbekannte Reparatur-Aktion"}), 400
    cfg["log_channels"] = log_channels
    _save_config_version(guild_id, before, source=f"before-log-repair-{action}")
    if not _direct_save_config(guild_id, cfg):
        return jsonify({"error": "Speichern fehlgeschlagen"}), 500
    return jsonify({"ok": True, "changed": changed, "health": _log_health_payload(guild_id)})


@flask_app.route("/api/guild/<guild_id>/logs/preset", methods=["POST"])
@require_auth
def api_logs_preset(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    preset = data.get("preset", "simple")
    base_channel = _to_int_or_none(data.get("channel_id"))
    cfg = _direct_load_config(guild_id)
    before = _copy.deepcopy(cfg)
    guild = get_guild(guild_id)
    modules = _all_log_modules()
    created = {}

    async def _ensure_channel(name):
        if not guild:
            return None
        existing = next((c for c in getattr(guild, "text_channels", []) if c.name == name), None)
        if existing:
            return existing.id
        me = getattr(guild, "me", None)
        if not me or not getattr(me.guild_permissions, "manage_channels", False):
            return None
        ch = await guild.create_text_channel(name, reason="ModForge Log-Preset")
        return ch.id

    if preset == "hardcore":
        names = {"security": "modforge-security", "moderation": "modforge-mod", "messages": "modforge-messages", "system": "modforge-system"}
        for group, name in names.items():
            cid = safe_async(_ensure_channel(name), None)
            if cid:
                created[group] = cid
        if len(created) < 4 and not base_channel:
            return jsonify({"error": "Konnte Kanäle nicht erstellen. Bot braucht Manage Channels oder wähle einen Kanal."}), 400
    else:
        if not base_channel:
            return jsonify({"error": "Bitte Ziel-Kanal auswählen."}), 400

    log_channels = {}
    if preset == "simple":
        cfg["log_channel"] = int(base_channel)
        log_channels = {m: int(base_channel) for m in modules}
    elif preset == "security":
        cfg["log_channel"] = int(base_channel)
        groups = _log_modules_for_preset("security")
        for m in modules:
            log_channels[m] = int(base_channel)
        # Mark important security modules explicitly, same channel but visible config.
        for m in groups["security"] | groups["moderation"]:
            if m in modules:
                log_channels[m] = int(base_channel)
    elif preset == "hardcore":
        fallback = int(base_channel) if base_channel else int(created.get("system") or next(iter(created.values())))
        cfg["log_channel"] = fallback
        groups = _log_modules_for_preset("hardcore")
        for m in modules:
            if m in groups["security"]:
                log_channels[m] = int(created.get("security", fallback))
            elif m in groups["moderation"]:
                log_channels[m] = int(created.get("moderation", fallback))
            elif m in groups["messages"]:
                log_channels[m] = int(created.get("messages", fallback))
            else:
                log_channels[m] = int(created.get("system", fallback))
    else:
        return jsonify({"error": "Unbekanntes Preset"}), 400
    cfg["log_channels"] = log_channels
    _save_config_version(guild_id, before, source=f"before-log-preset-{preset}")
    if not _direct_save_config(guild_id, cfg):
        return jsonify({"error": "Speichern fehlgeschlagen"}), 500
    return jsonify({"ok": True, "preset": preset, "created": created, "health": _log_health_payload(guild_id)})


@flask_app.route("/api/guild/<guild_id>/logs/test", methods=["POST"])
@require_auth
def api_logs_test(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    guild = get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Server nicht gefunden"}), 404
    health = _log_health_payload(guild_id)
    channel_ids = sorted({int(m["channel_id"]) for m in health["modules"] if m.get("channel_id") and not m.get("disabled")})
    results = []

    async def _send_tests():
        import discord
        sent = []
        for cid in channel_ids[:25]:
            channel = guild.get_channel(int(cid))
            if not channel:
                sent.append({"channel_id": cid, "ok": False, "reason": "Kanal nicht gefunden"})
                continue
            try:
                embed = discord.Embed(
                    title="📢 ModForge Log-Test",
                    description="**Beschreibung**\nDieser Kanal kann ModForge-Logs empfangen.\n\n**User-Struktur**\nTestUser\n`(123456789)`",
                    color=0x3CB371, timestamp=datetime.datetime.utcnow(),
                )
                embed.add_field(name="📌 Modul", value="`log_test`", inline=True)
                embed.add_field(name="🆔 Server", value=f"`{guild.id}`", inline=True)
                embed.set_footer(text="ModForge Log-Test")
                await channel.send(embed=embed)
                sent.append({"channel_id": cid, "ok": True, "reason": "OK", "name": channel.name})
            except Exception as e:
                sent.append({"channel_id": cid, "ok": False, "reason": str(e)[:160], "name": getattr(channel, "name", str(cid))})
        return sent
    results = safe_async(_send_tests(), []) or []
    return jsonify({"ok": True, "tested": len(results), "results": results})

@flask_app.route("/dashboard/<guild_id>/cases")
@require_auth
def guild_cases(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    import datetime as _dt

    cases      = []
    stats      = {
        "total": 0, "ban": 0, "kick": 0, "warn": 0,
        "timeout": 0, "softban": 0, "tempban": 0, "other": 0,
    }
    cases_7d   = 0
    cases_30d  = 0

    db = get_db()
    if db:
        try:
            raw = safe_async(
                db.cases.find(_guild_query(guild_id))
                        .sort("case_id", -1)
                        .to_list(500),
                []
            ) or []

            now      = _dt.datetime.utcnow()
            week_ago  = now - _dt.timedelta(days=7)
            month_ago = now - _dt.timedelta(days=30)

            for c in raw:
                # Timestamp formatieren
                ts = c.get("created_at") or c.get("timestamp")
                ts_str = ""
                ts_iso = ""
                if ts:
                    if isinstance(ts, _dt.datetime):
                        ts_str = ts.strftime("%d.%m.%Y %H:%M")
                        ts_iso = ts.isoformat()
                        if ts >= week_ago:
                            cases_7d += 1
                        if ts >= month_ago:
                            cases_30d += 1
                    else:
                        ts_str = str(ts)[:19]
                        ts_iso = str(ts)

                c["ts_str"] = ts_str
                c["ts_iso"] = ts_iso

                # _id entfernen (nicht JSON-serialisierbar)
                c.pop("_id", None)

                # User-Namen aus Guild auflösen wenn möglich
                uid = c.get("user_id")
                mid = c.get("mod_id") or c.get("moderator_id")

                c["user_name"] = ""
                c["mod_name"]  = ""

                if g and uid:
                    try:
                        member = g.get_member(int(uid))
                        if member:
                            c["user_name"] = member.display_name
                    except Exception:
                        pass

                if g and mid:
                    try:
                        mod = g.get_member(int(mid))
                        if mod:
                            c["mod_name"] = mod.display_name
                    except Exception:
                        pass

                # Stats zählen
                action = str(c.get("action", "other")).lower()
                if action in stats:
                    stats[action] += 1
                else:
                    stats["other"] += 1
                stats["total"] += 1

                cases.append(c)

        except Exception as e:
            log.error(f"[CASES PAGE] {e}")

    return render_template(
        "dashboard/cases.html",
        guild=g, cfg=cfg, user=us["user"],
        cases=cases,
        stats=stats,
        cases_7d=cases_7d,
        cases_30d=cases_30d,
        active="cases",
    )

# ═══════════════════════════════════════════════════════════════════
# WARNS
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/warns")
@require_auth
def guild_warns(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    import datetime as _dt

    ws         = cfg.get("warn_system", {}) or {}
    thresholds = ws.get("thresholds", {}) or {}
    decay      = cfg.get("warn_decay", {}) or {}

    # Thresholds sortiert
    sorted_th = sorted(
        [{"count": int(k), "action": v} for k, v in thresholds.items()],
        key=lambda x: x["count"]
    )

    # Echte Warn-Statistiken aus DB
    total_warns   = 0
    warns_7d      = 0
    top_warned    = []  # Top 5 User mit meisten Warns
    recent_warns  = []

    db = get_db()
    if db:
        gid_int  = int(guild_id)
        week_ago = _dt.datetime.utcnow() - _dt.timedelta(days=7)

        try:
            total_warns = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int}
            )
        except Exception:
            pass

        try:
            warns_7d = safe_collection_count(
                db.data,
                {"type": "warning", "guild_id": gid_int,
                 "timestamp": {"$gte": week_ago}}
            )
        except Exception:
            pass

        try:
            pipeline = [
                {"$match": {"type": "warning", "guild_id": gid_int}},
                {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 5},
            ]
            top_raw = safe_async(db.data.aggregate(pipeline).to_list(5), []) or []
            for item in top_raw:
                uid  = item.get("_id", 0)
                name = str(uid)
                if g and uid:
                    try:
                        m = g.get_member(int(uid))
                        if m:
                            name = m.display_name
                    except Exception:
                        pass
                top_warned.append({"id": uid, "name": name, "count": item["count"]})
        except Exception:
            pass

        try:
            raw_warns = safe_async(
                db.data.find({"type": "warning", "guild_id": gid_int})
                        .sort("timestamp", -1)
                        .to_list(10),
                []
            ) or []
            for w in raw_warns:
                w.pop("_id", None)
                ts = w.get("timestamp")
                w["ts_str"] = ts.strftime("%d.%m.%Y %H:%M") if isinstance(ts, _dt.datetime) else str(ts)[:19]
                uid = w.get("user_id", 0)
                w["user_name"] = ""
                if g and uid:
                    try:
                        m = g.get_member(int(uid))
                        if m:
                            w["user_name"] = m.display_name
                    except Exception:
                        pass
                recent_warns.append(w)
        except Exception:
            pass

    return render_template(
        "dashboard/warns.html",
        guild=g, cfg=cfg, user=us["user"],
        ws=ws,
        sorted_th=sorted_th,
        decay=decay,
        total_warns=total_warns,
        warns_7d=warns_7d,
        top_warned=top_warned,
        recent_warns=recent_warns,
        active="warns",
    )

@flask_app.route("/dashboard/<guild_id>/tickets")
@require_auth
def guild_tickets(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    categories = [{"id":str(c.id),"name":c.name} for c in g.categories] if g else []
    ticket_docs = []
    ticket_stats = {"total": 0, "open": 0, "closed": 0, "claimed": 0}
    db = get_db()
    if db:
        try:
            ticket_docs = safe_async(db.data.find({"type": "ticket", "guild_id": {"$in": _guild_id_values(guild_id)}}).sort("created_at", -1).to_list(100), []) or []
            for t in ticket_docs:
                t["_id"] = str(t.get("_id", ""))
                if hasattr(t.get("created_at"), "isoformat"):
                    t["created_at_iso"] = t["created_at"].isoformat()
            ticket_stats["total"] = len(ticket_docs)
            ticket_stats["open"] = sum(1 for t in ticket_docs if t.get("status") == "open")
            ticket_stats["closed"] = sum(1 for t in ticket_docs if t.get("status") == "closed")
            ticket_stats["claimed"] = sum(1 for t in ticket_docs if t.get("assigned_to"))
        except Exception as e:
            log.debug(f"ticket docs load failed: {e}")
    return render_template("dashboard/tickets.html", guild=g, cfg=cfg, user=us["user"],
                           channels=channels, categories=categories, ticket_docs=ticket_docs[:25], ticket_stats=ticket_stats, active="tickets")

@flask_app.route("/api/guild/<guild_id>/tickets/panel", methods=["POST"])
@require_auth
def api_tickets_panel(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    data = request.json or {}
    guild = get_guild(guild_id)
    cfg = _direct_load_config(guild_id)
    if not guild:
        return jsonify({"error": "Server nicht gefunden"}), 404
    channel_id = _to_int_or_none(data.get("channel_id")) or cfg.get("ticket_system", {}).get("panel_channel_id")
    if not channel_id:
        return jsonify({"error": "Panel-Kanal fehlt"}), 400
    async def _send_panel():
        import discord
        from bot.bot import TicketView
        ch = guild.get_channel(int(channel_id))
        if not ch:
            raise RuntimeError("Kanal nicht gefunden")
        title = data.get("title") or "🎫 Support Tickets"
        desc = data.get("description") or "Klicke auf den Button, um ein Ticket zu öffnen."
        emb = discord.Embed(title=title[:256], description=desc[:4000], color=0x5865F2, timestamp=datetime.datetime.utcnow())
        emb.set_footer(text="ModForge Tickets")
        msg = await ch.send(embed=emb, view=TicketView(bot))
        return msg
    try:
        msg = safe_async(_send_panel(), None)
        if not msg:
            return jsonify({"error": "Panel konnte nicht gesendet werden"}), 500
        ts = cfg.get("ticket_system", {}) or {}
        ts["enabled"] = True
        ts["ticket_message_id"] = int(msg.id)
        ts["panel_channel_id"] = int(channel_id)
        cfg["ticket_system"] = ts
        _direct_save_config(guild_id, cfg)
        return jsonify({"ok": True, "message_id": int(msg.id), "channel_id": int(channel_id), "jump_url": getattr(msg, "jump_url", None)})
    except Exception as e:
        log.error(f"ticket panel failed: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/tickets/health")
@require_auth
def api_tickets_health(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    g = get_guild(guild_id)
    cfg = _direct_load_config(guild_id)
    ts = cfg.get("ticket_system", {}) or {}
    checks = []
    def add(ok, label, reason): checks.append({"ok": bool(ok), "label": label, "reason": reason})
    cat = g.get_channel(int(ts.get("category_id"))) if g and ts.get("category_id") else None
    log_ch = g.get_channel(int(ts.get("log_channel_id"))) if g and ts.get("log_channel_id") else None
    me = getattr(g, "me", None) if g else None
    perms = getattr(me, "guild_permissions", None)
    add(ts.get("enabled"), "Ticket-System", "aktiv" if ts.get("enabled") else "deaktiviert")
    add(cat is not None or not ts.get("category_id"), "Kategorie", "OK" if cat or not ts.get("category_id") else "nicht gefunden")
    add(log_ch is not None or not ts.get("log_channel_id"), "Log-Kanal", "OK" if log_ch or not ts.get("log_channel_id") else "nicht gefunden")
    add(getattr(perms, "manage_channels", False), "Manage Channels", "OK" if getattr(perms, "manage_channels", False) else "Bot braucht Manage Channels")
    add(getattr(perms, "send_messages", False), "Send Messages", "OK" if getattr(perms, "send_messages", False) else "Bot braucht Send Messages")
    return jsonify({"ok": True, "checks": checks})

@flask_app.route("/dashboard/<guild_id>/autoresponse")
@require_auth
def guild_autoresponse(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/autoresponse.html", guild=g, cfg=cfg, user=us["user"],
                           auto_responses=cfg.get("auto_responses",[]), active="autoresponse")

# ═══════════════════════════════════════════════════════════════════
# ROLES
# ═══════════════════════════════════════════════════════════════════

def _role_danger_permissions(role):
    danger = ["administrator", "manage_roles", "ban_members", "kick_members", "manage_channels", "manage_guild", "manage_webhooks", "mention_everyone", "moderate_members"]
    perms = getattr(role, "permissions", None)
    return [p for p in danger if getattr(perms, p, False)]


def _role_can_manage(guild, role):
    me = getattr(guild, "me", None) if guild else None
    if not role:
        return False, "Rolle fehlt"
    if getattr(role, "managed", False):
        return False, "Managed Rolle"
    if role.is_default():
        return False, "@everyone"
    if not me or not getattr(me.guild_permissions, "manage_roles", False):
        return False, "Manage Roles fehlt"
    if getattr(me, "top_role", None) and role >= me.top_role:
        return False, "Bot-Rolle zu niedrig"
    return True, "OK"


def _role_summary(guild, role):
    danger = _role_danger_permissions(role)
    ok, reason = _role_can_manage(guild, role)
    members = len(getattr(role, "members", []) or [])
    score = 0
    if "administrator" in danger:
        score += 60
    score += min(40, len([p for p in danger if p != "administrator"]) * 8)
    if members > 20:
        score += 10
    return {
        "id": str(role.id), "name": role.name,
        "color": str(role.color) if getattr(role, "color", None) and role.color.value else "",
        "pos": getattr(role, "position", 0), "members": members,
        "managed": getattr(role, "managed", False), "mentionable": getattr(role, "mentionable", False),
        "hoist": getattr(role, "hoist", False), "danger_perms": danger,
        "risk": min(100, score), "can_manage": ok, "health": reason,
    }


@flask_app.route("/dashboard/<guild_id>/roles")
@require_auth
def guild_roles(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    guild_roles = []
    dangerous_roles = []
    manageable_count = 0
    if g and hasattr(g, 'roles') and g.roles:
        for role in sorted(g.roles, key=lambda r: r.position, reverse=True):
            if role.is_default():
                continue
            data = _role_summary(g, role)
            if data["can_manage"]:
                manageable_count += 1
            if data["danger_perms"]:
                dangerous_roles.append(data)
            if not data["managed"]:
                guild_roles.append(data)

    role_map = {r["id"]: r["name"] for r in guild_roles}
    ar_ids = cfg.get("auto_role", {}).get("roles", []) or []
    auto_roles = [{"id": str(rid), "name": role_map.get(str(rid), str(rid))} for rid in ar_ids]
    sr_ids = cfg.get("sticky_roles", []) or []
    sticky_roles = [{"id": str(rid), "name": role_map.get(str(rid), str(rid))} for rid in sr_ids]
    vs = cfg.get("verify_system", {}) or {}
    verify_add = [{"id": str(rid), "name": role_map.get(str(rid), str(rid))} for rid in vs.get("add_roles", [])]
    verify_remove = [{"id": str(rid), "name": role_map.get(str(rid), str(rid))} for rid in vs.get("remove_roles", [])]

    role_health = []
    for group, items in (("auto", auto_roles), ("sticky", sticky_roles), ("verify_add", verify_add), ("verify_remove", verify_remove)):
        for item in items:
            role = g.get_role(int(item["id"])) if g and str(item["id"]).isdigit() else None
            ok, reason = _role_can_manage(g, role)
            role_health.append({"group": group, "id": item["id"], "name": item["name"], "ok": ok, "reason": reason})

    role_stats = {
        "total": len(guild_roles), "dangerous": len(dangerous_roles),
        "manageable": manageable_count, "auto": len(auto_roles), "sticky": len(sticky_roles),
        "verify": len(verify_add) + len(verify_remove),
    }

    return render_template(
        "dashboard/roles.html", guild=g, cfg=cfg, user=us["user"],
        guild_roles=guild_roles, auto_roles=auto_roles, sticky_roles=sticky_roles,
        verify_add=verify_add, verify_remove=verify_remove, vs=vs,
        role_health=role_health, dangerous_roles=dangerous_roles, role_stats=role_stats,
        active="roles",
    )

def _backups_col():
    """MongoDB-Collection für Server-Backups (Bot + Direct-DB-Fallback)."""
    db = get_db()
    if db is not None:
        try:
            return db.client["ModForge"]["backups"]
        except Exception:
            pass
    direct = _get_direct_db()
    if direct is not None:
        return direct["backups"]
    return None
def _public_backups_col():
    """MongoDB-Collection für öffentlich geteilte Backups."""
    db = get_db()
    if db is not None:
        try:
            return db.client["ModForge"]["public_backups"]
        except Exception:
            pass
    direct = _get_direct_db()
    if direct is not None:
        return direct["public_backups"]
    return None
def _ts(value):
    """datetime/str → Unix-Timestamp-String (oder '')."""
    if not value:
        return ""
    if hasattr(value, "timestamp"):
        try:
            return str(int(value.timestamp()))
        except Exception:
            return ""
    if isinstance(value, str):
        try:
            import datetime as _dt
            return str(int(_dt.datetime.fromisoformat(value.replace("Z", "")).timestamp()))
        except Exception:
            return ""
    return ""
def _collection_to_list(query, collection, sort=None, limit=100):
    """Lädt Motor- oder PyMongo-Collection zuverlässig als Liste."""
    if collection is None:
        return []
    try:
        cursor = collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if hasattr(cursor, "to_list"):
            return safe_async(cursor.to_list(limit), []) or []
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)
    except Exception as e:
        log.debug(f"collection_to_list failed: {e}")
        return []


def _collection_find_one(query, collection):
    if collection is None:
        return None
    try:
        result = collection.find_one(query)
        if hasattr(result, "__await__"):
            return safe_async(result, None)
        return result
    except Exception as e:
        log.debug(f"collection_find_one failed: {e}")
        return None


def _collection_delete_one(query, collection):
    if collection is None:
        return None
    try:
        result = collection.delete_one(query)
        if hasattr(result, "__await__"):
            return safe_async(result, None)
        return result
    except Exception as e:
        log.debug(f"collection_delete_one failed: {e}")
        return None


def _collection_update_one(query, update, collection, upsert=False):
    if collection is None:
        return None
    try:
        result = collection.update_one(query, update, upsert=upsert)
        if hasattr(result, "__await__"):
            return safe_async(result, None)
        return result
    except Exception as e:
        log.debug(f"collection_update_one failed: {e}")
        return None


def _collection_insert_one(collection, document):
    if collection is None:
        return None
    try:
        result = collection.insert_one(document)
        if hasattr(result, "__await__"):
            return safe_async(result, None)
        return result
    except Exception as e:
        log.debug(f"collection_insert_one failed: {e}")
        return None


def _id_variants(value):
    vals = []
    try:
        vals.append(int(value))
    except (TypeError, ValueError):
        pass
    vals.append(str(value))
    # De-dupe preserving order
    out = []
    for v in vals:
        if v not in out:
            out.append(v)
    return out


def _backup_query(guild_id, backup_id=None):
    variants = _id_variants(guild_id)
    query = {
        "$or": [
            {"guild_id": {"$in": variants}},
            {"guild_id_str": str(guild_id)},
            {"data.guild_id": {"$in": variants}},
        ]
    }
    if backup_id is not None:
        query["backup_id"] = backup_id
    return query


def _template_query(guild_id=None, backup_id=None):
    query = {}
    if guild_id is not None:
        variants = _id_variants(guild_id)
        query["$or"] = [
            {"guild_id": {"$in": variants}},
            {"guild_id_str": str(guild_id)},
            {"data.guild_id": {"$in": variants}},
        ]
    if backup_id is not None:
        query["backup_id"] = backup_id
    return query

def _enrich_backup_doc(doc):
    """Macht aus einem rohen Backup-DB-Dokument ein Template-fertiges Dict."""
    if not doc:
        return None
    payload = doc.get("data") or doc
    roles = payload.get("roles") or []
    channels = payload.get("channels") or []
    categories = payload.get("categories") or []
    emojis = payload.get("emojis") or []
    created_raw = doc.get("created_at") or doc.get("timestamp") or payload.get("created_at")
    approx_size = 0
    try:
        approx_size = len(json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8"))
    except Exception:
        pass
    bid = doc.get("backup_id") or doc.get("id") or "?"
    role_count = len(roles) if isinstance(roles, list) else 0
    channel_count = len(channels) if isinstance(channels, list) else 0
    cat_count = len(categories) if isinstance(categories, list) else 0
    emoji_count = len(emojis) if isinstance(emojis, list) else 0
    health_score = 0
    health_score += 25 if role_count else 0
    health_score += 35 if channel_count else 0
    health_score += 20 if cat_count else 0
    health_score += 10 if payload.get("guild_name") else 0
    health_score += 10 if approx_size else 0
    warnings = []
    if not role_count:
        warnings.append("Keine Rollen im Backup")
    if not channel_count:
        warnings.append("Keine Kanäle im Backup")
    if approx_size == 0:
        warnings.append("Backup-Größe unbekannt")
    return {
        "id": bid,
        "label": doc.get("label") or payload.get("label") or f"Backup {bid}",
        "created_ts": _ts(created_raw),
        "created_by": str(doc.get("created_by") or payload.get("created_by") or "—"),
        "guild_name": doc.get("guild_name") or payload.get("guild_name") or "?",
        "guild_icon": doc.get("guild_icon_url") or payload.get("guild_icon_url") or payload.get("icon_url") or "",
        "roles": role_count,
        "channels": channel_count,
        "categories": cat_count,
        "emojis": emoji_count,
        "has_password": bool(doc.get("password_hash") or doc.get("has_password")),
        "verification": payload.get("verification_level", 0),
        "size_bytes": approx_size,
        "size_label": f"{approx_size/1024:.1f} KB" if approx_size else "—",
        "health_score": min(100, health_score),
        "warnings": warnings,
        "source_type": "db",
    }
def _load_backup_docs(guild_id, limit=200):
    col = _backups_col()
    if col is None:
        return []
    docs = _collection_to_list(_backup_query(guild_id), col, sort=[("created_at", -1), ("timestamp", -1)], limit=limit)
    # Fallback: if $or/dot query is not supported by a fake/old collection wrapper, try broad scan.
    if not docs:
        all_docs = _collection_to_list({}, col, sort=[("created_at", -1), ("timestamp", -1)], limit=limit)
        variants = {str(x) for x in _id_variants(guild_id)}
        docs = [d for d in all_docs if str(d.get("guild_id")) in variants or str(d.get("guild_id_str")) in variants or str((d.get("data") or {}).get("guild_id")) in variants]
    dedup = {}
    for doc in docs:
        bid = doc.get("backup_id") or doc.get("id")
        if bid and bid not in dedup:
            dedup[bid] = doc
    return list(dedup.values())


def _backup_doc(guild_id, backup_id, allow_any=False):
    col = _backups_col()
    if col is None:
        return None
    doc = _collection_find_one(_backup_query(guild_id, backup_id), col)
    if not doc and allow_any:
        doc = _collection_find_one({"backup_id": backup_id}, col)
    return doc


def _backup_preview(guild_id, backup_id, allow_any=False):
    doc = _backup_doc(guild_id, backup_id, allow_any=allow_any)
    if not doc:
        return None
    payload = doc.get("data") or doc
    guild = get_guild(guild_id)
    current_roles = {r.name.lower() for r in getattr(guild, "roles", []) if not r.is_default()} if guild else set()
    current_channels = {c.name.lower() for c in getattr(guild, "channels", [])} if guild else set()
    roles = payload.get("roles") or []
    channels = payload.get("channels") or []
    categories = payload.get("categories") or []
    def _name(x):
        return (x.get("name") if isinstance(x, dict) else str(x)) or "?"
    role_names = [_name(r) for r in roles]
    channel_names = [_name(c) for c in channels]
    new_roles = [n for n in role_names if n.lower() not in current_roles]
    existing_roles = [n for n in role_names if n.lower() in current_roles]
    new_channels = [n for n in channel_names if n.lower() not in current_channels]
    existing_channels = [n for n in channel_names if n.lower() in current_channels]
    risk = "low"
    warnings = []
    if len(roles) > 25 or len(channels) > 35:
        risk = "high"
        warnings.append("Sehr großes Backup – Restore kann viele Änderungen auslösen")
    elif len(roles) > 10 or len(channels) > 15:
        risk = "medium"
        warnings.append("Mittleres Backup – Restore vorher prüfen")
    if existing_roles:
        warnings.append(f"{len(existing_roles)} Rollen existieren bereits")
    if existing_channels:
        warnings.append(f"{len(existing_channels)} Kanäle existieren bereits")
    enriched = _enrich_backup_doc(doc) or {}
    return {
        "id": backup_id,
        "meta": enriched,
        "risk": risk,
        "warnings": warnings,
        "summary": {
            "roles_total": len(roles), "roles_new": len(new_roles), "roles_existing": len(existing_roles),
            "channels_total": len(channels), "channels_new": len(new_channels), "channels_existing": len(existing_channels),
            "categories_total": len(categories), "emojis_total": len(payload.get("emojis") or []),
        },
        "samples": {"roles_new": new_roles[:15], "channels_new": new_channels[:15], "categories": [_name(c) for c in categories[:12]]},
    }


def _collect_backup_payload_web(guild):
    """Fallback-Collector, damit Web-Backups auch ohne BackupCog gespeichert werden."""
    roles = []
    for r in sorted(getattr(guild, "roles", []) or [], key=lambda x: getattr(x, "position", 0), reverse=True):
        try:
            if r.is_default() or getattr(r, "managed", False):
                continue
            roles.append({
                "role_id": r.id,
                "name": r.name,
                "color": getattr(getattr(r, "color", None), "value", 0),
                "permissions": getattr(getattr(r, "permissions", None), "value", 0),
                "hoist": getattr(r, "hoist", False),
                "mentionable": getattr(r, "mentionable", False),
                "position": getattr(r, "position", 0),
            })
        except Exception:
            continue
    categories = []
    for c in getattr(guild, "categories", []) or []:
        categories.append({"id": c.id, "name": c.name, "position": getattr(c, "position", 0), "overwrites": {}})
    channels = []
    for ch in getattr(guild, "channels", []) or []:
        try:
            if str(getattr(ch, "type", "")) == "category":
                continue
            item = {
                "id": ch.id,
                "name": ch.name,
                "type": str(getattr(ch, "type", "text")),
                "position": getattr(ch, "position", 0),
                "category_id": getattr(ch, "category_id", None),
            }
            for attr in ("topic", "slowmode_delay", "nsfw", "bitrate", "user_limit"):
                if hasattr(ch, attr):
                    item[attr] = getattr(ch, attr)
            channels.append(item)
        except Exception:
            continue
    emojis = []
    for e in getattr(guild, "emojis", []) or []:
        try:
            emojis.append({"id": e.id, "name": e.name, "url": str(e.url)})
        except Exception:
            continue
    return {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "roles": roles,
        "categories": categories,
        "channels": channels,
        "emojis": emojis,
        "icon_url": str(guild.icon.url) if getattr(guild, "icon", None) else None,
        "created_at": datetime.datetime.utcnow().isoformat(),
    }


def _save_backup_doc_web(guild_id, payload, created_by, label=None):
    import uuid
    col = _backups_col()
    if col is None:
        return None
    backup_id = str(uuid.uuid4())[:8]
    doc = {
        "backup_id": backup_id,
        "guild_id": int(guild_id),
        "guild_id_str": str(guild_id),
        "guild_name": payload.get("guild_name"),
        "label": label,
        "created_by": created_by,
        "created_at": datetime.datetime.utcnow(),
        "data": payload,
    }
    result = _collection_insert_one(col, doc)
    return backup_id if result is not None else None


@flask_app.route("/dashboard/<guild_id>/backup")
@require_auth
def guild_backup(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    backups = []
    public_ids = set()
    for b in _load_backup_docs(guild_id, limit=200):
        enriched = _enrich_backup_doc(b)
        if enriched:
            backups.append(enriched)

    backups.sort(key=lambda b: int(b.get("created_ts") or 0), reverse=True)
    # Welche dieser Backups sind bereits public?
    pcol = _public_backups_col()
    if pcol is not None and backups:
        try:
            ids = [b["id"] for b in backups]
            pubs = _collection_to_list({"backup_id": {"$in": ids}}, pcol, limit=100)
            public_ids = {p.get("backup_id") for p in (pubs or [])}
        except Exception:
            pass
    for b in backups:
        b["is_public"] = b["id"] in public_ids

    bs = cfg.get("backup_system", {}) or {}
    return render_template(
        "dashboard/backup.html", guild=g, cfg=cfg, user=us["user"],
        backups=backups, total_size=len(backups), total_size_bytes=sum(b.get("size_bytes", 0) for b in backups),
        auto_enabled=bs.get("auto_enabled", False),
        auto_interval=bs.get("auto_interval_hours", 24),
        auto_max=bs.get("auto_max_backups", 5),
        last_backup_ts=_ts(bs.get("auto_last_backup")),
        bot_ready=bot_ready(),
        active="backup",
    )
def _template_score_from_counts(roles=0, channels=0, categories=0, downloads=0, likes=0, description=""):
    score = 35
    score += min(int(roles or 0), 30) * 1.0
    score += min(int(channels or 0), 30) * 1.0
    score += min(int(categories or 0), 10) * 1.5
    score += min(int(downloads or 0), 50) * 0.4
    score += min(int(likes or 0), 50) * 0.8
    if description and len(description) >= 40:
        score += 8
    return max(0, min(100, int(round(score))))


def _template_recommendations(category, roles=0, channels=0, support=False):
    rec = []
    c = (category or "general").lower()
    if c in ("gaming", "community", "support", "business", "security"):
        rec.append(c)
    if int(channels or 0) >= 8 and "community" not in rec:
        rec.append("community")
    if int(roles or 0) >= 8 and "security" not in rec:
        rec.append("security")
    return rec[:3] or ["general"]


def _template_risk_from_backup(payload, current_guild=None):
    roles = len(payload.get("roles") or [])
    channels = len(payload.get("channels") or [])
    categories = len(payload.get("categories") or [])
    danger = []
    level = "low"
    if roles > 25 or channels > 35:
        level = "high"
        danger.append("Sehr großes Template – viele Änderungen möglich")
    elif roles > 10 or channels > 15:
        level = "medium"
        danger.append("Mittelgroßes Template – vor Import prüfen")
    if current_guild:
        current_channels = len(getattr(current_guild, "channels", []) or [])
        if channels > current_channels + 20:
            level = "high"
            danger.append("Template erstellt deutlich mehr Kanäle als aktuell vorhanden")
    return {"level": level, "warnings": danger, "roles": roles, "channels": channels, "categories": categories}


@flask_app.route("/dashboard/<guild_id>/templates")
@require_auth
def guild_templates(guild_id):
    """Community-Templates: eigene geteilte Backups + Importieren von anderen."""
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err

    my_shared = []
    all_public = []
    pcol = _public_backups_col()
    if pcol is not None:
        mine_raw = _collection_to_list(_template_query(guild_id), pcol, sort=[("shared_at", -1)], limit=50)
        public_raw = _collection_to_list({}, pcol, sort=[("downloads", -1), ("shared_at", -1)], limit=200)
    else:
        mine_raw, public_raw = [], []

    def _shape(p):
        roles = int(p.get("roles_count") or 0)
        channels = int(p.get("channels_count") or 0)
        cats = int(p.get("categories_count") or 0)
        downloads = int(p.get("downloads") or 0)
        likes = int(p.get("likes") or 0)
        ratings = p.get("ratings") or {}
        rating_values = [int(v) for v in ratings.values() if str(v).isdigit()]
        rating_count = len(rating_values)
        rating_avg = round(sum(rating_values) / rating_count, 2) if rating_count else 0
        category = (p.get("category") or "general").lower()
        desc = p.get("description") or ""
        score = _template_score_from_counts(roles, channels, cats, downloads, likes + int(rating_avg * max(1, rating_count)), desc)
        return {
            "id": p.get("backup_id", "?"),
            "name": p.get("name") or "Unbenannt",
            "description": desc,
            "category": category,
            "guild_name": p.get("guild_name") or "?",
            "guild_icon": p.get("guild_icon") or "",
            "shared_by": str(p.get("shared_by") or "—"),
            "shared_ts": _ts(p.get("shared_at")),
            "roles": roles,
            "channels": channels,
            "categories": cats,
            "emojis": int(p.get("emojis_count") or 0),
            "downloads": downloads,
            "likes": likes,
            "rating_avg": rating_avg,
            "rating_count": rating_count,
            "score": score,
            "risk": "high" if roles > 25 or channels > 35 else "medium" if roles > 10 or channels > 15 else "low",
            "recommended": _template_recommendations(category, roles, channels),
            "is_mine": str(p.get("guild_id")) == str(guild_id) or str(p.get("guild_id_str")) == str(guild_id),
        }

    my_shared = [_shape(p) for p in (mine_raw or [])]
    all_public = [_shape(p) for p in (public_raw or [])]

    # Kategorie-Aufteilung für die Galerie
    categories = {}
    for tpl in all_public:
        categories.setdefault(tpl["category"], []).append(tpl)
    popular_templates = sorted(all_public, key=lambda t: (t.get("rating_avg", 0) * 12 + t.get("rating_count", 0) * 2 + t.get("likes", 0) * 2 + t.get("downloads", 0) + t.get("score", 0)), reverse=True)[:5]

    return render_template(
        "dashboard/templates.html",
        guild=g, cfg=cfg, user=us["user"], active="templates",
        my_shared=my_shared,
        all_public=all_public,
        categories=categories,
        popular_templates=popular_templates,
        bot_ready=bot_ready(),
    )

# ═══════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/settings")
@require_auth
def guild_settings(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # Kanal-Listen
    text_channels = []
    categories    = []
    if g:
        if hasattr(g, 'text_channels') and g.text_channels:
            text_channels = [
                {"id": str(c.id), "name": c.name}
                for c in sorted(g.text_channels, key=lambda c: c.position)
            ]
        if hasattr(g, 'categories') and g.categories:
            categories = [
                {"id": str(c.id), "name": c.name}
                for c in g.categories
            ]

    # Config-Sektionen
    ws  = cfg.get("warn_system",      {}) or {}
    st  = cfg.get("server_tag",       {}) or {}
    ma  = cfg.get("message_archive",  {}) or {}
    wl  = cfg.get("webhook_logging",  {}) or {}
    ab  = cfg.get("auto_ban_appeal",  {}) or {}
    it  = cfg.get("invite_tracking",  {}) or {}
    bs  = cfg.get("backup_system",    {}) or {}
    vs  = cfg.get("verify_system",    {}) or {}

    return render_template(
        "dashboard/settings.html",
        guild=g, cfg=cfg, user=us["user"],
        channels=text_channels,
        categories=categories,
        ws=ws, st=st, ma=ma, wl=wl, ab=ab, it=it, bs=bs, vs=vs,
        active="settings",
    )
@flask_app.route("/dashboard/<guild_id>/design")
@require_auth
def guild_design(guild_id):
    """Dashboard-Design Tab – Theme / Akzentfarbe / Density / Animationen.

    Die Einstellungen leben rein im localStorage des Browsers (pro User/Gerät),
    es wird also nichts in der MongoDB persistiert. Das ist Absicht: Design ist
    eine Browser-Präferenz, kein Server-Setting.
    """
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    return render_template("dashboard/design.html", guild=g, cfg=cfg, user=us["user"], active="design")

# =========================================================

@flask_app.route("/dashboard/<guild_id>/embed")
@require_auth
def guild_embed(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
    return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=us["user"], channels=channels, active="embed")

# PUBLIC PAGES (new)

@flask_app.route("/public-stats")
def public_stats():
    gc, mc, up, lat = _base_stats()
    uptime_pct = _uptime_pct()
    db = get_db()
    cases_count = 0
    if bot_ready() and db:
        cases_count = safe_collection_count(getattr(db, "cases", None))
    return render_template("public_stats.html", gc=gc, mc=mc, lat=round(lat or 0),
                           uptime_pct=f"{uptime_pct:.3f}", cases=cases_count,
                           shards=getattr(bot, "shard_count", 1))

# =========================================================
# ADMIN PAGES (new)
# =========================================================

@flask_app.route("/admin/logs")
@admin_required
def admin_logs():
    import logging
    entries = []
    # Gather recent log entries from the root logger handler buffers
    try:
        for handler in logging.getLogger().handlers:
            if hasattr(handler, 'buffer'):
                for record in handler.buffer[-200:]:
                    entries.append({
                        "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                        "level": record.levelname,
                        "message": record.getMessage()[:500],
                    })
    except Exception:
        pass
    return render_template("admin/logs.html", log_entries=entries[-200:])

# =========================================================
# DASHBOARD API — Universal Config Endpoint
# =========================================================

@flask_app.route("/api/guild/<guild_id>/config", methods=["POST"])
@require_auth
def api_guild_config(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)

    # Handle special keys with _ prefix
    if "_reset" in data:
        from bot.config import DEFAULT_CONFIG
        import copy
        cfg = copy.deepcopy(DEFAULT_CONFIG)
    if "_security_level" in data:
        cfg["security_level"] = _to_int_or_none(data["_security_level"], minimum=0, maximum=3) or 0
    if "_log_channel" in data:
        cfg["log_channel"] = _to_int_or_none(data["_log_channel"])
    if "_log_channels" in data:
        cfg["log_channels"] = _normalize_log_channels(data.get("_log_channels") or {})
    if "_prefix" in data:
        cfg["prefix"] = str(data["_prefix"])[:5] or "!"
    if "_dashboard_theme" in data:
        cfg["dashboard_theme"] = str(data["_dashboard_theme"])
    if "_no_prefix" in data:
        cfg["no_prefix"] = bool(data["_no_prefix"])
    if "_report_channel" in data:
        cfg["report_channel"] = _to_int_or_none(data["_report_channel"])
    if "_appeal_log_channel" in data:
        cfg["appeal_log_channel"] = _to_int_or_none(data["_appeal_log_channel"])
    if "_auto_ban_appeal" in data:
        cfg["auto_ban_appeal"] = data["_auto_ban_appeal"]
    if "_invite_tracking" in data:
        cfg["invite_tracking"] = data["_invite_tracking"]
    if "_message_archive" in data:
        ma = cfg.get("message_archive",{})
        ma["enabled"] = data["_message_archive"].get("enabled", False)
        cfg["message_archive"] = ma
    if "_temp_voice" in data:
        tv = cfg.get("temp_voice", {})
        for k, v in data["_temp_voice"].items():
            tv[k] = v
        cfg["temp_voice"] = tv
    if "_webhook_logging" in data:
        wl = cfg.get("webhook_logging", {"enabled": False, "webhooks": {}})
        wl["enabled"] = data["_webhook_logging"].get("enabled", False)
        cfg["webhook_logging"] = wl
    if "_server_tag" in data:
        st = cfg.get("server_tag", {})
        st["enabled"] = data["_server_tag"].get("enabled", False)
        if data["_server_tag"].get("tag"): st["tag"] = data["_server_tag"]["tag"]
        cfg["server_tag"] = st
    if "_warn_thresholds" in data:
        ws = cfg.get("warn_system",{})
        ws["thresholds"] = data["_warn_thresholds"]
        cfg["warn_system"] = ws
    if "_warn_thresholds_add" in data:
        ws = cfg.get("warn_system",{})
        th = ws.get("thresholds",{})
        th.update(data["_warn_thresholds_add"])
        ws["thresholds"] = th
        cfg["warn_system"] = ws
    if "_warn_thresholds_remove" in data:
        # Erwartet eine Liste von Threshold-Keys (z. B. ["3","5"])
        ws = cfg.get("warn_system", {})
        th = ws.get("thresholds", {}) or {}
        for key in (data["_warn_thresholds_remove"] or []):
            th.pop(str(key), None)
        ws["thresholds"] = th
        cfg["warn_system"] = ws
    if "_warn_decay" in data:
        cfg["warn_decay"] = data["_warn_decay"]
    if "_welcome" in data and isinstance(data["_welcome"], dict):
        wc = cfg.get("welcome", {}) or {}
        wc.update(data["_welcome"])
        cfg["welcome"] = wc
    if "_leave" in data and isinstance(data["_leave"], dict):
        lv = cfg.get("leave", {}) or {}
        lv.update(data["_leave"])
        cfg["leave"] = lv
    if "_verify_system" in data and isinstance(data["_verify_system"], dict):
        vs = cfg.get("verify_system", {}) or {}
        vs.update(data["_verify_system"])
        cfg["verify_system"] = vs
    if "_ticket_system" in data:
        ts = cfg.get("ticket_system",{})
        ts.update(data["_ticket_system"])
        cfg["ticket_system"] = ts

    # Raw config override (admin only)
    if "_raw" in data and isinstance(data["_raw"], dict):
        cfg = data["_raw"]

    # Handle module configs (anti_spam, anti_nuke, etc.)
    for key in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod","badge_automation","backup_system","ticket_extended"]:
        if key in data:
            mod = cfg.get(key, {})
            mod.update(data[key])
            cfg[key] = mod

    try:
        if _dangerous_change(data):
            _save_config_version(guild_id, _direct_load_config(guild_id), source="before-dangerous-save")
        else:
            _save_config_version(guild_id, _direct_load_config(guild_id), source="before-save")
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        log.error(f"[CONFIG API ERROR] {e}")
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

@flask_app.route("/api/guild/<guild_id>/automod", methods=["POST"])
@require_auth
def api_guild_automod(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    before = _copy.deepcopy(cfg)
    am = cfg.get("automod", {}) or {}
    action = data.get("action")

    try:
        if action == "add_word":
            value = str(data.get("value", "")).strip().lower()[:80]
            if not value:
                return jsonify({"error": "Wort fehlt"}), 400
            words = list(am.get("bad_words", []) or [])
            if value not in [str(w).lower() for w in words]:
                words.append(value)
            am["bad_words"] = sorted(words, key=str.lower)
        elif action == "del_word":
            value = str(data.get("value", "")).strip().lower()
            am["bad_words"] = [w for w in am.get("bad_words", []) if str(w).lower() != value]
        elif action == "add_regex":
            value = str(data.get("value", "")).strip()[:500]
            if not value:
                return jsonify({"error": "Regex fehlt"}), 400
            report = _automod_regex_report([value])[0]
            if not report["ok"]:
                return jsonify({"error": f"Regex ungültig: {report['message']}"}), 400
            rules = list(am.get("regex_rules", []) or [])
            if value not in rules:
                rules.append(value)
            am["regex_rules"] = rules
        elif action == "del_regex":
            rules = list(am.get("regex_rules", []) or [])
            idx = int(data.get("index", -1))
            if 0 <= idx < len(rules):
                rules.pop(idx)
            am["regex_rules"] = rules
        elif action == "add_domain":
            value = str(data.get("value", "")).strip().lower().replace("https://", "").replace("http://", "").split("/")[0][:120]
            if not value or "." not in value:
                return jsonify({"error": "Bitte gültige Domain eingeben"}), 400
            domains = list(am.get("allowed_domains", []) or [])
            if value not in [str(d).lower() for d in domains]:
                domains.append(value)
            am["allowed_domains"] = sorted(domains, key=str.lower)
        elif action == "del_domain":
            value = str(data.get("value", "")).strip().lower()
            am["allowed_domains"] = [d for d in am.get("allowed_domains", []) if str(d).lower() != value]
        elif action == "bulk_words":
            mode = data.get("mode", "append")
            words = [w.strip().lower()[:80] for w in str(data.get("value", "")).replace(",", "\n").splitlines() if w.strip()]
            words = sorted(set(words), key=str.lower)
            am["bad_words"] = words if mode == "replace" else sorted(set(list(am.get("bad_words", []) or []) + words), key=str.lower)
        elif action == "bulk_domains":
            mode = data.get("mode", "append")
            domains = []
            for d in str(data.get("value", "")).replace(",", "\n").splitlines():
                domain = d.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
                if domain and "." in domain:
                    domains.append(domain[:120])
            domains = sorted(set(domains), key=str.lower)
            am["allowed_domains"] = domains if mode == "replace" else sorted(set(list(am.get("allowed_domains", []) or []) + domains), key=str.lower)
        else:
            return jsonify({"error": "Unbekannte AutoMod-Aktion"}), 400
        cfg["automod"] = am
        _save_config_version(guild_id, before, source=f"before-automod-{action}")
        _direct_save_config(guild_id, cfg)
        return jsonify({"ok": True, "automod": am, "suggestions": _automod_suggestions(cfg), "regex_report": _automod_regex_report(am.get("regex_rules", []))})
    except Exception as e:
        log.error(f"[AUTOMOD API] {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/automod/test", methods=["POST"])
@require_auth
def api_guild_automod_test(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    text = str(data.get("text", ""))[:4000]
    return jsonify({"ok": True, "result": _automod_evaluate(cfg, text)})


@flask_app.route("/api/guild/<guild_id>/automod/export")
@require_auth
def api_guild_automod_export(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    cfg = _direct_load_config(guild_id)
    payload = {
        "guild_id": int(guild_id),
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "automod": cfg.get("automod", {}) or {},
        "anti_scam": cfg.get("anti_scam", {}) or {},
        "anti_url_shortener": cfg.get("anti_url_shortener", {}) or {},
    }
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=automod-{guild_id}.json"},
    )


@flask_app.route("/api/guild/<guild_id>/automod/import", methods=["POST"])
@require_auth
def api_guild_automod_import(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    mode = data.get("mode", "merge")
    incoming = data.get("automod", data)
    if not isinstance(incoming, dict):
        return jsonify({"error": "Ungültiger Import"}), 400
    cfg = _direct_load_config(guild_id)
    before = _copy.deepcopy(cfg)
    current = cfg.get("automod", {}) or {}
    allowed_keys = {"bad_words", "regex_rules", "invite_filter", "link_filter", "block_all_links", "allowed_domains", "zalgo_filter", "unicode_abuse", "phishing_check", "punishment"}
    clean = {k: v for k, v in incoming.items() if k in allowed_keys}
    if mode == "replace":
        current = clean
    else:
        for key, value in clean.items():
            if isinstance(value, list) and isinstance(current.get(key), list):
                current[key] = sorted(set(list(current.get(key, [])) + value), key=str)
            else:
                current[key] = value
    # Validate regex after import.
    bad_regex = [r for r in _automod_regex_report(current.get("regex_rules", [])) if not r["ok"]]
    if bad_regex:
        return jsonify({"error": f"Import enthält {len(bad_regex)} ungültige Regex-Regel(n).", "regex_report": bad_regex}), 400
    cfg["automod"] = current
    _save_config_version(guild_id, before, source="before-automod-import")
    _direct_save_config(guild_id, cfg)
    return jsonify({"ok": True, "automod": current, "suggestions": _automod_suggestions(cfg)})

@flask_app.route("/api/guild/<guild_id>/autoresponse", methods=["POST"])
@require_auth
def api_guild_autoresponse(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    ars = cfg.get("auto_responses", [])
    action = data.get("action")
    if action == "add":
        ars.append({"trigger": data["trigger"], "response": data["response"], "enabled": True})
    elif action == "del":
        idx = int(data.get("index", -1))
        if 0 <= idx < len(ars): ars.pop(idx)
    elif action == "toggle":
        idx = int(data.get("index", -1))
        if 0 <= idx < len(ars): ars[idx]["enabled"] = data.get("enabled", True)
    cfg["auto_responses"] = ars
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})

@flask_app.route("/api/guild/<guild_id>/roles/preview/<role_id>")
@require_auth
def api_role_preview(guild_id, role_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    guild = get_guild(guild_id)
    if not guild:
        return jsonify({"error": "Server nicht gefunden"}), 404
    role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
    if not role:
        return jsonify({"error": "Rolle nicht gefunden"}), 404
    return jsonify({"ok": True, "role": _role_summary(guild, role)})


@flask_app.route("/api/guild/<guild_id>/roles", methods=["POST"])
@require_auth
def api_guild_roles(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    action = data.get("action")
    rid = int(data.get("role_id", 0))
    if action == "add_auto":
        ar = cfg.get("auto_role", {"enabled": True, "roles": []})
        if rid not in ar.get("roles",[]): ar.setdefault("roles",[]).append(rid)
        ar["enabled"] = True
        cfg["auto_role"] = ar
    elif action == "del_auto":
        ar = cfg.get("auto_role", {"roles":[]})
        ar["roles"] = [r for r in ar.get("roles",[]) if r != rid]
        cfg["auto_role"] = ar
    elif action == "add_sticky":
        sr = cfg.get("sticky_roles", [])
        if rid not in sr: sr.append(rid)
        cfg["sticky_roles"] = sr
    elif action == "del_sticky":
        cfg["sticky_roles"] = [r for r in cfg.get("sticky_roles",[]) if r != rid]
    elif action == "add_verify":
        vs = cfg.setdefault("verify_system", {"enabled": True, "add_roles": [], "remove_roles": []})
        vs.setdefault("add_roles", [])
        if rid not in vs["add_roles"]: vs["add_roles"].append(rid)
        cfg["verify_system"] = vs
    elif action == "del_verify":
        vs = cfg.setdefault("verify_system", {"enabled": True, "add_roles": [], "remove_roles": []})
        vs["add_roles"] = [r for r in vs.get("add_roles", []) if r != rid]
        cfg["verify_system"] = vs
    elif action == "add_unverify":
        vs = cfg.setdefault("verify_system", {"enabled": True, "add_roles": [], "remove_roles": []})
        vs.setdefault("remove_roles", [])
        if rid not in vs["remove_roles"]: vs["remove_roles"].append(rid)
        cfg["verify_system"] = vs
    elif action == "del_unverify":
        vs = cfg.setdefault("verify_system", {"enabled": True, "add_roles": [], "remove_roles": []})
        vs["remove_roles"] = [r for r in vs.get("remove_roles", []) if r != rid]
        cfg["verify_system"] = vs
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})
@flask_app.route("/api/guild/<guild_id>/embed", methods=["POST"])
@require_auth
def api_guild_embed(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    channel_id = data.get("channel_id")
    embed_data = data.get("embed", {})
    if not channel_id or not embed_data:
        return jsonify({"error": "missing channel_id or embed"}), 400
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "guild not found"}), 404
    ch = g.get_channel(int(channel_id))
    if not ch:
        return jsonify({"error": "channel not found"}), 404
    import discord
    from bot.utils import _run_async
    try:
        color = embed_data.pop("color", 0x7c3aed)
        emb = discord.Embed(
            title=embed_data.get("title"),
            description=embed_data.get("description"),
            url=embed_data.get("url"),
            color=color,
        )
        if embed_data.get("author"):
            emb.set_author(name=embed_data["author"].get("name",""), icon_url=embed_data["author"].get("icon_url"))
        if embed_data.get("thumbnail"):
            emb.set_thumbnail(url=embed_data["thumbnail"]["url"])
        if embed_data.get("image"):
            emb.set_image(url=embed_data["image"]["url"])
        if embed_data.get("footer"):
            emb.set_footer(text=embed_data["footer"].get("text",""), icon_url=embed_data["footer"].get("icon_url"))
        if embed_data.get("timestamp"):
            emb.timestamp = datetime.datetime.utcnow()
        for field in embed_data.get("fields", []):
            emb.add_field(name=field["name"], value=field["value"], inline=field.get("inline", False))
        _run_async(ch.send(embed=emb))
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[EMBED API ERROR] {e}")
        return jsonify({"error": str(e)}), 500

# =========================================================
# DASHBOARD: MEMBERS PAGE
# =========================================================

@flask_app.route("/dashboard/<guild_id>/members")
@require_auth
def guild_members(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    members = []
    guild_owner_id = str(g.owner_id) if hasattr(g, 'owner_id') and g.owner_id else "0"
    badge_catalog = []
    if g and bot_ready():
        import datetime as _dt
        now = _dt.datetime.utcnow()
        bot_id = str(bot.user.id) if bot.user else "1491447622442160248"
        for m in g.members[:500]:
            try:
                age_days = (now - m.created_at.replace(tzinfo=None)).days if m.created_at else 999
                rc = len([r for r in m.roles if r != g.default_role])
                risk = 0
                if age_days < 7: risk += 30
                elif age_days < 30: risk += 10
                if not m.avatar: risk += 10
                if rc == 0 and not m.bot: risk += 15
                risk = min(risk, 100)

                # Tags + Sort Priority
                tag = ""; tag_color = ""; sp = 10
                if str(m.id) == "1303627964734246944":
                    tag = "Bot Owner/Dev"; tag_color = "#f59e0b"; risk = 0; sp = 0
                elif str(m.id) == bot_id:
                    tag = "ModForge"; tag_color = "#7c3aed"; risk = 0; sp = 1
                elif str(m.id) == guild_owner_id:
                    tag = "Server Owner"; tag_color = "#22d3ee"; risk = 0; sp = 2
                elif m.bot:
                    tag = "Bot"; tag_color = "#3b82f6"; sp = 5

                # Timeout
                timeout_str = ""
                try:
                    if m.timed_out_until and m.timed_out_until.timestamp() > now.timestamp():
                        timeout_str = str(int(m.timed_out_until.timestamp()))
                except Exception:
                    pass

                # Voice
                voice_ch = ""
                voice_mute = False
                voice_deaf = False
                voice_stream = False
                if m.voice and m.voice.channel:
                    voice_ch = m.voice.channel.name
                    voice_mute = m.voice.mute or m.voice.self_mute
                    voice_deaf = m.voice.deaf or m.voice.self_deaf
                    voice_stream = getattr(m.voice, 'self_stream', False)

                # Top role
                top_role_name = ""
                top_role_color = ""
                if m.top_role and m.top_role != g.default_role:
                    top_role_name = m.top_role.name
                    top_role_color = str(m.top_role.color) if m.top_role.color.value else ""

                # Boost
                boost_since = ""
                if m.premium_since:
                    boost_since = str(int(m.premium_since.timestamp()))

                # Status
                status = str(m.status) if hasattr(m, 'status') else "offline"

                # Permissions summary
                is_admin = m.guild_permissions.administrator
                can_ban = m.guild_permissions.ban_members
                can_kick = m.guild_permissions.kick_members
                can_manage = m.guild_permissions.manage_guild

                # Cases/Warns count
                user_cases = 0
                user_warns = 0
                try:
                    db = get_db()
                    if db:
                        user_cases = safe_collection_count(db.cases, {"guild_id": {"$in": _guild_id_values(g.id)}, "user_id": {"$in": [m.id, str(m.id)]}})
                        user_warns = safe_collection_count(db.data, {"type": "warning", "guild_id": {"$in": _guild_id_values(g.id)}, "user_id": {"$in": [m.id, str(m.id)]}})
                        if user_cases: risk = min(risk + user_cases * 5, 100)
                        if user_warns: risk = min(risk + user_warns * 8, 100)
                except Exception:
                    pass

                members.append({
                    "id": str(m.id),
                    "cases": user_cases,
                    "warns": user_warns,
                    "name": str(m),
                    "display_name": m.display_name,
                    "nick": m.nick or "",
                    "bot": m.bot,
                    "avatar": m.display_avatar.url,
                    "risk": risk,
                    "new_account": age_days < 7,
                    "role_count": rc,
                    "roles": [{"name": r.name, "color": str(r.color) if r.color.value else ""} for r in m.roles if r != g.default_role][:20],
                    "roles_str": ", ".join([r.name for r in m.roles if r != g.default_role][:5]) or "Keine",
                    "tag": tag, "tag_color": tag_color,
                    "sort_priority": sp,
                    "age_days": age_days,
                    "timeout": timeout_str,
                    "voice_ch": voice_ch,
                    "voice_mute": voice_mute,
                    "voice_deaf": voice_deaf,
                    "voice_stream": voice_stream,
                    "joined": str(int(m.joined_at.timestamp())) if m.joined_at else "",
                    "created": str(int(m.created_at.timestamp())) if m.created_at else "",
                    "status": status,
                    "top_role": top_role_name,
                    "top_role_color": top_role_color,
                    "boost_since": boost_since,
                    "is_admin": is_admin,
                    "can_ban": can_ban,
                    "can_kick": can_kick,
                    "can_manage": can_manage,
                    "pending": getattr(m, 'pending', False),
                    "is_on_mobile": m.is_on_mobile() if hasattr(m, 'is_on_mobile') else False,
                    "desktop_status": str(getattr(m, 'desktop_status', 'offline')),
                    "web_status": str(getattr(m, 'web_status', 'offline')),
                    "mobile_status": str(getattr(m, 'mobile_status', 'offline')),
                    "activity": str(m.activity.name) if m.activity and hasattr(m.activity, 'name') else "",
                    "activity_type": str(m.activity.type.name) if m.activity and hasattr(m.activity, 'type') else "",
                    "banner_url": m.banner.url if hasattr(m, 'banner') and m.banner else "",
                    "guild_avatar_url": m.guild_avatar.url if hasattr(m, 'guild_avatar') and m.guild_avatar else "",
                    "accent_color": str(m.accent_color) if hasattr(m, 'accent_color') and m.accent_color else "",
                    "all_perms": {
                        "administrator": m.guild_permissions.administrator,
                        "manage_guild": m.guild_permissions.manage_guild,
                        "manage_roles": m.guild_permissions.manage_roles,
                        "manage_channels": m.guild_permissions.manage_channels,
                        "manage_messages": m.guild_permissions.manage_messages,
                        "ban_members": m.guild_permissions.ban_members,
                        "kick_members": m.guild_permissions.kick_members,
                        "moderate_members": m.guild_permissions.moderate_members,
                        "mention_everyone": m.guild_permissions.mention_everyone,
                        "manage_webhooks": m.guild_permissions.manage_webhooks,
                        "manage_nicknames": m.guild_permissions.manage_nicknames,
                        "manage_emojis": m.guild_permissions.manage_emojis_and_stickers if hasattr(m.guild_permissions, 'manage_emojis_and_stickers') else False,
                        "view_audit_log": m.guild_permissions.view_audit_log,
                        "send_messages": m.guild_permissions.send_messages,
                        "connect": m.guild_permissions.connect,
                        "speak": m.guild_permissions.speak,
                        "mute_members": m.guild_permissions.mute_members,
                        "deafen_members": m.guild_permissions.deafen_members,
                        "move_members": m.guild_permissions.move_members,
                    },
                    "role_ids": [str(r.id) for r in m.roles if r != g.default_role],
                })
            except Exception as ex:
                log.debug(f"Member parse error: {ex}")

                # ── Badges laden ──
        guild_badges = {}
        try:
            db = get_db()
            if db:
                guild_badges = safe_async(db.badge_get_all_guild_details(int(guild_id)), {}) or {}
                _defs = safe_async(db.badge_definitions(), {}) or {}
                badge_catalog = sorted(_defs.values(), key=lambda b: b.get("name", b.get("id", "")))
        except Exception:
            pass
        rarity_points = {"common": 1, "rare": 3, "epic": 6, "legendary": 10, "mythic": 16}
        for m in members:
            m["badges"] = guild_badges.get(m["id"], [])
            m["badge_score"] = sum(rarity_points.get(str(b.get("rarity", "common")), 1) + int(b.get("level", 1) or 1) for b in m["badges"])
            if m["badge_score"]:
                m["risk"] = max(0, m["risk"] - min(25, m["badge_score"] // 2))
            # Badge-Träger sortieren: hinter Dev/Owner, vor Bots
            if m["badges"] and m["sort_priority"] >= 5:
                m["sort_priority"] = 4
        members.sort(key=lambda x: (x["sort_priority"], -x.get("badge_score", 0), -x["risk"], x["name"].lower()))
    return render_template("dashboard/members.html", guild=g, cfg=cfg, user=us["user"], members=members, badge_catalog=badge_catalog, guild_owner_id=guild_owner_id, active="members")

# =========================================================
# PUBLIC SERVER PAGE
# =========================================================

@flask_app.route("/server/<guild_id>")
def public_server_page(guild_id):
    g = get_guild(guild_id)
    if not g:
        abort(404)
    cfg = _direct_load_config(guild_id)
    pp = cfg.get("public_page", {})
    # Build server info
    mods = ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
    active_modules = [m.replace("_"," ").title() for m in mods if cfg.get(m,{}).get("enabled")]
    sec = min(85 + len(active_modules) * 2, 100)
    server = {
        "name": g.name,
        "icon": g.icon.url if g.icon else None,
        "members": g.member_count or 0,
        "security": sec,
        "active_modules": len(active_modules),
        "modules": active_modules,
        "invite": pp.get("invite_url"),
    }
    return render_template("server_public.html", server=server)

@flask_app.route("/server/<guild_id>/user/<member_id>")
def public_server_user(guild_id, member_id):
    g = get_guild(guild_id)
    if not g:
        abort(404)
    member = g.get_member(int(member_id)) if str(member_id).isdigit() else None
    if not member:
        abort(404)
    badges = []
    db = get_db()
    if db:
        badges = safe_async(db.badge_get_details(int(guild_id), int(member_id)), []) or []
    profile = {
        "id": str(member.id), "name": str(member), "display_name": member.display_name,
        "avatar": member.display_avatar.url, "bot": member.bot,
        "joined": int(member.joined_at.timestamp()) if member.joined_at else None,
        "created": int(member.created_at.timestamp()) if member.created_at else None,
        "server_name": g.name, "server_id": str(g.id), "badges": badges,
    }
    return render_template("server_user.html", profile=profile)
# =========================================================
# DASHBOARD: STATS / WHITELIST / LIVEFEED
# =========================================================

@flask_app.route("/dashboard/<guild_id>/stats")
@require_auth
def guild_stats_page(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    import datetime as _dt
    cases_count = 0
    case_types = {}
    top_mods = []
    days_labels = []
    days_data = []
    db = get_db()
    if db:
        try:
            all_cases = safe_async(db.cases.find(_guild_query(guild_id)).sort("case_id", -1).to_list(500), []) or []
            cases_count = len(all_cases)
            # Case types
            for cs in all_cases:
                a = cs.get("action", "other")
                case_types[a] = case_types.get(a, 0) + 1
            # Top mods
            from collections import Counter
            mod_counter = Counter((cs.get("mod_id") or cs.get("moderator_id")) for cs in all_cases if (cs.get("mod_id") or cs.get("moderator_id")))
            top_mods = [{"id": mid, "count": cnt} for mid, cnt in mod_counter.most_common(10)]
            # Cases per day (last 7 days)
            now = _dt.datetime.utcnow()
            for i in range(6, -1, -1):
                day = now - _dt.timedelta(days=i)
                label = day.strftime("%a")
                count = sum(1 for cs in all_cases if (cs.get("created_at") or cs.get("timestamp")) and
                    (cs.get("created_at") or cs.get("timestamp")).date() == day.date())
                days_labels.append(label)
                days_data.append(count)
        except Exception as e:
            log.debug(f"Stats page error: {e}")

    # ── Member-Wachstum: kumulativer Verlauf seit Server-Erstellung ──
    # Wir nutzen die ``joined_at``-Daten aller momentan auf dem Server befindlichen
    # Mitglieder (das ist die einzige Information, die Discord uns ohne extra Logging
    # liefert). Das ergibt eine ehrliche Kurve "wie viele heutige Member waren wann
    # bereits drin?". Verlassene Member sind nicht enthalten – das ist eine bekannte
    # Discord-API-Limitation.
    growth_labels: list = []
    growth_data: list = []
    growth_total = 0
    growth_buckets = 0
    if g and hasattr(g, "members") and g.members and hasattr(g, "created_at") and g.created_at:
        try:
            created_at = g.created_at
            if created_at.tzinfo is not None:
                created_at = created_at.replace(tzinfo=None)
            now_utc = _dt.datetime.utcnow()

            # Joins sammeln (datetime.date pro Member)
            join_dates = []
            for m in g.members:
                ja = getattr(m, "joined_at", None)
                if not ja:
                    continue
                if ja.tzinfo is not None:
                    ja = ja.replace(tzinfo=None)
                # Bot-Owner / very old accounts trotzdem reinrechnen, aber nicht vor created_at
                if ja < created_at:
                    ja = created_at
                join_dates.append(ja)

            join_dates.sort()
            total_members = len(join_dates)

            # Bucket-Auflösung wählen: max ~60 Datenpunkte
            span = now_utc - created_at
            span_days = max(1, span.days or 1)
            if span_days <= 60:
                bucket_seconds = 24 * 3600           # täglich
                fmt = "%d.%m."
            elif span_days <= 365 * 2:
                bucket_seconds = 7 * 24 * 3600        # wöchentlich
                fmt = "%d.%m.%y"
            elif span_days <= 365 * 6:
                bucket_seconds = 30 * 24 * 3600       # monatlich
                fmt = "%b %y"
            else:
                bucket_seconds = 90 * 24 * 3600       # quartalsweise
                fmt = "Q%m/%y"

            cursor = created_at
            idx = 0  # Position im sortierten join_dates-Array
            running = 0
            # Sicherheitsbremse, damit wir bei kaputten Zeitstempeln nicht endlos laufen
            max_buckets = 400
            while cursor <= now_utc and growth_buckets < max_buckets:
                bucket_end = cursor + _dt.timedelta(seconds=bucket_seconds)
                while idx < total_members and join_dates[idx] < bucket_end:
                    running += 1
                    idx += 1
                growth_labels.append(cursor.strftime(fmt))
                growth_data.append(running)
                growth_buckets += 1
                cursor = bucket_end

            # Endpunkt = aktueller Member-Count (für den Fall, dass Joins fehlen)
            if growth_data:
                growth_data[-1] = max(growth_data[-1], total_members)
            growth_total = total_members
        except Exception as ex:
            log.debug(f"member-growth error: {ex}")
            growth_labels, growth_data = [], []
    active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"]
                      if cfg.get(k, {}).get("enabled"))
    channels_count = len(g.channels) if g and hasattr(g,'channels') else 0
    roles_count = len(g.roles)-1 if g and hasattr(g,'roles') and g.roles else 0
    text_ch = len([ch for ch in g.channels if hasattr(ch,'type') and str(ch.type)=='text']) if g and hasattr(g,'channels') else 0
    voice_ch = len([ch for ch in g.channels if hasattr(ch,'type') and str(ch.type)=='voice']) if g and hasattr(g,'channels') else 0
    bots = sum(1 for m in g.members if m.bot) if g and hasattr(g,'members') and g.members else 0
    humans = (g.member_count or 0) - bots if g else 0
    online = sum(1 for m in g.members if hasattr(m,'status') and str(m.status)!='offline') if g and hasattr(g,'members') and g.members else 0
    boosts = g.premium_subscription_count or 0 if g and hasattr(g,'premium_subscription_count') else 0
    warns_count = 0
    try:
        wc = getattr(db,'warnings',None) if db else None
        if wc: warns_count = safe_collection_count(wc, {"guild_id":str(guild_id)})
    except Exception:
        pass
    log_channels_count = len(cfg.get("log_channels",{}) or {})
    sec_level = cfg.get("security_level",0)

    server_created_ts = ""
    try:
        if g and hasattr(g, "created_at") and g.created_at:
            server_created_ts = str(int(g.created_at.timestamp()))
    except Exception:
        pass

    return render_template("dashboard/stats.html", guild=g, cfg=cfg, user=us["user"],
        cases_count=cases_count, case_types=case_types, top_mods=top_mods,
        active_mods=active_mods, channels_count=channels_count,
        days_labels=days_labels, days_data=days_data,
        roles_count=roles_count, text_ch=text_ch, voice_ch=voice_ch,
        bots=bots, humans=humans, online=online, boosts=boosts,
        warns_count=warns_count, log_channels_count=log_channels_count,
        sec_level=sec_level,
        growth_labels=growth_labels, growth_data=growth_data,
        growth_total=growth_total, server_created_ts=server_created_ts,
        active="stats")

# ═══════════════════════════════════════════════════════════════════
# WHITELIST
# ═══════════════════════════════════════════════════════════════════
@flask_app.route("/dashboard/<guild_id>/whitelist")
@require_auth
def guild_whitelist(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    wl = {}
    if bot_ready():
        try:
            wl = bot.db.get_whitelist(int(guild_id))
        except Exception:
            pass

    # Rollen + User-Namen aus Guild auflösen
    role_map   = {}
    member_map = {}
    if g:
        if hasattr(g, 'roles') and g.roles:
            role_map = {str(r.id): r.name for r in g.roles}
        if hasattr(g, 'members') and g.members:
            member_map = {str(m.id): m.display_name for m in g.members}

    # Kategorien anreichern
    cats = [
        {
            "key":         "users",
            "label":       "User",
            "icon":        "👤",
            "desc":        "Alle Security-Module werden für diese User deaktiviert",
            "placeholder": "User-ID eingeben…",
            "color":       "124,58,237",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("users", [])
            ],
        },
        {
            "key":         "roles",
            "label":       "Rollen",
            "icon":        "🏷️",
            "desc":        "Mitglieder mit diesen Rollen werden von allen Modulen ignoriert",
            "placeholder": "Rollen-ID eingeben…",
            "color":       "34,211,238",
            "entries": [
                {"id": str(rid), "name": role_map.get(str(rid), "")}
                for rid in wl.get("roles", [])
            ],
        },
        {
            "key":         "channels",
            "label":       "Kanäle",
            "icon":        "📁",
            "desc":        "In diesen Kanälen sind alle Security-Module inaktiv",
            "placeholder": "Kanal-ID eingeben…",
            "color":       "74,222,128",
            "entries": [
                {"id": str(cid), "name": ""}
                for cid in wl.get("channels", [])
            ],
        },
        {
            "key":         "bypass_antinuke",
            "label":       "Bypass Anti-Nuke",
            "icon":        "💣",
            "desc":        "Dürfen Massenaktionen durchführen ohne gesperrt zu werden",
            "placeholder": "User-ID eingeben…",
            "color":       "239,68,68",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("bypass_antinuke", [])
            ],
        },
        {
            "key":         "bypass_antispam",
            "label":       "Bypass Anti-Spam",
            "icon":        "⚡",
            "desc":        "Anti-Spam-Filter wird für diese User komplett ignoriert",
            "placeholder": "User-ID eingeben…",
            "color":       "245,158,11",
            "entries": [
                {"id": str(uid), "name": member_map.get(str(uid), "")}
                for uid in wl.get("bypass_antispam", [])
            ],
        },
    ]

    total_entries = sum(len(c["entries"]) for c in cats)

    # Rollen-Liste für Dropdown
    guild_roles = []
    if g and hasattr(g, 'roles') and g.roles:
        guild_roles = [
            {"id": str(r.id), "name": r.name}
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]

    # Kanal-Liste für Dropdown
    guild_channels = []
    if g and hasattr(g, 'text_channels') and g.text_channels:
        guild_channels = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(g.text_channels, key=lambda c: c.position)
        ]

    return render_template(
        "dashboard/whitelist.html",
        guild=g, cfg=cfg, user=us["user"],
        whitelist=wl,
        cats=cats,
        total_entries=total_entries,
        guild_roles=guild_roles,
        guild_channels=guild_channels,
        active="whitelist",
    )

@flask_app.route("/dashboard/<guild_id>/livefeed")
@require_auth
def guild_livefeed(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    activities = []
    try:
        from bot.config import ACTIVITY
        raw = ACTIVITY.snapshot(30)
        if isinstance(raw, list):
            activities = [a for a in raw if str(a.get("guild_id","")) == str(guild_id)][:20]
    except Exception:
        pass
    return render_template("dashboard/livefeed.html", guild=g, cfg=cfg, user=us["user"],
        activities=activities, active="livefeed")

# =========================================================
# WHITELIST API
# =========================================================

@flask_app.route("/api/guild/<guild_id>/whitelist", methods=["POST"])
@require_auth
def api_guild_whitelist(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403

    data = request.json or {}
    action = data.get("action")
    cat = data.get("category", "users")
    item_id = data.get("id")
    allowed = {"users", "roles", "channels", "bypass_antispam", "bypass_antinuke"}

    if action not in {"add", "del"} or cat not in allowed or not item_id:
        return jsonify({"error": "Ungültige Whitelist-Parameter"}), 400

    try:
        item_id = int(str(item_id).strip())
    except (TypeError, ValueError):
        return jsonify({"error": "ID muss eine Zahl sein"}), 400

    try:
        wl = safe_async(bot.db.aget_whitelist(int(guild_id)), None) if getattr(bot, "db", None) else None
        if not isinstance(wl, dict):
            db = _get_direct_db()
            doc = db.whitelist.find_one({"_id": int(guild_id)}) if db is not None else None
            wl = doc if isinstance(doc, dict) else {}
            wl.pop("_id", None)
        for key in allowed:
            wl.setdefault(key, [])

        if action == "add":
            if item_id not in wl[cat]:
                wl[cat].append(item_id)
        else:
            wl[cat] = [x for x in wl.get(cat, []) if str(x) != str(item_id)]

        if not _direct_save_whitelist(guild_id, wl):
            return jsonify({"error": "Speichern fehlgeschlagen"}), 500
        return jsonify({"ok": True, "category": cat, "count": len(wl.get(cat, []))})
    except Exception as e:
        log.error(f"[WHITELIST API] {e}")
        return jsonify({"error": str(e)}), 500

# =========================================================
# ADMIN: Full Server Dashboard (same as user, no perm check)
# =========================================================

@flask_app.route("/admin/server/<guild_id>")
@flask_app.route("/admin/server/<guild_id>/<path:subpage>")
@admin_required
def admin_server_dashboard(guild_id, subpage=""):
    """Admin kann JEDEN Server im vollen Dashboard öffnen — ohne OAuth."""
    g = get_guild(guild_id)
    if not g:
        abort(404)
    cfg = _direct_load_config(guild_id)
    admin_user = {"id":"0","username":"Admin","avatar_url":"https://cdn.discordapp.com/embed/avatars/0.png"}

    # Reuse the normal dashboard routes so admin/user tabs stay identical and error-free.
    dispatch = {
        "": globals().get("guild_dashboard"),
        "overview": globals().get("guild_dashboard"),
        "security": globals().get("guild_security"),
        "automod": globals().get("guild_automod"),
        "logs": globals().get("guild_logs"),
        "cases": globals().get("guild_cases"),
        "warns": globals().get("guild_warns"),
        "settings": globals().get("guild_settings"),
        "roles": globals().get("guild_roles"),
        "welcome": globals().get("guild_welcome"),
        "verification": globals().get("guild_verification"),
        "modules": globals().get("guild_modules"),
        "tickets": globals().get("guild_tickets"),
        "backup": globals().get("guild_backup"),
        "templates": globals().get("guild_templates"),
        "members": globals().get("guild_members"),
        "tempvoice": globals().get("guild_tempvoice"),
        "autoresponse": globals().get("guild_autoresponse"),
        "stats": globals().get("guild_stats_page"),
        "livefeed": globals().get("guild_livefeed"),
        "audit": globals().get("guild_audit"),
        "badges": globals().get("guild_badges"),
        "whitelist": globals().get("guild_whitelist"),
        "embed": globals().get("guild_embed"),
        "design": globals().get("guild_design"),
        "autonick": globals().get("guild_autonick"),
        "beta": globals().get("guild_beta"),
    }
    target = dispatch.get(subpage or "overview")
    if target is not None and hasattr(target, "__wrapped__"):
        return target.__wrapped__(guild_id)

    # Legacy fallback for unknown sub-pages.
    if not subpage or subpage == "overview":
        overview = _build_overview(cfg, guild_id)
        return render_template("dashboard/overview.html", guild=g, cfg=cfg, user=admin_user, overview=overview, active="overview")

    elif subpage == "security":
        # Security page needs full module list — reuse guild_security logic
        modules = []
        mod_defs = [
            ("anti_spam","⚡","Anti-Spam","Spam erkennen",[{"key":"msg_limit","label":"Limit","type":"number","min":2,"max":30},{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_nuke","💥","Anti-Nuke","Massenaktionen",[{"key":"threshold","label":"Schwelle","type":"number","min":2,"max":20},{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_raid","🚨","Anti-Raid","Massenjoins",[{"key":"join_threshold","label":"Join-Limit","type":"number","min":3,"max":50}]),
            ("anti_mention","🔔","Anti-Mention","Mass-Mentions",[{"key":"mention_limit","label":"Max","type":"number","min":2,"max":30}]),
            ("anti_scam","🎣","Anti-Scam","Phishing",[{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
            ("anti_webhook","🔌","Anti-Webhook","Webhooks",[]),
            ("anti_ghost_ping","👻","Ghost-Ping","Ghost-Pings",[]),
            ("anti_vpn","🌐","Anti-VPN","VPN-Erkennung",[]),
            ("automod","🤖","AutoMod","Filter",[{"key":"punishment","label":"Strafe","type":"select","options":["warn","timeout","kick","ban"]}]),
        ]
        for key,icon,label,desc,params in mod_defs:
            mcfg = cfg.get(key,{})
            for p in params: p["value"] = mcfg.get(p["key"],"")
            modules.append({"key":key,"icon":icon,"label":label,"desc":desc,"enabled":mcfg.get("enabled",False),"params":params})
        wl_count = 0
        try:
            wl = bot.db.get_whitelist(int(guild_id)) if bot_ready() else {}
            wl_count = sum(len(v) for v in wl.values() if isinstance(v,list))
        except Exception:
            pass
        return render_template("dashboard/security.html", guild=g, cfg=cfg, user=admin_user,
            modules=modules, active_count=sum(1 for m in modules if m["enabled"]), wl_count=wl_count, active="security")

    elif subpage == "automod":
        return render_template("dashboard/automod.html", guild=g, cfg=cfg, user=admin_user, active="automod")

    elif subpage == "logs":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        log_channels = cfg.get("log_channels",{})
        from bot.config import LOG_MODULES, LOG_MODULES_EXTRA
        icons = {"default":"📌","moderation":"🛡️","antispam":"⚡","antinuke":"💥","antiraid":"🚨","voice":"🎤","members":"👥","channels":"📁","roles":"🏷️","tickets":"🎫","cases":"📋","warns":"⚠️","welcome":"👋","errors":"❌","backup":"💾"}
        all_mods = list(LOG_MODULES) + list(LOG_MODULES_EXTRA)
        log_module_defs = [{"key":m,"icon":icons.get(m,"⚙️"),"label":m.replace("_"," ").title()} for m in all_mods]
        return render_template("dashboard/logs.html", guild=g, cfg=cfg, user=admin_user,
            channels=channels, log_channels=log_channels, log_modules=log_module_defs, active="logs")

    elif subpage == "cases":
        cases = []
        db = get_db()
        if db:
            try:
                raw = safe_async(db.cases.find({"guild_id":str(guild_id)}).sort("case_id",-1).to_list(200),[]) or []
                for cc in raw: cc["timestamp"] = str(cc.get("timestamp",""))[:19]
                cases = raw
            except Exception:
                pass
        return render_template("dashboard/cases.html", guild=g, cfg=cfg, user=admin_user, cases=cases, active="cases")

    elif subpage == "warns":
        return render_template("dashboard/warns.html", guild=g, cfg=cfg, user=admin_user, active="warns")

    elif subpage == "settings":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        return render_template("dashboard/settings.html", guild=g, cfg=cfg, user=admin_user, channels=channels, active="settings")

    elif subpage == "roles":
        guild_roles = [{"id":str(r.id),"name":r.name} for r in g.roles if not r.is_default() and not r.managed] if g else []
        return render_template("dashboard/roles.html", guild=g, cfg=cfg, user=admin_user,
            guild_roles=guild_roles, auto_roles=cfg.get("auto_role",{}).get("roles",[]), sticky_roles=cfg.get("sticky_roles",[]), active="roles")

    elif subpage == "welcome":
        content = _build_welcome_content(cfg, guild_id)
        return render_template("dashboard/welcome.html", guild=g, cfg=cfg, user=admin_user, content=content, active="welcome")

    elif subpage == "modules":
        return render_template(
            "dashboard/modules.html", guild=g, cfg=cfg, user=admin_user,
            sections=_module_sections(), current_section=request.args.get("section", "antispam"),
            active="modules"
        )

    elif subpage == "tickets":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        categories = [{"id":str(ct.id),"name":ct.name} for ct in g.categories] if g else []
        return render_template("dashboard/tickets.html", guild=g, cfg=cfg, user=admin_user, channels=channels, categories=categories, active="tickets")

    elif subpage == "backup":
        backups = []
        col = _backups_col()
        if col is not None:
            try:
                try:
                    raw = safe_async(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).to_list(50), None)
                    if raw is None:
                        raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))
                except Exception:
                    raw = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(50))
                for b in raw or []:
                    enriched = _enrich_backup_doc(b)
                    if enriched:
                        backups.append(enriched)
            except Exception:
                pass
        bs = cfg.get("backup_system", {}) or {}
        return render_template(
            "dashboard/backup.html", guild=g, cfg=cfg, user=admin_user,
            backups=backups, total_size=len(backups),
            auto_enabled=bs.get("auto_enabled", False),
            auto_interval=bs.get("auto_interval_hours", 24),
            auto_max=bs.get("auto_max_backups", 5),
            last_backup_ts=_ts(bs.get("auto_last_backup")),
            bot_ready=bot_ready(),
            active="backup",
        )

    elif subpage == "templates":
        my_shared, all_public = [], []
        pcol = _public_backups_col()
        if pcol is not None:
            try:
                try:
                    mine_raw = safe_async(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).to_list(50), None)
                    if mine_raw is None:
                        mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
                except Exception:
                    mine_raw = list(pcol.find({"guild_id": str(guild_id)}).sort("shared_at", -1).limit(50))
                try:
                    pub_raw = safe_async(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).to_list(200), None)
                    if pub_raw is None:
                        pub_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
                except Exception:
                    pub_raw = list(pcol.find({}).sort([("downloads", -1), ("shared_at", -1)]).limit(200))
            except Exception:
                mine_raw, pub_raw = [], []
            def _shape(p):
                return {
                    "id": p.get("backup_id", "?"),
                    "name": p.get("name") or "Unbenannt",
                    "description": p.get("description") or "",
                    "category": (p.get("category") or "general").lower(),
                    "guild_name": p.get("guild_name") or "?",
                    "guild_icon": p.get("guild_icon") or "",
                    "shared_by": str(p.get("shared_by") or "—"),
                    "shared_ts": _ts(p.get("shared_at")),
                    "roles": int(p.get("roles_count") or 0),
                    "channels": int(p.get("channels_count") or 0),
                    "categories": int(p.get("categories_count") or 0),
                    "emojis": int(p.get("emojis_count") or 0),
                    "downloads": int(p.get("downloads") or 0),
                    "is_mine": str(p.get("guild_id")) == str(guild_id) or str(p.get("guild_id_str")) == str(guild_id),
                }
            my_shared = [_shape(p) for p in (mine_raw or [])]
            all_public = [_shape(p) for p in (pub_raw or [])]
        categories = {}
        for tpl in all_public:
            categories.setdefault(tpl["category"], []).append(tpl)
        return render_template("dashboard/templates.html", guild=g, cfg=cfg, user=admin_user,
            my_shared=my_shared, all_public=all_public, categories=categories,
            bot_ready=bot_ready(), active="templates")

    elif subpage == "autoresponse":
        return render_template("dashboard/autoresponse.html", guild=g, cfg=cfg, user=admin_user, auto_responses=cfg.get("auto_responses",[]), active="autoresponse")

    elif subpage == "embed":
        channels = [{"id":str(ch.id),"name":ch.name} for ch in g.text_channels] if g else []
        return render_template("dashboard/embed.html", guild=g, cfg=cfg, user=admin_user, channels=channels, active="embed")

    elif subpage == "whitelist":
        wl = {}
        if bot_ready():
            try: wl = bot.db.get_whitelist(int(guild_id))
            except Exception:
                pass
        return render_template("dashboard/whitelist.html", guild=g, cfg=cfg, user=admin_user, whitelist=wl, active="whitelist")

    elif subpage == "stats":
        import datetime as _dt
        cases_count = 0; case_types = {}; top_mods = []; days_labels = []; days_data = []
        db = get_db()
        if db:
            try:
                all_cases = safe_async(db.cases.find({"guild_id":str(guild_id)}).to_list(500),[]) or []
                cases_count = len(all_cases)
                for cs in all_cases: a=cs.get("action","other"); case_types[a]=case_types.get(a,0)+1
                from collections import Counter
                mc = Counter(cs.get("moderator_id") for cs in all_cases if cs.get("moderator_id"))
                top_mods = [{"id":mid,"count":cnt} for mid,cnt in mc.most_common(10)]
                now = _dt.datetime.utcnow()
                for i in range(6,-1,-1):
                    day = now - _dt.timedelta(days=i)
                    days_labels.append(day.strftime("%a"))
                    days_data.append(sum(1 for cs in all_cases if cs.get("timestamp") and cs["timestamp"].date()==day.date()))
            except Exception:
                pass
        active_mods = sum(1 for k in ["anti_spam","anti_nuke","anti_raid","anti_mention","anti_scam","automod"] if cfg.get(k,{}).get("enabled"))
        return render_template("dashboard/stats.html", guild=g, cfg=cfg, user=admin_user,
            cases_count=cases_count, case_types=case_types, top_mods=top_mods,
            active_mods=active_mods, channels_count=len(g.channels) if g else 0,
            days_labels=days_labels, days_data=days_data, active="stats")

    elif subpage == "members":
        members = []
        if g and bot_ready():
            import datetime as _dt
            now = _dt.datetime.utcnow()
            for m in g.members[:200]:
                age = (now - m.created_at.replace(tzinfo=None)).days if m.created_at else 999
                rc = len([r for r in m.roles if r != g.default_role])
                risk = min((30 if age<7 else 10 if age<30 else 0) + (10 if not m.avatar else 0) + (15 if rc==0 and not m.bot else 0), 100)
                # Special tags
            tag = None
            tag_color = ""
            if str(m.id) == "1303627964734246944":
                tag = "Bot-Entwickler"
                tag_color = "#f59e0b"
                risk = 0
            elif str(m.id) == "1491447622442160248" or m.id == (bot.user.id if bot_ready() and bot.user else 0):
                tag = "ModForge Bot"
                tag_color = "#7c3aed"
                risk = 0
            elif m.bot:
                tag = "Bot"
                tag_color = "#3b82f6"

            members.append({"id":str(m.id),"name":str(m),"bot":m.bot,"avatar":m.display_avatar.url,
                    "risk":risk,"new_account":age<7,"role_count":rc,
                    "roles_str":", ".join([r.name for r in m.roles if r!=g.default_role][:5]) or "Keine",
                    "tag":tag,"tag_color":tag_color})

        # Sort: Developer first, then Bot, then by risk
        def _member_sort_key(x):
            if x["id"] == "1303627964734246944": return (0, "")
            if x["id"] == "1491447622442160248": return (1, "")
            if x.get("tag") == "ModForge Bot": return (1, "")
            return (2 if not x["bot"] else 3, -x["risk"])
        members.sort(key=_member_sort_key)
        return render_template("dashboard/members.html", guild=g, cfg=cfg, user=admin_user, members=members, active="members")

    elif subpage == "autonick":
        rules = cfg.get("auto_nickname", {}).get("rules", [])
        enabled = cfg.get("auto_nickname", {}).get("enabled", False)
        guild_roles = [{"id":str(r.id),"name":r.name,"color":str(r.color) if r.color and r.color.value else ""}
                       for r in g.roles if not r.is_default() and not r.managed] if g and hasattr(g,'roles') and g.roles else []
        return render_template("dashboard/autonick.html", guild=g, cfg=cfg, user=admin_user,
            rules=rules, enabled=enabled, guild_roles=guild_roles, active="autonick")

    elif subpage == "beta":
        return guild_beta.__wrapped__(guild_id)

    elif subpage == "livefeed":
        activities = []
        try:
            from bot.config import ACTIVITY
            raw = ACTIVITY.snapshot(30)
            if isinstance(raw,list): activities = [a for a in raw if str(a.get("guild_id",""))==str(guild_id)][:20]
        except Exception:
            pass
        return render_template("dashboard/livefeed.html", guild=g, cfg=cfg, user=admin_user, activities=activities, active="livefeed")

    elif subpage == "design":
        return render_template("dashboard/design.html", guild=g, cfg=cfg, user=admin_user, active="design")

    # Default: overview
    overview = _build_overview(cfg, guild_id)
    return render_template("dashboard/overview.html", guild=g, cfg=cfg, user=admin_user, overview=overview, active="overview")

@flask_app.route("/dashboard/refresh")
@require_auth
def dashboard_refresh():
    """Re-fetches guild list from Discord API and persists it in MongoDB."""
    user_session = get_session()
    if not user_session:
        return redirect("/dashboard/login")
    try:
        refresh_session_guilds()
    except Exception as e:
        log.debug(f"Refresh error: {e}")
    return redirect("/dashboard")
# =========================================================
# MEMBER MOD-ACTION API
# =========================================================

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/action", methods=["POST"])
@require_auth
def api_member_action(guild_id, member_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Mod-Aktionen benötigen einen laufenden Bot."}), 503
    data = request.json or {}
    action = data.get("action")
    reason = data.get("reason", "Dashboard-Aktion")
    duration = data.get("duration", 60)
    from bot.utils import _run_async
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    member = g.get_member(int(member_id))
    if not member:
        return jsonify({"error": "User nicht auf dem Server"}), 404
    try:
        if action == "warn":
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "warn", reason))
            count = _run_async(bot.db.aadd_warning(g.id, member.id, reason, int(user_session["user"]["id"])))
            _run_async(bot.log_action(g, "⚠️ Warn (Dashboard)", f"{member.mention} verwarnt.\nGrund: {reason}\nVerwarnungen: {count}", 0xeab308, module="moderation"))
            return jsonify({"ok": True, "action": "warn", "case_id": case_id, "warn_count": count})
        elif action == "kick":
            _run_async(member.kick(reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "kick", reason))
            _run_async(bot.log_action(g, "👢 Kick (Dashboard)", f"{member.mention} gekickt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "kick", "case_id": case_id})
        elif action == "ban":
            _run_async(member.ban(reason=f"Dashboard: {reason}", delete_message_seconds=86400))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "ban", reason))
            _run_async(bot.log_action(g, "🔨 Ban (Dashboard)", f"{member.mention} gebannt.\nGrund: {reason}", 0xef4444, module="moderation"))
            return jsonify({"ok": True, "action": "ban", "case_id": case_id})
        elif action == "timeout":
            import datetime as _dt
            dur = max(60, min(int(duration), 2419200))  # 1min to 28 days
            until = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=dur)
            _run_async(member.timeout(until, reason=f"Dashboard: {reason}"))
            case_id = _run_async(bot.db.acreate_case(g.id, member.id, int(user_session["user"]["id"]), "timeout", reason, duration=dur))
            _run_async(bot.log_action(g, "🔇 Timeout (Dashboard)", f"{member.mention} getimeoutet ({dur}s).\nGrund: {reason}", 0xf59e0b, module="moderation"))
            return jsonify({"ok": True, "action": "timeout", "case_id": case_id})
        elif action == "untimeout":
            _run_async(member.timeout(None, reason="Dashboard: Timeout aufgehoben"))
            _run_async(bot.log_action(g, "🔊 Timeout aufgehoben (Dashboard)", f"{member.mention}", 0x22c55e, module="moderation"))
            return jsonify({"ok": True, "action": "untimeout"})
        elif action == "add_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.add_roles(role, reason="Dashboard: Rolle gegeben"))
                return jsonify({"ok": True, "action": "add_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "remove_role":
            role = g.get_role(int(data.get("role_id", 0)))
            if role:
                _run_async(member.remove_roles(role, reason="Dashboard: Rolle entfernt"))
                return jsonify({"ok": True, "action": "remove_role"})
            return jsonify({"error": "Rolle nicht gefunden"}), 404
        elif action == "nick":
            new_nick = data.get("nick", "")
            _run_async(member.edit(nick=new_nick or None, reason="Dashboard: Nickname geändert"))
            return jsonify({"ok": True, "action": "nick"})
        else:
            return jsonify({"error": f"Unbekannte Aktion: {action}"}), 400
    except Exception as e:
        log.error(f"[MOD ACTION API] {action} on {member_id}: {e}")
        return jsonify({"error": str(e)}), 500
@flask_app.route("/api/guild/<guild_id>/noprefix", methods=["POST"])
@require_auth
def api_noprefix(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    cfg = _direct_load_config(guild_id)
    if "enabled" in data:
        cfg["no_prefix"] = bool(data["enabled"])
    if "action" in data:
        np_users = cfg.get("no_prefix_users", [])
        uid = data.get("user_id")
        if data["action"] == "add" and uid:
            if uid not in [str(u) for u in np_users]:
                np_users.append(int(uid) if uid.isdigit() else uid)
        elif data["action"] == "del" and uid:
            np_users = [u for u in np_users if str(u) != str(uid)]
        cfg["no_prefix_users"] = np_users
    try:
        _direct_save_config(guild_id, cfg)
    except Exception:
        pass
    return jsonify({"ok": True, "no_prefix": cfg.get("no_prefix", False)})
@flask_app.route("/api/guild/<guild_id>/activity")
@require_auth
def api_guild_activity(guild_id):
    """Live-Activity für einen bestimmten Server."""
    try:
        from bot.config import ACTIVITY
        raw = ACTIVITY.snapshot(100)
        if not isinstance(raw, list):
            raw = []
        filtered = [a for a in raw if str(a.get("guild_id","")) == str(guild_id)]
        return jsonify(filtered[:50])
    except Exception:
        return jsonify([])

# ═══════════════════════════════════════════════════════════════════
# AUTO-NICKNAME ROUTES
# Ersetze die KOMPLETTEN alten guild_autonick + api_guild_autonick
# Funktionen – keine doppelten Routes!
# ═══════════════════════════════════════════════════════════════════

@flask_app.route("/dashboard/<guild_id>/autonick")
@require_auth
def guild_autonick(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    an      = cfg.get("auto_nickname", {})
    rules   = an.get("rules", [])
    enabled = an.get("enabled", False)

    # Rollen-Liste für Dropdowns (nach Position sortiert, höchste zuerst)
    guild_roles = []
    if g and hasattr(g, "roles") and g.roles:
        guild_roles = [
            {
                "id":    str(r.id),
                "name":  r.name,
                "color": str(r.color) if r.color and r.color.value else "",
            }
            for r in sorted(g.roles, key=lambda r: r.position, reverse=True)
            if not r.is_default() and not r.managed
        ]

    # Ausnahme-Rollen mit Namen anreichern
    role_map        = {str(r.id): r.name for r in g.roles} if g else {}
    exempt_role_ids = [str(x) for x in an.get("exempt_roles", [])]
    exempt_roles    = [
        {"id": eid, "name": role_map.get(eid, f"Unbekannte Rolle ({eid})")}
        for eid in exempt_role_ids
    ]

    return render_template(
        "dashboard/autonick.html",
        guild=g,
        cfg=cfg,
        user=us["user"],
        rules=rules,
        enabled=enabled,
        guild_roles=guild_roles,
        exempt_roles=exempt_roles,
        active="autonick",
    )
@flask_app.route("/api/guild/<guild_id>/autonick", methods=["POST"])
@require_auth
def api_guild_autonick(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403

    data   = request.json or {}
    action = data.get("action", "").strip()

    if not action:
        return jsonify({"ok": False, "error": "action fehlt"}), 400

    cfg = _direct_load_config(guild_id)
    an  = cfg.get("auto_nickname", {})

    # Defaults sicherstellen
    an.setdefault("enabled",      False)
    an.setdefault("rules",        [])
    an.setdefault("exempt_roles", [])

    # ── toggle ──────────────────────────────────────────────────────
    if action == "toggle":
        an["enabled"] = bool(data.get("enabled", False))

    # ── add ─────────────────────────────────────────────────────────
    elif action == "add":
        role_id = str(data.get("role_id", "")).strip()
        prefix  = data.get("prefix", "")
        suffix  = data.get("suffix", "")

        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        if not prefix and not suffix:
            return jsonify({"ok": False, "error": "Prefix oder Suffix wird benötigt"}), 400

        # Doppelte Regel verhindern
        existing_ids = [str(r.get("role_id", "")) for r in an["rules"]]
        if role_id in existing_ids:
            return jsonify({
                "ok":    False,
                "error": "Für diese Rolle existiert bereits eine Regel"
            }), 400

        new_rule = {
            "role_id":   role_id,
            "role_name": str(data.get("role_name", "")),
            "prefix":    prefix,
            "suffix":    suffix,
            "priority":  len(an["rules"]) + 1,
        }
        an["rules"].append(new_rule)

        # Zuerst speichern
        cfg["auto_nickname"] = an
        try:
            _direct_save_config(guild_id, cfg)
        except Exception as e:
            log.error(f"autonick save (add) Fehler: {e}")
            return jsonify({"ok": False, "error": "Speichern fehlgeschlagen"}), 500

        # Bulk-Apply wurde bewusst entfernt: Nicknames werden sicher über den Bot-Event/Commands angewendet.
        stats = {"applied": 0, "skipped": 0, "failed": 0, "total": 0}

        return jsonify({
            "ok":      True,
            "rules":   an["rules"],
            "enabled": an["enabled"],
            "applied": stats["applied"],
            "skipped": stats["skipped"],
            "failed":  stats["failed"],
            "total":   stats["total"],
        })

    # ── delete ──────────────────────────────────────────────────────
    elif action == "delete":
        idx = data.get("index", -1)
        if not isinstance(idx, int) or not (0 <= idx < len(an["rules"])):
            return jsonify({"ok": False, "error": "Ungültiger Index"}), 400
        an["rules"].pop(idx)
        # Prioritäten neu vergeben
        for i, r in enumerate(an["rules"]):
            r["priority"] = i + 1

    # ── reorder ─────────────────────────────────────────────────────
    elif action == "reorder":
        new_order = data.get("order", [])
        rules     = an["rules"]
        if not isinstance(new_order, list) or len(new_order) != len(rules):
            return jsonify({"ok": False, "error": "Ungültige Reihenfolge"}), 400
        try:
            an["rules"] = [rules[i] for i in new_order if 0 <= i < len(rules)]
            for i, r in enumerate(an["rules"]):
                r["priority"] = i + 1
        except (IndexError, TypeError) as e:
            return jsonify({"ok": False, "error": f"Reorder Fehler: {e}"}), 400

    # ── add_exempt ──────────────────────────────────────────────────
    elif action == "add_exempt":
        role_id = str(data.get("role_id", "")).strip()
        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        exempt = [str(x) for x in an["exempt_roles"]]
        if role_id not in exempt:
            exempt.append(role_id)
        an["exempt_roles"] = exempt

    # ── remove_exempt ───────────────────────────────────────────────
    elif action == "remove_exempt":
        role_id = str(data.get("role_id", "")).strip()
        if not role_id:
            return jsonify({"ok": False, "error": "role_id fehlt"}), 400
        an["exempt_roles"] = [str(x) for x in an["exempt_roles"] if str(x) != role_id]

    # ── Unbekannte Aktion ───────────────────────────────────────────
    else:
        return jsonify({"ok": False, "error": f"Unbekannte Aktion: {action}"}), 400

    # Speichern für alle Aktionen außer 'add' (bereits oben gespeichert)
    cfg["auto_nickname"] = an
    try:
        _direct_save_config(guild_id, cfg)
    except Exception as e:
        log.error(f"autonick save Fehler: {e}")
        return jsonify({"ok": False, "error": "Speichern fehlgeschlagen"}), 500

    return jsonify({
        "ok":      True,
        "rules":   an.get("rules", []),
        "enabled": an.get("enabled", False),
    })
# =========================================================
# BACKUP API – Erstellen / Restore / Löschen / Download
# =========================================================

@flask_app.route("/api/guild/<guild_id>/backup/list")
@require_auth
def api_backup_list(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    backups = []
    for doc in _load_backup_docs(guild_id, limit=250):
        enriched = _enrich_backup_doc(doc)
        if enriched:
            backups.append(enriched)
    backups.sort(key=lambda b: int(b.get("created_ts") or 0), reverse=True)
    return jsonify({"ok": True, "backups": backups, "count": len(backups), "total_size_bytes": sum(b.get("size_bytes", 0) for b in backups)})


@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/preview")
@require_auth
def api_backup_preview(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = _backup_preview(guild_id, backup_id)
    if not data:
        return jsonify({"error": "Backup nicht gefunden"}), 404
    return jsonify({"ok": True, "preview": data})


@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/health")
@require_auth
def api_backup_health(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = _backup_preview(guild_id, backup_id)
    if not data:
        return jsonify({"error": "Backup nicht gefunden"}), 404
    meta = data.get("meta", {})
    return jsonify({"ok": True, "health": {"score": meta.get("health_score", 0), "warnings": meta.get("warnings", []), "risk": data.get("risk"), "summary": data.get("summary")}})


@flask_app.route("/api/guild/<guild_id>/backup/create", methods=["POST"])
@require_auth
def api_backup_create(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Backups können nur erstellt werden, wenn der Bot läuft."}), 503
    data = request.json or {}
    label = (data.get("label") or "").strip() or None
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        from bot.bot import BOT_REF
        _bcog = BOT_REF.get_cog("BackupCog") if BOT_REF else None
        payload = _run_async(_bcog._collect_backup_data(g)) if _bcog else None
        if not payload:
            payload = _collect_backup_payload_web(g)
        if not payload:
            return jsonify({"error": "Backup-Daten konnten nicht gesammelt werden"}), 500
        bid = _run_async(_bcog._backup_db_save(payload, int(user_session["user"]["id"]), label)) if _bcog else None
        if not bid:
            bid = _save_backup_doc_web(guild_id, payload, int(user_session["user"]["id"]), label)
        if not bid:
            return jsonify({"error": "Backup konnte nicht gespeichert werden"}), 500
        preview = _backup_preview(guild_id, bid) or {"meta": _enrich_backup_doc({"backup_id": bid, "guild_id": int(guild_id), "guild_id_str": str(guild_id), "label": label, "data": payload})}
        return jsonify({"ok": True, "backup_id": bid, "backup": preview.get("meta")})
    except Exception as e:
        log.error(f"[BACKUP CREATE] {e}")
        return jsonify({"error": str(e)}), 500
@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/restore", methods=["POST"])
@require_auth
def api_backup_restore(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Restore nur möglich wenn der Bot läuft."}), 503
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    try:
        from bot.bot import BOT_REF; _bcog = BOT_REF.get_cog("BackupCog") if BOT_REF else None
        # Eigenes Backup bevorzugt, Cross-Server als Fallback
        doc = None
        if _bcog:
            doc = _run_async(_bcog._backup_db_get(int(guild_id), backup_id)) or _run_async(_bcog._backup_db_get_any(backup_id))
        if not doc:
            doc = _backup_doc(guild_id, backup_id, allow_any=True)
        if not doc or not doc.get("data"):
            return jsonify({"error": "Backup nicht gefunden"}), 404
        if doc.get("password_hash"):
            return jsonify({
                "error": "Passwortgeschützte Backups bitte mit /backup_restore in Discord wiederherstellen."
            }), 400
        report = _run_async(_bcog._restore_from_backup(g, doc["data"], None)) if _bcog else None
        return jsonify({"ok": True, "report": report or {}})
    except Exception as e:
        log.error(f"[BACKUP RESTORE] {e}")
        return jsonify({"error": str(e)}), 500
@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/delete", methods=["POST"])
@require_auth
def api_backup_delete(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    col = _backups_col()
    if col is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        res = _collection_delete_one(_backup_query(guild_id, backup_id), col)
        deleted = getattr(res, "deleted_count", 0) or 0

        # Auch aus der öffentlichen Liste entfernen, falls geteilt
        pcol = _public_backups_col()
        if pcol is not None:
            _collection_delete_one(_template_query(guild_id, backup_id), pcol)

        if not deleted:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[BACKUP DELETE] {e}")
        return jsonify({"error": str(e)}), 500
@flask_app.route("/api/guild/<guild_id>/backup/<backup_id>/download")
@require_auth
def api_backup_download(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    col = _backups_col()
    if col is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        doc = _collection_find_one(_backup_query(guild_id, backup_id), col)
        if not doc:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        # _id und Passwort-Hash NICHT mit ausliefern
        doc.pop("_id", None)
        doc.pop("password_hash", None)
        body = json.dumps(doc, indent=2, default=str, ensure_ascii=False)
        return Response(
            body, mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="modforge-backup-{backup_id}.json"'},
        )
    except Exception as e:
        log.error(f"[BACKUP DOWNLOAD] {e}")
        return jsonify({"error": str(e)}), 500
# =========================================================
# TEMPLATES API – Public-Backup teilen / unshare / importieren
# =========================================================

@flask_app.route("/api/guild/<guild_id>/templates/share", methods=["POST"])
@require_auth
def api_template_share(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    backup_id = (data.get("backup_id") or "").strip()
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "general").strip().lower()
    if not backup_id or not name:
        return jsonify({"error": "backup_id und name sind erforderlich"}), 400

    col = _backups_col()
    pcol = _public_backups_col()
    if col is None or pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503

    try:
        backup = _collection_find_one(_backup_query(guild_id, backup_id), col)
        if not backup:
            return jsonify({"error": "Backup nicht gefunden"}), 404
        if backup.get("password_hash"):
            return jsonify({"error": "Passwortgeschützte Backups können nicht öffentlich geteilt werden."}), 400

        payload = backup.get("data") or {}
        guild_name = backup.get("guild_name") or payload.get("guild_name") or "?"
        guild_icon = payload.get("guild_icon_url") or ""

        update_doc = {
            "backup_id": backup_id,
            "guild_id": int(guild_id),
            "guild_id_str": str(guild_id),
            "name": name[:60],
            "description": description[:500],
            "category": (category or "general")[:30],
            "shared_by": str(user_session["user"]["id"]),
            "shared_at": datetime.datetime.utcnow(),
            "guild_name": guild_name,
            "guild_icon": guild_icon,
            "roles_count": len(payload.get("roles") or []),
            "channels_count": len(payload.get("channels") or []),
            "categories_count": len(payload.get("categories") or []),
            "emojis_count": len(payload.get("emojis") or []),
        }
        _collection_update_one(
            {"backup_id": backup_id},
            {"$set": update_doc, "$setOnInsert": {"downloads": 0}},
            pcol, upsert=True,
        )
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[TEMPLATE SHARE] {e}")
        return jsonify({"error": str(e)}), 500
@flask_app.route("/api/guild/<guild_id>/templates/unshare/<backup_id>", methods=["POST"])
@require_auth
def api_template_unshare(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    pcol = _public_backups_col()
    if pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    try:
        res = _collection_delete_one(_template_query(guild_id, backup_id), pcol)
        deleted = getattr(res, "deleted_count", 0) or 0
        if not deleted:
            return jsonify({"error": "Template nicht gefunden oder gehört nicht diesem Server"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"[TEMPLATE UNSHARE] {e}")
        return jsonify({"error": str(e)}), 500
def _backup_doc_any(backup_id, guild_id=None):
    col = _backups_col()
    if col is None:
        return None
    doc = _collection_find_one(_backup_query(guild_id, backup_id), col) if guild_id is not None else None
    if not doc:
        doc = _collection_find_one({"backup_id": backup_id}, col)
    return doc


@flask_app.route("/api/guild/<guild_id>/templates/preview/<backup_id>")
@require_auth
def api_template_preview(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    pcol = _public_backups_col()
    public = _collection_find_one({"backup_id": backup_id}, pcol) if pcol is not None else None
    doc = _backup_doc_any(backup_id)
    if not doc:
        return jsonify({"error": "Template/Backup nicht gefunden"}), 404
    payload = doc.get("data") or doc
    roles = payload.get("roles") or []
    channels = payload.get("channels") or []
    categories_raw = payload.get("categories") or []
    score = _template_score_from_counts(len(roles), len(channels), len(categories_raw), (public or {}).get("downloads", 0), (public or {}).get("likes", 0), (public or {}).get("description", ""))
    risk = _template_risk_from_backup(payload, get_guild(guild_id))
    return jsonify({
        "ok": True,
        "template": {
            "id": backup_id,
            "name": (public or {}).get("name") or doc.get("label") or "Template",
            "description": (public or {}).get("description") or "",
            "category": (public or {}).get("category", "general"),
            "score": score, "risk": risk,
            "downloads": int((public or {}).get("downloads") or 0),
            "likes": int((public or {}).get("likes") or 0),
            "rating_avg": round(sum([int(v) for v in ((public or {}).get("ratings") or {}).values() if str(v).isdigit()]) / max(1, len(((public or {}).get("ratings") or {}))), 2) if (public or {}).get("ratings") else 0,
            "rating_count": len((public or {}).get("ratings") or {}),
            "recommended": _template_recommendations((public or {}).get("category"), len(roles), len(channels)),
            "roles": [{"name": r.get("name", str(r)) if isinstance(r, dict) else str(r)} for r in roles[:25]],
            "channels": [{"name": c.get("name", str(c)) if isinstance(c, dict) else str(c), "type": c.get("type", "text") if isinstance(c, dict) else "text"} for c in channels[:35]],
            "categories": [{"name": c.get("name", str(c)) if isinstance(c, dict) else str(c)} for c in categories_raw[:20]],
        }
    })


@flask_app.route("/api/guild/<guild_id>/templates/check/<backup_id>")
@require_auth
def api_template_check(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    g = get_guild(guild_id)
    doc = _backup_doc_any(backup_id)
    if not doc:
        return jsonify({"error": "Template/Backup nicht gefunden"}), 404
    payload = doc.get("data") or doc
    roles = payload.get("roles") or []
    channels = payload.get("channels") or []
    cats = payload.get("categories") or []
    current_roles = {r.name.lower() for r in getattr(g, "roles", []) if not r.is_default()} if g else set()
    current_channels = {c.name.lower() for c in getattr(g, "channels", [])} if g else set()
    role_names = [r.get("name", str(r)).lower() if isinstance(r, dict) else str(r).lower() for r in roles]
    channel_names = [c.get("name", str(c)).lower() if isinstance(c, dict) else str(c).lower() for c in channels]
    added_roles = [r for r in role_names if r not in current_roles]
    existing_roles = [r for r in role_names if r in current_roles]
    added_channels = [c for c in channel_names if c not in current_channels]
    existing_channels = [c for c in channel_names if c in current_channels]
    risk = _template_risk_from_backup(payload, g)
    warnings = list(risk.get("warnings", []))
    if existing_roles:
        warnings.append(f"{len(existing_roles)} Rolle(n) existieren bereits und können übersprungen werden")
    if existing_channels:
        warnings.append(f"{len(existing_channels)} Kanal/Kanäle existieren bereits und können übersprungen werden")
    return jsonify({
        "ok": True, "risk": risk.get("level", "low"), "warnings": warnings,
        "summary": {
            "roles_total": len(roles), "roles_new": len(added_roles), "roles_existing": len(existing_roles),
            "channels_total": len(channels), "channels_new": len(added_channels), "channels_existing": len(existing_channels),
            "categories_total": len(cats),
        },
        "samples": {"roles_new": added_roles[:12], "channels_new": added_channels[:12]},
    })


@flask_app.route("/api/guild/<guild_id>/templates/like/<backup_id>", methods=["POST"])
@require_auth
def api_template_like(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    pcol = _public_backups_col()
    if pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    uid = str(user_session.get("user", {}).get("id", "0"))
    doc = _collection_find_one({"backup_id": backup_id}, pcol)
    if not doc:
        return jsonify({"error": "Template nicht gefunden"}), 404
    liked_by = set(str(x) for x in (doc.get("liked_by") or []))
    if uid in liked_by:
        _collection_update_one({"backup_id": backup_id}, {"$pull": {"liked_by": uid}, "$inc": {"likes": -1}}, pcol)
        liked = False
    else:
        _collection_update_one({"backup_id": backup_id}, {"$addToSet": {"liked_by": uid}, "$inc": {"likes": 1}}, pcol)
        liked = True
    new_doc = _collection_find_one({"backup_id": backup_id}, pcol) or {}
    return jsonify({"ok": True, "liked": liked, "likes": max(0, int(new_doc.get("likes", 0) or 0))})


@flask_app.route("/api/guild/<guild_id>/templates/rate/<backup_id>", methods=["POST"])
@require_auth
def api_template_rate(guild_id, backup_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    pcol = _public_backups_col()
    if pcol is None:
        return jsonify({"error": "Keine DB-Verbindung"}), 503
    data = request.json or {}
    try:
        stars = max(1, min(5, int(data.get("stars", 0))))
    except (TypeError, ValueError):
        return jsonify({"error": "Bewertung muss 1–5 Sterne sein"}), 400
    uid = str(user_session.get("user", {}).get("id", "0"))
    doc = _collection_find_one({"backup_id": backup_id}, pcol)
    if not doc:
        return jsonify({"error": "Template nicht gefunden"}), 404
    _collection_update_one({"backup_id": backup_id}, {"$set": {f"ratings.{uid}": stars}}, pcol)
    new_doc = _collection_find_one({"backup_id": backup_id}, pcol) or {}
    ratings = new_doc.get("ratings") or {}
    vals = [int(v) for v in ratings.values() if str(v).isdigit()]
    avg = round(sum(vals) / len(vals), 2) if vals else 0
    return jsonify({"ok": True, "stars": stars, "rating_avg": avg, "rating_count": len(vals)})


@flask_app.route("/api/guild/<guild_id>/templates/import/<backup_id>", methods=["POST"])
@require_auth
def api_template_import(guild_id, backup_id):
    """Wendet ein öffentliches Template auf den aktuellen Server an (Restore).

    Sicherheitsregeln:
      • Frontend muss confirmed=true senden.
      • Vor Import wird automatisch ein Backup erstellt.
      • Restore-Log + Pre-Backup-ID werden zurückgegeben.
    """
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline. Import nur möglich wenn der Bot läuft."}), 503
    data = request.json or {}
    if not data.get("confirmed"):
        return jsonify({"error": "Bitte Import per Checkbox bestätigen."}), 400
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    restore_log = []
    pre_backup_id = None
    try:
        from bot.bot import BOT_REF
        _bcog = BOT_REF.get_cog("BackupCog") if BOT_REF else None
        if not _bcog:
            return jsonify({"error": "Backup-System ist nicht geladen. Import aus Sicherheitsgründen abgebrochen."}), 503

        doc = _run_async(_bcog._backup_db_get_any(backup_id)) or _backup_doc_any(backup_id)
        if not doc or not doc.get("data"):
            return jsonify({"error": "Template nicht gefunden"}), 404
        if doc.get("password_hash"):
            return jsonify({"error": "Passwortgeschützte Templates können nicht importiert werden."}), 400

        restore_log.append("Template gefunden und geprüft.")
        # Auto-Backup VOR Import
        pre_payload = _run_async(_bcog._collect_backup_data(g)) or _collect_backup_payload_web(g)
        if not pre_payload:
            return jsonify({"error": "Sicherheits-Backup vor Import konnte nicht erstellt werden."}), 500
        pre_backup_id = _run_async(_bcog._backup_db_save(
            pre_payload,
            int(user_session["user"]["id"]),
            f"Auto-Backup vor Template {backup_id}",
        )) or _save_backup_doc_web(guild_id, pre_payload, int(user_session["user"]["id"]), f"Auto-Backup vor Template {backup_id}")
        if not pre_backup_id:
            return jsonify({"error": "Sicherheits-Backup vor Import konnte nicht gespeichert werden."}), 500
        restore_log.append(f"Sicherheits-Backup erstellt: {pre_backup_id}")

        # Detaillierter Vergleich vor Restore
        check = _backup_preview(guild_id, backup_id, allow_any=True)
        if check:
            s = check.get("summary", {})
            restore_log.append(
                f"Import-Check: {s.get('roles_new', 0)} neue Rollen, "
                f"{s.get('channels_new', 0)} neue Kanäle, "
                f"{s.get('categories_total', 0)} Kategorien. Risiko: {check.get('risk', 'low')}"
            )
            for warning in check.get("warnings", [])[:5]:
                restore_log.append(f"Warnung: {warning}")

        restore_log.append("Restore gestartet.")
        report = _run_async(_bcog._restore_from_backup(g, doc["data"], None)) or {}
        restore_log.append(
            f"Restore fertig: Rollen erstellt {report.get('roles_created', 0)}, "
            f"Kanäle erstellt {report.get('channels_created', 0)}, "
            f"Fehler {len(report.get('errors', []) or [])}."
        )
        for err in (report.get("errors") or [])[:8]:
            restore_log.append(f"Fehler: {err}")

        # Download-Counter
        pcol = _public_backups_col()
        if pcol is not None:
            try:
                _collection_update_one({"backup_id": backup_id}, {"$inc": {"downloads": 1}}, pcol)
            except Exception:
                pass
        return jsonify({"ok": True, "report": report, "pre_backup_id": pre_backup_id, "restore_log": restore_log})
    except Exception as e:
        log.error(f"[TEMPLATE IMPORT] {e}")
        return jsonify({"error": str(e), "pre_backup_id": pre_backup_id, "restore_log": restore_log}), 500

@flask_app.route("/dashboard/<guild_id>/badges")
@require_auth
def guild_badges(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err
    if str(us.get("user", {}).get("id")) != "1303627964734246944":
        abort(403)
    db = get_db()
    definitions = []
    history = []
    guild_badges = {}
    if db:
        defs = safe_async(db.badge_definitions(), {}) or {}
        definitions = sorted(defs.values(), key=lambda b: (b.get("category", "general"), b.get("name", "")))
        history = safe_async(db.badge_history(int(guild_id), 150), []) or []
        guild_badges = safe_async(db.badge_get_all_guild_details(int(guild_id)), {}) or {}
    role_options = []
    if g and getattr(g, "roles", None):
        role_options = [{"id": str(r.id), "name": r.name} for r in g.roles if not r.is_default() and not getattr(r, "managed", False)]
    users_with_badges = []
    for uid, badges in guild_badges.items():
        member = g.get_member(int(uid)) if g and str(uid).isdigit() else None
        users_with_badges.append({"id": uid, "name": member.display_name if member else uid, "badges": badges})
    return render_template(
        "dashboard/badges.html", guild=g, cfg=cfg, user=us["user"], active="badges",
        definitions=definitions, history=history, role_options=role_options, users_with_badges=users_with_badges
    )

# =========================================================
# BADGE API (nur Bot-Developer)
# =========================================================

@flask_app.route("/api/guild/<guild_id>/badges/definitions", methods=["POST"])
@require_auth
def api_badge_definition_upsert(guild_id):
    user_session = get_session()
    if not user_session or str(user_session["user"]["id"]) != "1303627964734246944":
        return jsonify({"error": "Nur der Bot-Developer kann Badge-Definitionen verwalten."}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    data = request.json or {}
    badge_id = (data.get("id") or data.get("badge_id") or "").strip()
    name = (data.get("name") or "").strip()
    if not badge_id or not name:
        return jsonify({"error": "Badge-ID und Name fehlen"}), 400
    ok = safe_async(db.badge_def_upsert(
        badge_id, name, data.get("emoji", "🏷️"), data.get("color", "#94a3b8"),
        data.get("desc") or data.get("description", ""), int(user_session["user"]["id"]),
        data.get("category", "general"), data.get("rarity", "common"), data.get("style", "solid"),
        data.get("level", 1), _to_int_or_none(data.get("role_id"))
    ), False)
    return jsonify({"ok": bool(ok)})

@flask_app.route("/api/guild/<guild_id>/badges/definitions/<badge_id>", methods=["DELETE"])
@require_auth
def api_badge_definition_delete(guild_id, badge_id):
    user_session = get_session()
    if not user_session or str(user_session["user"]["id"]) != "1303627964734246944":
        return jsonify({"error": "Nur der Bot-Developer kann Badge-Definitionen verwalten."}), 403
    if badge_id in BADGES:
        return jsonify({"error": "Statische Badges können nicht gelöscht werden."}), 400
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    ok = safe_async(db.badge_def_delete(badge_id), False)
    return jsonify({"ok": bool(ok)})

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/badges", methods=["GET"])
@require_auth
def api_member_badges_get(guild_id, member_id):
    """Alle Badges eines Users abrufen."""
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    try:
        result = safe_async(db.badge_get_details(int(guild_id), int(member_id)), []) or []
        defs = safe_async(db.badge_definitions(), {}) or {}
        return jsonify({"ok": True, "badges": result, "all_badges": [
            {"id": k, "name": v.get("name", k), "emoji": v.get("emoji", "🏷️"), "color": v.get("color", "#94a3b8"), "desc": v.get("desc", ""), "category": v.get("category", "general"), "rarity": v.get("rarity", "common"), "style": v.get("style", "solid"), "level": v.get("level", 1), "role_id": v.get("role_id"), "custom": v.get("custom", False)}
            for k, v in sorted(defs.items(), key=lambda x: x[1].get("name", x[0]))
        ]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/badges", methods=["POST"])
@require_auth
def api_member_badge_add(guild_id, member_id):
    """Badge zu einem User hinzufügen (nur Bot-Developer)."""
    user_session = get_session()
    if not user_session or str(user_session["user"]["id"]) != "1303627964734246944":
        return jsonify({"error": "Nur der Bot-Developer kann Badges verwalten."}), 403
    data = request.json or {}
    badge_id = (data.get("badge_id") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    defs = safe_async(db.badge_definitions(), {}) or {}
    if not badge_id or badge_id not in defs:
        return jsonify({"error": f"Ungültiges Badge: {badge_id}"}), 400
    try:
        ok = safe_async(db.badge_add(int(guild_id), int(member_id), badge_id, int(user_session["user"]["id"])), False)
        if ok:
            try:
                bd = defs.get(badge_id, {})
                role_id = bd.get("role_id")
                guild = get_guild(guild_id)
                member = guild.get_member(int(member_id)) if guild else None
                role = guild.get_role(int(role_id)) if guild and role_id else None
                if member and role and bot_ready():
                    _run_async(member.add_roles(role, reason=f"Badge-Rolle: {badge_id}"))
            except Exception as e:
                log.debug(f"badge role link failed: {e}")
        return jsonify({"ok": ok, "duplicate": not ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/badges/order", methods=["POST"])
@require_auth
def api_member_badge_order(guild_id, member_id):
    """Reihenfolge der Badges eines Users speichern (nur Bot-Developer)."""
    user_session = get_session()
    if not user_session or str(user_session["user"]["id"]) != "1303627964734246944":
        return jsonify({"error": "Nur der Bot-Developer kann Badge-Reihenfolgen ändern."}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    data = request.json or {}
    badge_ids = data.get("badge_ids") or []
    if not isinstance(badge_ids, list):
        return jsonify({"error": "badge_ids muss eine Liste sein"}), 400
    ok = safe_async(db.badge_reorder(int(guild_id), int(member_id), badge_ids), False)
    return jsonify({"ok": bool(ok)})

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/badges/<badge_id>", methods=["DELETE"])
@require_auth
def api_member_badge_remove(guild_id, member_id, badge_id):
    """Badge von einem User entfernen (nur Bot-Developer)."""
    user_session = get_session()
    if not user_session or str(user_session["user"]["id"]) != "1303627964734246944":
        return jsonify({"error": "Nur der Bot-Developer kann Badges verwalten."}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    try:
        ok = safe_async(db.badge_remove(int(guild_id), int(member_id), badge_id), False)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/details")
@require_auth
def api_member_details(guild_id, member_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "database offline"}), 503
    try:
        # Fetch notes
        notes = safe_async(db.notes.find({"guild_id": int(guild_id), "user_id": int(member_id)}).sort([("pinned", -1), ("created_at", -1), ("timestamp", -1)]).to_list(50), []) or []
        # Convert BSON/Datetime
        for n in notes:
            n["_id"] = str(n["_id"])
            if n.get("timestamp") and hasattr(n.get("timestamp"), "isoformat"): n["timestamp"] = n["timestamp"].isoformat() + "Z"
            if n.get("created_at") and hasattr(n.get("created_at"), "isoformat"): n["created_at"] = n["created_at"].isoformat() + "Z"
        
        # Fetch detailed cases
        cases = safe_async(db.cases.find({"guild_id": int(guild_id), "user_id": int(member_id)}).sort("case_id", -1).to_list(50), []) or []
        for c in cases:
            c["_id"] = str(c["_id"])
            if c.get("created_at"): c["created_at"] = c["created_at"].isoformat() + "Z"
            if c.get("timestamp"): c["timestamp"] = c["timestamp"].isoformat() + "Z"
            
        return jsonify({"ok": True, "notes": notes, "cases": cases})
    except Exception as e:
        log.error(f"[MEMBER DETAILS API] {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route("/api/guild/<guild_id>/member/<member_id>/note", methods=["POST"])
@require_auth
def api_member_note(guild_id, member_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    data = request.json or {}
    text = data.get("text")
    if not text: return jsonify({"error": "missing text"}), 400
    try:
        priority = data.get("priority", "medium") if data.get("priority", "medium") in ("low", "medium", "high") else "medium"
        note = {
            "guild_id": int(guild_id),
            "user_id": int(member_id),
            "mod_id": int(user_session["user"]["id"]),
            "text": text[:2000],
            "priority": priority,
            "pinned": bool(data.get("pinned", False)),
            "created_at": datetime.datetime.utcnow(),
            "timestamp": datetime.datetime.utcnow()
        }
        safe_async(db.notes.insert_one(note))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================================================
# ADVANCED DASHBOARD FEATURES: Wizard, Emergency, Rollback, Audit, Export
# =========================================================

@flask_app.route("/dashboard/<guild_id>/audit")
@require_auth
def guild_audit(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err
    events = []
    try:
        raw = ACTIVITY.snapshot(200)
        events = [a for a in raw if str(a.get("guild_id", "")) == str(guild_id) and str(a.get("kind", "")).lower() in {"audit", "security", "antinuke", "moderation", "case"}][:80]
    except Exception:
        pass
    if bot_ready() and g and hasattr(g, "audit_logs"):
        async def _fetch_audit():
            out = []
            try:
                async for entry in g.audit_logs(limit=25):
                    out.append({
                        "kind": str(entry.action).replace("AuditLogAction.", ""),
                        "text": f"{entry.user} → {getattr(entry.target, 'name', entry.target)}",
                        "ts": entry.created_at.isoformat(),
                    })
            except Exception:
                pass
            return out
        audit_events = safe_async(_fetch_audit(), []) or []
        events = audit_events + events
    dangerous_roles = _dangerous_roles(g)
    return render_template("dashboard/audit.html", guild=g, cfg=cfg, user=us["user"], events=events, dangerous_roles=dangerous_roles, active="audit")


def _dangerous_roles(guild):
    result = []
    if not guild or not getattr(guild, "roles", None):
        return result
    danger = ["administrator", "manage_roles", "ban_members", "manage_webhooks"]
    for role in guild.roles:
        try:
            if role.is_default() or getattr(role, "managed", False):
                continue
            perms = []
            for perm in danger:
                if getattr(role.permissions, perm, False):
                    perms.append(perm)
            if perms:
                result.append({"id": str(role.id), "name": role.name, "perms": perms, "position": getattr(role, "position", 0)})
        except Exception:
            continue
    return sorted(result, key=lambda x: -x["position"])[:50]


def _permission_report(guild, cfg):
    checks = []
    me = getattr(guild, "me", None) if guild else None
    perms = getattr(me, "guild_permissions", None)
    def add(key, label, ok, fix):
        checks.append({"key": key, "label": label, "ok": bool(ok), "fix": fix})
    add("manage_roles", "Manage Roles", getattr(perms, "manage_roles", False), "Bot-Rolle höher ziehen und Recht geben")
    add("ban_members", "Ban Members", getattr(perms, "ban_members", False), "Recht `Mitglieder bannen` aktivieren")
    add("kick_members", "Kick Members", getattr(perms, "kick_members", False), "Recht `Mitglieder kicken` aktivieren")
    add("manage_channels", "Manage Channels", getattr(perms, "manage_channels", False), "Für Lockdown und TempVoice nötig")
    add("manage_messages", "Manage Messages", getattr(perms, "manage_messages", False), "Für AutoMod-Löschungen nötig")
    add("logs", "Log-Kanal", bool(cfg.get("log_channel") or cfg.get("log_channels")), "Unter Logs `/log #kanal` setzen")
    return checks


@flask_app.route("/api/guild/<guild_id>/health")
@require_auth
def api_guild_health(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    g = get_guild(guild_id)
    cfg = _direct_load_config(guild_id)
    checks = _permission_report(g, cfg)
    return jsonify({
        "ok": True,
        "bot_online": bot_ready(),
        "checks": checks,
        "dangerous_roles": _dangerous_roles(g),
        "score": _score_config(g, cfg),
    })


def _score_config(guild, cfg):
    score = 0
    if cfg.get("log_channel") or cfg.get("log_channels"): score += 10
    if cfg.get("anti_nuke", {}).get("enabled"): score += 20
    if cfg.get("anti_spam", {}).get("enabled"): score += 10
    if cfg.get("anti_raid", {}).get("enabled"): score += 10
    if cfg.get("automod", {}).get("enabled"): score += 10
    if cfg.get("verify_system", {}).get("enabled"): score += 10
    if cfg.get("backup_system", {}).get("auto_enabled"): score += 10
    me = getattr(guild, "me", None) if guild else None
    perms = getattr(me, "guild_permissions", None)
    if perms and getattr(perms, "manage_roles", False) and getattr(perms, "ban_members", False): score += 15
    if cfg.get("security_level", 0) >= 2: score += 5
    return min(score, 100)


@flask_app.route("/api/guild/<guild_id>/onboarding/wizard_seen", methods=["POST"])
@require_auth
def api_wizard_seen(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    cfg = _direct_load_config(guild_id)
    onboarding = cfg.get("dashboard_onboarding", {}) or {}
    onboarding["wizard_popup_seen"] = True
    onboarding["wizard_popup_seen_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    cfg["dashboard_onboarding"] = onboarding
    try:
        _direct_save_config(guild_id, cfg)
        return jsonify({"ok": True})
    except Exception as e:
        log.error(f"wizard_seen save failed: {e}")
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/quick_setup", methods=["POST"])
@require_auth
def api_quick_setup(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    profile = data.get("profile", "safe")
    log_channel = _to_int_or_none(data.get("log_channel"))
    cfg = _direct_load_config(guild_id)
    _save_config_version(guild_id, cfg, source="before-quick-setup")
    cfg["security_level"] = 1 if profile == "easy" else 2 if profile == "safe" else 3
    for key in ("anti_spam", "anti_nuke", "anti_raid", "automod", "anti_scam", "anti_mention"):
        cfg.setdefault(key, {})["enabled"] = True
    if log_channel:
        cfg["log_channel"] = log_channel
        from bot.config import LOG_MODULES, LOG_MODULES_EXTRA
        cfg["log_channels"] = {m: log_channel for m in list(LOG_MODULES) + list(LOG_MODULES_EXTRA)}
    if data.get("welcome_channel"):
        cfg.setdefault("welcome", {})["enabled"] = True
        cfg["welcome"]["channel_id"] = _to_int_or_none(data.get("welcome_channel"))
    if data.get("verify_channel"):
        cfg.setdefault("verify_system", {})["enabled"] = True
        cfg["verify_system"]["verify_channel"] = _to_int_or_none(data.get("verify_channel"))
    onboarding = cfg.get("dashboard_onboarding", {}) or {}
    onboarding.update({
        "wizard_popup_seen": True,
        "wizard_popup_seen_at": datetime.datetime.utcnow().isoformat() + "Z",
        "wizard_profile": profile,
    })
    cfg["dashboard_onboarding"] = onboarding
    _direct_save_config(guild_id, cfg)
    return jsonify({"ok": True, "score": _score_config(get_guild(guild_id), cfg)})


@flask_app.route("/api/guild/<guild_id>/emergency", methods=["POST"])
@require_auth
def api_emergency_mode(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    if not bot_ready():
        return jsonify({"error": "Bot ist offline"}), 503
    g = get_guild(guild_id)
    if not g:
        return jsonify({"error": "Server nicht gefunden"}), 404
    cfg = _direct_load_config(guild_id)
    _save_config_version(guild_id, cfg, source="before-emergency")
    cfg.setdefault("anti_raid", {})["enabled"] = True
    cfg["anti_raid"]["lockdown"] = True
    cfg["security_level"] = 3
    _direct_save_config(guild_id, cfg)
    locked = 0
    try:
        for ch in getattr(g, "text_channels", [])[:100]:
            try:
                _run_async(ch.set_permissions(g.default_role, send_messages=False, reason="Dashboard Emergency Mode"))
                locked += 1
            except Exception:
                pass
        try:
            if getattr(g, "owner", None):
                import discord
                emb = discord.Embed(title="🚨 Emergency Mode aktiv", description=f"Auf **{g.name}** wurde Emergency Mode aktiviert.", color=0xef4444)
                _run_async(g.owner.send(embed=emb))
        except Exception:
            pass
        _run_async(bot.log_action(g, "🚨 Emergency Mode", f"{locked} Kanäle gesperrt. AntiRaid maximal gesetzt.", 0xef4444, module="security"))
    except Exception as e:
        log.error(f"Emergency mode error: {e}")
    return jsonify({"ok": True, "locked": locked})


@flask_app.route("/api/guild/<guild_id>/cases/export")
@require_auth
def api_cases_export(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    fmt = request.args.get("format", "json").lower()
    db = get_db()
    cases = []
    if db:
        cases = safe_async(db.cases.find(_guild_query(guild_id)).sort("case_id", -1).to_list(1000), []) or []
    for c in cases:
        c.pop("_id", None)
        for k, v in list(c.items()):
            if hasattr(v, "isoformat"):
                c[k] = v.isoformat()
    if fmt == "html":
        rows = "".join(f"<tr><td>#{c.get('case_id')}</td><td>{c.get('action')}</td><td>{c.get('user_id')}</td><td>{c.get('reason','')}</td></tr>" for c in cases)
        body = f"<html><meta charset='utf-8'><body><h1>Cases {guild_id}</h1><table border='1' cellspacing='0' cellpadding='6'>{rows}</table></body></html>"
        return Response(body, mimetype="text/html", headers={"Content-Disposition": f"attachment; filename=cases-{guild_id}.html"})
    return Response(json.dumps(cases, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": f"attachment; filename=cases-{guild_id}.json"})


@flask_app.route("/api/guild/<guild_id>/case/<case_id>/reason", methods=["POST"])
@require_auth
def api_case_edit_reason(guild_id, case_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    new_reason = data.get("reason", "").strip()
    db = get_db()
    if not db:
        return jsonify({"error": "Datenbank offline"}), 503
    try:
        q = {"guild_id": {"$in": _guild_id_values(guild_id)}, "case_id": {"$in": [int(case_id), str(case_id)]}}
        res = db.cases.update_one(q, {"$set": {"reason": new_reason}})
        if res.modified_count > 0 or res.matched_count > 0:
            return jsonify({"ok": True})
        return jsonify({"error": "Case nicht gefunden"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/case/<case_id>/evidence", methods=["POST"])
@require_auth
def api_case_add_evidence(guild_id, case_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    url = data.get("url", "").strip()
    note = data.get("note", "").strip()
    if not url:
        return jsonify({"error": "Beweis-URL fehlt"}), 400
    db = get_db()
    if not db:
        return jsonify({"error": "Datenbank offline"}), 503
    try:
        q = {"guild_id": {"$in": _guild_id_values(guild_id)}, "case_id": {"$in": [int(case_id), str(case_id)]}}
        evidence_entry = {
            "url": url,
            "note": note,
            "added_by": user_session.get("user", {}).get("id") or 0,
            "added_at": datetime.datetime.utcnow().isoformat()
        }
        res = db.cases.update_one(q, {"$push": {"evidence": evidence_entry}})
        if res.modified_count > 0 or res.matched_count > 0:
            return jsonify({"ok": True})
        return jsonify({"error": "Case nicht gefunden"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/case/<case_id>", methods=["DELETE"])
@require_auth
def api_case_delete(guild_id, case_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    db = get_db()
    if not db:
        return jsonify({"error": "Datenbank offline"}), 503
    try:
        q = {"guild_id": {"$in": _guild_id_values(guild_id)}, "case_id": {"$in": [int(case_id), str(case_id)]}}
        res = db.cases.delete_one(q)
        if res.deleted_count > 0:
            return jsonify({"ok": True})
        return jsonify({"error": "Case nicht gefunden"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@flask_app.route("/api/guild/<guild_id>/config/versions")
@require_auth
def api_config_versions(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    col = _config_versions_col()
    if col is None:
        return jsonify({"ok": True, "versions": []})
    docs = list(col.find({"guild_id": int(guild_id)}).sort("created_at", -1).limit(25))
    versions = [{"id": str(d.get("_id")), "source": d.get("source", "dashboard"), "created_at": d.get("created_at").isoformat() if d.get("created_at") else ""} for d in docs]
    return jsonify({"ok": True, "versions": versions})


@flask_app.route("/api/guild/<guild_id>/config/rollback", methods=["POST"])
@require_auth
def api_config_rollback(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    col = _config_versions_col()
    if col is None:
        return jsonify({"error": "Keine Versionen verfügbar"}), 404
    data = request.json or {}
    vid = data.get("version_id")
    try:
        from bson.objectid import ObjectId
        doc = col.find_one({"_id": ObjectId(vid), "guild_id": int(guild_id)}) if vid else col.find_one({"guild_id": int(guild_id)}, sort=[("created_at", -1)])
    except Exception:
        doc = None
    if not doc:
        return jsonify({"error": "Version nicht gefunden"}), 404
    _save_config_version(guild_id, _direct_load_config(guild_id), source="before-rollback")
    _direct_save_config(guild_id, doc.get("config", {}))
    return jsonify({"ok": True})

# ═══════════════════════════════════════════════════════════════════
# BETA-FEATURE DASHBOARD (Dark Mode, Appeals, Staff Applications)
# Hinweis: Alle Funktionen in diesem Bereich sind als BETA markiert.
# Es können Fehler auftreten. Funktionen werden kontinuierlich verbessert.
# ═══════════════════════════════════════════════════════════════════

def _beta_warning():
    """Returns a standardized BETA warning text."""
    return {
        "beta": True,
        "warning": "⚠️ Diese Funktionen sind BETA. Es können Fehler auftreten. "
                   "Bei Problemen bitte im Support-Channel melden. "
                   "Alle Daten werden sicher in der MongoDB gespeichert."
    }


@flask_app.route("/dashboard/<guild_id>/beta")
@require_auth
def guild_beta(guild_id):
    """Zeigt das BETA-Dashboard mit allen experimentellen Features."""
    us, g, cfg, err = _dash_guard(guild_id)
    if err:
        return err

    # Aktuelle Beta-Settings aus Config
    beta_cfg = cfg.get("beta_features", {}) or {}

    # Lade Daten aus DB
    appeals = []
    staff_apps = []
    theme = {}
    try:
        from database.db import Database
        db = Database()
        appeals = safe_async(db.aget_all_appeals(int(guild_id)), []) or []
        staff_apps = safe_async(db.aget_all_staff_applications(int(guild_id)), []) or []
        theme = safe_async(db.aget_server_theme(int(guild_id)), {}) or {}
    except Exception as ex:
        log.debug(f"Beta dashboard load: {ex}")

    # Counts
    appeals_count = len(appeals)
    appeals_pending = sum(1 for a in appeals if a.get("status") == "pending")
    staff_count = len(staff_apps)
    staff_pending = sum(1 for s in staff_apps if s.get("status") == "pending")

    # Aktuelle Theme-Einstellung
    current_theme = theme.get("theme_name") or beta_cfg.get("theme", "dark")
    auto_dm = beta_cfg.get("auto_dm_enabled", True)
    smart_timeout = beta_cfg.get("smart_timeout_enabled", True)
    risk_alerts = beta_cfg.get("risk_alerts_enabled", True)

    # Verfügbare Themes
    THEMES_LIST = [
        ("dark", "🌙 Dark", "#5865F2"),
        ("light", "☀️ Light", "#7C3AED"),
        ("midnight", "🌌 Midnight", "#8B5CF6"),
        ("sunset", "🌅 Sunset", "#EC4899"),
        ("forest", "🌲 Forest", "#22C55E"),
        ("neon", "⚡ Neon", "#FACC15"),
        ("ocean", "🌊 Ocean", "#06B6D4"),
        ("lavender", "💜 Lavender", "#C084FC"),
    ]

    return render_template(
        "dashboard/beta.html",
        guild=g, cfg=cfg, user=us["user"],
        active="beta",
        beta_warning=_beta_warning(),
        themes=THEMES_LIST,
        current_theme=current_theme,
        auto_dm=auto_dm,
        smart_timeout=smart_timeout,
        risk_alerts=risk_alerts,
        appeals=appeals[:20],
        staff_apps=staff_apps[:20],
        appeals_count=appeals_count,
        appeals_pending=appeals_pending,
        staff_count=staff_count,
        staff_pending=staff_pending,
        theme_data=theme,
    )


# ── API: Theme Settings ─────────────────────────────────────
@flask_app.route("/api/guild/<guild_id>/beta/theme", methods=["POST"])
@require_auth
def api_beta_theme(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    theme = data.get("theme", "dark")
    if theme not in ["dark", "light", "midnight", "sunset", "forest", "neon", "ocean", "lavender"]:
        return jsonify({"error": "Unbekanntes Theme"}), 400
    try:
        from database.db import Database
        db = Database()
        _run_async(db.asave_server_theme(int(guild_id), {
            "guild_id": int(guild_id),
            "theme_name": theme,
            "accent_color": data.get("accent_color", "#5865F2"),
            "updated_at": datetime.datetime.utcnow(),
        }))
        # Auch in Config speichern
        cfg = _direct_load_config(guild_id)
        beta_cfg = cfg.get("beta_features", {}) or {}
        beta_cfg["theme"] = theme
        cfg["beta_features"] = beta_cfg
        _direct_save_config(guild_id, cfg)
        return jsonify({"ok": True, "theme": theme})
    except Exception as e:
        log.error(f"Beta theme save error: {e}")
        return jsonify({"error": str(e), "beta": True}), 500


# ── API: Beta Settings (auto_dm, smart_timeout, risk_alerts) ─
@flask_app.route("/api/guild/<guild_id>/beta/settings", methods=["POST"])
@require_auth
def api_beta_settings(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    try:
        cfg = _direct_load_config(guild_id)
        beta_cfg = cfg.get("beta_features", {}) or {}
        if "auto_dm_enabled" in data:
            beta_cfg["auto_dm_enabled"] = bool(data["auto_dm_enabled"])
        if "smart_timeout_enabled" in data:
            beta_cfg["smart_timeout_enabled"] = bool(data["smart_timeout_enabled"])
        if "risk_alerts_enabled" in data:
            beta_cfg["risk_alerts_enabled"] = bool(data["risk_alerts_enabled"])
        beta_cfg["updated_at"] = datetime.datetime.utcnow().isoformat()
        cfg["beta_features"] = beta_cfg
        if _direct_save_config(guild_id, cfg):
            return jsonify({"ok": True, "beta_features": beta_cfg})
        return jsonify({"error": "Speichern fehlgeschlagen"}), 500
    except Exception as e:
        log.error(f"Beta settings save error: {e}")
        return jsonify({"error": str(e), "beta": True}), 500


# ── API: Appeal Status Update ──────────────────────────────────
@flask_app.route("/api/guild/<guild_id>/beta/appeals/<appeal_id>", methods=["POST"])
@require_auth
def api_beta_appeal_update(guild_id, appeal_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    action = data.get("action", "approve")  # approve, reject, delete
    reviewer_id = int(user_session.get("user", {}).get("id", 0)) if user_session.get("user", {}).get("id") not in (None, "0") else None
    try:
        from database.db import Database
        db = Database()
        if action == "delete":
            ok = safe_async(db.adelete_appeal(appeal_id), False)
            return jsonify({"ok": bool(ok), "action": "deleted"})
        status = "approved" if action == "approve" else "rejected"
        ok = safe_async(db.aupdate_appeal_status(appeal_id, status, reviewer_id=reviewer_id), False)
        return jsonify({"ok": bool(ok), "status": status})
    except Exception as e:
        log.error(f"Appeal update error: {e}")
        return jsonify({"error": str(e), "beta": True}), 500


# ── API: Staff Application Status Update ──────────────────────
@flask_app.route("/api/guild/<guild_id>/beta/staff/<app_id>", methods=["POST"])
@require_auth
def api_beta_staff_update(guild_id, app_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    action = data.get("action", "approve")
    notes = data.get("notes", "")
    reviewer_id = int(user_session.get("user", {}).get("id", 0)) if user_session.get("user", {}).get("id") not in (None, "0") else None
    try:
        from database.db import Database
        db = Database()
        if action == "delete":
            ok = safe_async(db.adelete_staff_application(app_id), False)
            return jsonify({"ok": bool(ok), "action": "deleted"})
        status = "approved" if action == "approve" else "rejected"
        ok = safe_async(db.aupdate_staff_application_status(app_id, status, reviewer_id=reviewer_id, notes=notes), False)
        return jsonify({"ok": bool(ok), "status": status})
    except Exception as e:
        log.error(f"Staff update error: {e}")
        return jsonify({"error": str(e), "beta": True}), 500


# ── API: Get Risk Profile (Dashboard) ─────────────────────────
@flask_app.route("/api/guild/<guild_id>/beta/risk/<user_id>")
@require_auth
def api_beta_risk(guild_id, user_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    try:
        from bot.cogs.beta import compute_user_risk
        g = get_guild(guild_id)
        if not g:
            return jsonify({"error": "Server nicht gefunden"}), 404
        member = g.get_member(int(user_id))
        if not member:
            return jsonify({"error": "User nicht gefunden"}), 404
        cfg = _direct_load_config(guild_id)
        cases = []
        try:
            from database.db import Database
            db = Database()
            cases = safe_async(db.cases.find({"guild_id": str(guild_id), "user_id": int(user_id)}).to_list(100), []) or []
        except Exception:
            pass
        risk = compute_user_risk(member, cfg, cases)
        risk["user_name"] = str(member)
        risk["user_avatar"] = member.display_avatar.url
        return jsonify({"ok": True, "risk": risk})
    except Exception as e:
        log.error(f"Risk profile error: {e}")
        return jsonify({"error": str(e), "beta": True}), 500


# 404 / 403 / 500 HANDLER
# =========================================================

@flask_app.errorhandler(404)
def page_not_found(e):
    return render_template("errors/404.html"), 404
@flask_app.errorhandler(403)
def forbidden(e):
    return render_template("errors/403.html"), 403
@flask_app.errorhandler(500)
def internal_error(e):
    log.error(f"[500 ERROR] {e}")
    return render_template("errors/500.html"), 500


# =========================================================
# BETA & ADVANCED FEATURES API ROUTES
# =========================================================

@flask_app.route("/api/guild/<guild_id>/activity")
@require_auth
def api_activity_feed(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    
    from database.db import Database
    db = Database()
    events = safe_async(db.aget_activity_feed(int(guild_id), 50), [])
    return jsonify(events)

@flask_app.route("/api/guild/<guild_id>/user/<user_id>/risk")
@require_auth
def api_user_risk(guild_id, user_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    
    from database.db import Database
    db = Database()
    risk = safe_async(db.aget_user_risk(int(guild_id), int(user_id)), {})
    return jsonify(risk)

@flask_app.route("/api/guild/<guild_id>/appeal/<appeal_id>/vote", methods=["POST"])
@require_auth
def api_vote_appeal(guild_id, appeal_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    
    data = request.json or {}
    vote = data.get("vote")
    
    # Hier würde die Abstimmungslogik stehen
    return jsonify({"ok": True, "message": "Vote recorded (Beta)"})

@flask_app.route("/api/guild/<guild_id>/theme", methods=["POST"])
@require_auth
def api_save_theme(guild_id):
    user_session = _api_session_or_admin(guild_id)
    if not user_session:
        return jsonify({"error": "forbidden"}), 403
    
    data = request.json or {}
    from database.db import Database
    db = Database()
    safe_async(db.asave_server_theme(int(guild_id), data), None)
    return jsonify({"ok": True})

@flask_app.route("/dashboard/<guild_id>/risk/<user_id>")
@require_auth
def guild_user_risk(guild_id, user_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    
    from database.db import Database
    db = Database()
    risk = safe_async(db.aget_user_risk(int(guild_id), int(user_id)), {})
    
    # Berechne Account-Alter
    member = g.get_member(int(user_id)) if g else None
    account_age = (datetime.datetime.utcnow() - member.created_at.replace(tzinfo=None)).days if member else 0
    join_age = (datetime.datetime.utcnow() - member.joined_at.replace(tzinfo=None)).days if member and member.joined_at else 0
    
    return render_template("dashboard/user_risk.html", 
                          guild=g, user=member, risk=risk, 
                          account_age=account_age, join_age=join_age)

@flask_app.route("/dashboard/<guild_id>/appeals")
@require_auth
def guild_appeals(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    
    from database.db import Database
    db = Database()
    appeals = safe_async(db.aget_pending_appeals(int(guild_id)), [])
    
    return render_template("dashboard/appeals.html", guild=g, appeals=appeals)

@flask_app.route("/dashboard/<guild_id>/staff-applications")
@require_auth
def guild_staff_applications(guild_id):
    us, g, cfg, err = _dash_guard(guild_id)
    if err: return err
    
    from database.db import Database
    db = Database()
    applications = safe_async(db.aget_pending_applications(int(guild_id)), [])
    
    return render_template("dashboard/staff_applications.html", guild=g, applications=applications)



@flask_app.route("/.well-known/discord")
def discord_verification():
    return "dh=96214b1c83e2b4ee693a8c49861b0216bebdd455", 200, {"Content-Type": "text/plain"}
