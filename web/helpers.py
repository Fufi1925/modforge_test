# web/helpers.py
import logging
import copy
from html import escape

from bot.config import DEFAULT_CONFIG, VALID_PUNISHMENTS, get_uptime
from bot.utils import _run_async

log = logging.getLogger("ModForge.Web.Helpers")


def _h(value) -> str:
    return escape(str(value or ""), quote=True)


def _bot_stats():
    """Gibt (guild_count, member_count, uptime_seconds, latency_ms) zurück – IMMER sicher."""
    gc = mc = up = lat = 0
    try:
        from bot.bot import BOT_REF

        if BOT_REF is not None and BOT_REF.is_ready():
            gc = len(BOT_REF.guilds)
            mc = sum(g.member_count or 0 for g in BOT_REF.guilds)
            try:
                up = get_uptime(BOT_REF.start_time)
            except Exception:
                up = 0
            if BOT_REF.latency is not None:
                lat = round(BOT_REF.latency * 1000, 1)
    except Exception as e:
        log.debug(f"_bot_stats error: {e}")
    return gc, mc, up, lat


def _get_guild_config(guild_id) -> dict:
    """Lädt die Config – gibt IMMER ein gültiges Dict zurück, nie einen Crash."""
    try:
        from bot.bot import BOT_REF

        if BOT_REF is not None and hasattr(BOT_REF, "db") and BOT_REF.db is not None:
            cfg = _run_async(BOT_REF.db.aget_config(int(guild_id)))
            if cfg and isinstance(cfg, dict):
                return cfg
    except Exception as e:
        log.debug(f"_get_guild_config error for {guild_id}: {e}")
    return copy.deepcopy(DEFAULT_CONFIG)


def _build_overview(cfg: dict, guild_id: str) -> str:
    """Erzeugt das HTML für die Dashboard-Übersichtsseite."""
    if not isinstance(cfg, dict):
        cfg = copy.deepcopy(DEFAULT_CONFIG)

    mods = [
        "anti_spam",
        "anti_nuke",
        "anti_raid",
        "anti_mention",
        "automod",
        "anti_scam",
    ]
    rows = ""
    for m in mods:
        enabled = (
            cfg.get(m, {}).get("enabled") if isinstance(cfg.get(m), dict) else False
        )
        rows += f"""<div style="display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.04)">
            <span style="font-size:.85rem">{m.replace("_", " ").title()}</span>
            <span>{"✅" if enabled else "❌"} {"Aktiv" if enabled else "Inaktiv"}</span>
        </div>"""

    active = sum(
        1
        for m in mods
        if isinstance(cfg.get(m), dict) and cfg.get(m, {}).get("enabled")
    )
    sec_level = (
        cfg.get("security_level", 0)
        if isinstance(cfg.get("security_level"), int)
        else 0
    )
    log_ch = cfg.get("log_channels")
    log_count = len(log_ch) if isinstance(log_ch, dict) else 0

    return f"""<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px;margin-bottom:22px">
    <div class="db-stat"><div class="db-stat-val" style="color:var(--vl)">{active}</div><div class="db-stat-label">Aktive Module (von {len(mods)})</div></div>
    <div class="db-stat"><div class="db-stat-val" style="color:var(--green)">{sec_level}</div><div class="db-stat-label">Security Level (0-3)</div></div>
    <div class="db-stat"><div class="db-stat-val" style="color:var(--amberl)">{log_count}</div><div class="db-stat-label">Log-Kanäle</div></div>
</div>
<div class="db-card"><div class="db-card-header"><span class="db-card-title">📊 Modul-Status</span></div>{rows}</div>"""


def _build_module_form(section: str, cfg: dict, guild_id: str) -> str:
    """Erzeugt das HTML-Formular für ein einzelnes Modul."""
    if not isinstance(cfg, dict):
        cfg = copy.deepcopy(DEFAULT_CONFIG)

    mod_map = {
        "antispam": "anti_spam",
        "antinuke": "anti_nuke",
        "antiraid": "anti_raid",
        "antimention": "anti_mention",
        "antiscam": "anti_scam",
        "automod": "automod",
        "verify": "verify_system",
        "tickets": "ticket_system",
        "autorole": "auto_role",
        "logs": "log_channels",
        "warns": "warn_system",
    }
    mod = mod_map.get(section, section)
    mcfg = cfg.get(mod, {})
    if not isinstance(mcfg, dict):
        mcfg = {}

    enabled = mcfg.get("enabled", False)
    punishment = mcfg.get("punishment", "warn")
    icon = {
        "antispam": "⚡",
        "antinuke": "💥",
        "antiraid": "🚨",
        "antimention": "🔔",
        "antiscam": "🎣",
        "automod": "🤖",
        "verify": "✅",
        "tickets": "🎫",
        "autorole": "🏷️",
        "logs": "📢",
        "warns": "⚠️",
    }.get(section, "⚙️")

    pun_opts = "".join(
        f'<option value="{p}" {"selected" if punishment == p else ""}>{p}</option>'
        for p in VALID_PUNISHMENTS
    )

    return f"""<div class="db-card" style="margin-bottom:16px">
    <div class="db-card-header"><span class="db-card-title">{icon} {section.replace("anti", "Anti-").title()}</span></div>
    <div class="cfg-row"><div><span class="cfg-label">Aktiviert</span><div class="cfg-desc">Modul ein-/ausschalten</div></div>
    <label class="toggle"><input type="checkbox" id="en" {"checked" if enabled else ""}><span class="slider"></span></label></div>
    <div class="cfg-row"><div><span class="cfg-label">Bestrafung</span></div>
    <select id="pn" class="cfg-select" style="min-width:140px">{pun_opts}</select></div>
</div>"""


def _build_welcome_content(cfg: dict, guild_id: str) -> str:
    """Erzeugt das HTML für Welcome/Leave Einstellungen."""
    if not isinstance(cfg, dict):
        cfg = copy.deepcopy(DEFAULT_CONFIG)

    wc = cfg.get("welcome", {})
    if not isinstance(wc, dict):
        wc = {}
    lc = cfg.get("leave", {})
    if not isinstance(lc, dict):
        lc = {}

    wc_col = wc.get("embed_color", "#22c55e") if str(wc.get("embed_color", "")).startswith("#") else "#22c55e"
    lc_col = lc.get("embed_color", "#ef4444") if str(lc.get("embed_color", "")).startswith("#") else "#ef4444"

    return f"""
<div class="db-card" style="margin-bottom:20px">
    <div class="db-card-header"><span class="db-card-title">👋 Welcome-Nachricht</span></div>
    <div class="cfg-row"><div><span class="cfg-label">Aktiviert</span></div>
    <label class="toggle"><input type="checkbox" id="wc-en" {"checked" if wc.get("enabled") else ""}><span class="slider"></span></label></div>
    <div class="cfg-row"><div><span class="cfg-label">Titel</span></div>
    <input class="cfg-input" id="wc-title" value="{_h(wc.get("embed_title", "👋 Willkommen!"))}" style="max-width:300px;width:100%"></div>
    <div class="cfg-row"><div><span class="cfg-label">Beschreibung</span></div>
    <input class="cfg-input" id="wc-desc" value="{_h(wc.get("embed_description", "Willkommen!"))}" style="max-width:400px;width:100%"></div>
    <div class="cfg-row"><div><span class="cfg-label">Farbe</span></div>
    <input type="color" id="wc-col" value="{wc_col}" style="width:50px;height:32px;border:none;border-radius:8px;cursor:pointer"></div>
    <div class="cfg-row"><div><span class="cfg-label">DM senden</span></div>
    <label class="toggle"><input type="checkbox" id="wc-dm" {"checked" if wc.get("dm_enabled") else ""}><span class="slider"></span></label></div>
</div>
<div class="db-card">
    <div class="db-card-header"><span class="db-card-title">👋 Leave-Nachricht</span></div>
    <div class="cfg-row"><div><span class="cfg-label">Aktiviert</span></div>
    <label class="toggle"><input type="checkbox" id="lv-en" {"checked" if lc.get("enabled") else ""}><span class="slider"></span></label></div>
    <div class="cfg-row"><div><span class="cfg-label">Titel</span></div>
    <input class="cfg-input" id="lv-title" value="{_h(lc.get("embed_title", "👋 Auf Wiedersehen!"))}" style="max-width:300px;width:100%"></div>
    <div class="cfg-row"><div><span class="cfg-label">Farbe</span></div>
    <input type="color" id="lv-col" value="{lc_col}" style="width:50px;height:32px;border:none;border-radius:8px;cursor:pointer"></div>
</div>"""
