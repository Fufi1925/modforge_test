// -*- coding: utf-8 -*-
// ModForge – zentrale Konfiguration (Node.js Migration)

const os = require('node:os');

const BOT_START_TIME = Date.now();
let EXTRA_UPTIME = Number.parseInt(process.env.EXTRA_UPTIME || '0', 10);
if (!Number.isFinite(EXTRA_UPTIME) || EXTRA_UPTIME < 0) EXTRA_UPTIME = 0;

function getUptime(startTime = BOT_START_TIME) {
  return Math.floor((Date.now() - startTime) / 1000) + EXTRA_UPTIME;
}

const BOT_TOKEN = process.env.DISCORD_TOKEN || '';

const COLOR_PRIMARY = 0x4169E1;
const COLOR_SUCCESS = 0x3CB371;
const COLOR_WARNING = 0xFEE75C;
const COLOR_DANGER = 0xED4245;
const COLOR_INFO = 0x00B0F4;
const COLOR_PURPLE = 0x9B59B6;

const FOOTER_TEXT = 'Powered by BotForge 🔒';
const FOOTER_ICON = 'https://cdn.discordapp.com/attachments/1509625552120840315/1511461866512056460/178042110349811.png?ex=6a208a0e&is=6a1f388e&hm=2e4a3f12ba9013ea8991f5835c39a5542b8e1c3385521d9a6ac88f0361a8a5eb';
const VERIFY_BANNER_URL = 'https://cdn.discordapp.com/attachments/1484260674145353928/1491861030601490432/1775755687339.png?ex=69d93b5b&is=69d7e9db&hm=d65f0da063a98be84b880e8abbdaeaac62eefe7f674724835b3a7e56b20f4943';

const E = Object.freeze({
  "OK": "<:1000052153:1493631416355917845>",
  "FAIL": "<:1000052152:1493631418671169546>",
  "SPAM": "<:1000051794:1493333260774805697>",
  "NUKE": "<:1000051798:1493333267481362493>",
  "RAID": "<:1000051717:1493333511489191989>",
  "MENTION": "<:1000051804:1493333277413740625>",
  "AUTOMOD": "<:1000051809:1493333289887334581>",
  "GHOST": "<:1000051752:1493333170005999898>",
  "SCAM": "<:1000051714:1493333518489485485>",
  "URLSHORT": "<:1000051729:1493333478035423292>",
  "GEAR": "<:1000051763:1493333183637225632>",
  "CHANNEL": "<:1000051745:1493333161449619636>",
  "PREFIX": "<:1000051785:1493333233805562126>",
  "SETTINGS": "<:1000051765:1493333200293068963>",
  "HELP": "<:1000051767:1493333187332411503>",
  "SYSTEM": "<:1000051810:1493333291342757969>",
  "OWNER": "<:1000051807:1493333285718196244>",
  "SHIELD": "<:1000051808:1493333287874068660>",
  "BOT": "<:1000051809:1493333289887334581>",
  "LATENCY": "<:1000051758:1493333196438507760>",
  "SERVER": "<:1000051764:1493333190708957234>",
  "USERS": "<:1000051750:1493333172962721872>",
  "CLOCK": "<:1000051766:1493333185281659102>",
  "BAN": "<:1000051714:1493333518489485485>",
  "KICK": "<:1000051798:1493333267481362493>",
  "WARN": "<:1000051717:1493333511489191989>",
  "MUTE": "<:1000051715:1493333515478237409>",
  "UNMUTE": "<:1000051716:1493333509773988051>",
  "DELETE": "<:1000051793:1493333258233057361>",
  "SLOW": "<:1000051751:1493333171675201707>",
  "LOCK": "<:1000051721:1493333505449398382>",
  "UNLOCK": "<:1000051722:1493333498847690985>",
  "NICK": "<:1000051770:1493333205082837202>",
  "EDIT": "<:1000051770:1493333205082837202>",
  "ROLE_ADD": "<:1000051772:1493333206928199690>",
  "ROLE_DEL": "<:1000051788:1493333238817493215>",
  "ROLE": "<:1000051784:1493333231532118137>",
  "VOICE_IN": "<:1000051716:1493333509773988051>",
  "VOICE_OUT": "<:1000051715:1493333515478237409>",
  "VOICE_SW": "<:1000051730:1493333482644967564>",
  "DUP": "<:1000051730:1493333482644967564>",
  "CAPS": "<:1000051760:1493333181657649235>",
  "EMOJI": "<:1000051750:1493333172962721872>",
  "BADWORD": "<:1000051799:1493333269444427898>",
  "NEWACC": "<:1000051779:1493333222115770488>",
  "JOIN": "<:1000051772:1493333206928199690>",
  "TICKET": "<:1000051768:1493333201924390982>",
  "TICKET_OK": "<:1000051630:1493333448688013482>",
  "TICKETBOX": "<:1000051761:1493333192030162967>",
  "VERIFY": "<:1000051808:1493333287874068660>",
  "VERIFY_BTN": "<:1000051808:1493333287874068660>",
  "EMOJI_LIST": "<:1000051775:1493333213031174224>",
  "CREATED": "<:1000051755:1493333177710678118>",
  "ROLES": "<:1000051792:1493333255091388607>",
  "CHANNELS": "<:1000051804:1493333277413740625>",
  "APPEAL": "📋",
  "MESSAGE": "<:1000051770:1493333205082837202>",
  "WEBHOOK": "<:1000051809:1493333289887334581>",
  "PERMS": "<:1000051808:1493333287874068660>",
  "UPDATE": "<:1000051770:1493333205082837202>",
  "NOTE": "<:1000051767:1493333187332411503>",
  "MOD": "<:1000051808:1493333287874068660>",
  "USER": "<:1000051750:1493333172962721872>",
  "IMAGE": "<:1000051775:1493333213031174224>",
  "NO": "<:1000052152:1493631418671169546>",
  "SPEED": "⚡",
  "ALERT": "⚠",
  "PLUS": "➕",
  "MINUS": "➖",
  "QUESTION": "❓",
  "LAW": "⚖",
  "DOT": "⚪",
  "REFRESH": "♻",
  "SHIELD_UI": "🛡️",
  "SPEED_UI": "⚡",
  "RAID_UI": "🚨",
  "BOT_UI": "🤖",
  "MENTION_UI": "🔔",
  "SCAM_UI": "🎣",
  "OK_UI": "✅",
  "APPEAL_UI": "📋",
  "AUDIT_UI": "🔍",
  "TICKET_UI": "🎫",
  "WELCOME_UI": "👋",
  "LOGS_UI": "📝",
  "ROCKET": "🚀",
  "HAMMER": "🔨",
  "PARTY": "🎉",
  "RED": "🔴",
  "ORANGE": "🟠",
  "YELLOW": "🟡",
  "GREEN": "🟢",
  "BLUE": "🔵",
  "FOLDER": "📁",
  "CATEGORY": "📂",
  "FILE": "📄",
  "SAVE": "💾",
  "TEXT": "💬",
  "VOICE": "🔊",
  "LABEL": "🏷️",
  "CASE": "<:1000051768:1493333201924390982>",
  "STATS": "<:1000051764:1493333190708957234>",
  "REPORT": "<:1000051717:1493333511489191989>",
  "TRANSFER": "<:1000051798:1493333267481362493>",
  "VANITY": "<:1000051785:1493333233805562126>",
  "ICON_CHANGE": "<:1000051775:1493333213031174224>",
  "BANNER_CHANGE": "<:1000051775:1493333213031174224>",
  "TOKEN_LEAK": "<:1000051799:1493333269444427898>",
  "WEBHOOK_LEAK": "<:1000051809:1493333289887334581>",
  "HIERARCHY": "<:1000051808:1493333287874068660>",
  "PERM_WARN": "<:1000051717:1493333511489191989>",
  "TIMER": "<:1000051766:1493333185281659102>",
  "HEART": "<:1000052153:1493631416355917845>",
  "DOXX": "<:1000051799:1493333269444427898>",
  "IMPERSONATE": "<:1000051752:1493333170005999898>",
  "CRYPTO": "<:1000051714:1493333518489485485>",
  "APPROVAL": "<:1000051767:1493333187332411503>",
  "MULTI_RAID": "<:1000051717:1493333511489191989>",
  "TIMEZONE": "<:1000051766:1493333185281659102>",
  "PANIC": "<:1000051798:1493333267481362493>",
  "SNAPSHOT": "<:1000051764:1493333190708957234>",
  "GROWTH": "<:1000051772:1493333206928199690>",
  "HEATMAP": "<:1000051764:1493333190708957234>",
  "TRANSCRIPT": "<:1000051770:1493333205082837202>",
  "PRIORITY_LOW": "<:1000052153:1493631416355917845>",
  "PRIORITY_MED": "<:1000051717:1493333511489191989>",
  "PRIORITY_HIGH": "<:1000052152:1493631418671169546>",
  "PRIORITY_URGENT": "<:1000051798:1493333267481362493>",
  "CLAIM": "<:1000051772:1493333206928199690>",
  "SURVEY": "<:1000051767:1493333187332411503>",
  "CANNED": "<:1000051770:1493333205082837202>",
  "MATH": "<:1000051763:1493333183637225632>",
  "QUIZ": "<:1000051767:1493333187332411503>",
  "TRUST": "<:1000051808:1493333287874068660>",
  "ALT": "<:1000051752:1493333170005999898>",
  "LOGS_CMD": "<:1000051765:1493333200293068963>"
});

const VALID_PUNISHMENTS = ['delete', 'warn', 'mute', 'timeout', 'kick', 'ban'];
const LOG_MODULES = ['moderation', 'antispam', 'antinuke', 'antiraid', 'antimention', 'antiscam', 'automod', 'verify', 'tickets', 'welcome'];
const LOG_MODULES_EXTRA = ['voice', 'members', 'nicknames', 'channels', 'roles', 'webhooks', 'warns', 'cases', 'backup', 'tempvoice'];
const LOG_MODS = [...LOG_MODULES, ...LOG_MODULES_EXTRA];

const SCAM_DOMAINS = [
  'discord-gift.com', 'discord-nitro.com', 'steamcomnunity.com', 'steamcommunnity.com',
  'dlscord.com', 'discrod.com', 'discorcl.com', 'nitro-drop.com'
];
const URL_SHORTENERS = ['bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'is.gd', 'ow.ly', 'cutt.ly', 'shorturl.at'];

const BADGES = Object.freeze({
  "bug_hunter": {
    "name": "Bug Hunter",
    "emoji": "🐛",
    "color": "#22d3ee",
    "desc": "Hat einen kritischen Bug gemeldet",
    "category": "moderation",
    "rarity": "epic",
    "style": "glow",
    "level": 4
  },
  "premium": {
    "name": "Premium",
    "emoji": "💎",
    "color": "#c084fc",
    "desc": "Premium-Mitglied",
    "category": "premium",
    "rarity": "epic",
    "style": "shine",
    "level": 3
  },
  "early_supporter": {
    "name": "Early Supporter",
    "emoji": "🌟",
    "color": "#fbbf24",
    "desc": "ModForge seit Tag 1",
    "category": "support",
    "rarity": "legendary",
    "style": "legendary",
    "level": 7
  },
  "contributor": {
    "name": "Contributor",
    "emoji": "🔧",
    "color": "#34d399",
    "desc": "Hat zum Code beigetragen",
    "category": "team",
    "rarity": "rare",
    "style": "glow",
    "level": 4
  },
  "translator": {
    "name": "Translator",
    "emoji": "🌍",
    "color": "#60a5fa",
    "desc": "Hat Übersetzungen erstellt",
    "category": "community",
    "rarity": "rare",
    "style": "outline",
    "level": 2
  },
  "designer": {
    "name": "Designer",
    "emoji": "🎨",
    "color": "#f472b6",
    "desc": "Hat UI/UX beigesteuert",
    "category": "team",
    "rarity": "epic",
    "style": "shine",
    "level": 4
  },
  "moderator": {
    "name": "Moderator",
    "emoji": "🛡️",
    "color": "#818cf8",
    "desc": "Community-Moderator",
    "category": "moderation",
    "rarity": "rare",
    "style": "glow",
    "level": 3
  },
  "veteran": {
    "name": "Veteran",
    "emoji": "🏆",
    "color": "#f59e0b",
    "desc": "1+ Jahr aktives Mitglied",
    "category": "loyalty",
    "rarity": "legendary",
    "style": "pulse",
    "level": 6
  },
  "challenger": {
    "name": "Challenger",
    "emoji": "⚔️",
    "color": "#ef4444",
    "desc": "Hat alle Challenges gemeistert",
    "category": "event",
    "rarity": "epic",
    "style": "shine",
    "level": 4
  },
  "event_winner": {
    "name": "Event Winner",
    "emoji": "🥇",
    "color": "#facc15",
    "desc": "Hat ein Event gewonnen",
    "category": "event",
    "rarity": "legendary",
    "style": "legendary",
    "level": 8
  },
  "nitro_booster": {
    "name": "Nitro Booster",
    "emoji": "💜",
    "color": "#d946ef",
    "desc": "Boostet ModForge mit Nitro",
    "category": "support",
    "rarity": "epic",
    "style": "pulse",
    "level": 4
  },
  "verified": {
    "name": "Verified",
    "emoji": "✅",
    "color": "#22c55e",
    "desc": "Verifiziertes Mitglied",
    "category": "community",
    "rarity": "common",
    "style": "solid",
    "level": 1
  },
  "partner": {
    "name": "Partner",
    "emoji": "🤝",
    "color": "#fb923c",
    "desc": "Offizieller Partner",
    "category": "team",
    "rarity": "epic",
    "style": "outline",
    "level": 4
  },
  "staff": {
    "name": "Staff",
    "emoji": "👔",
    "color": "#a78bfa",
    "desc": "ModForge-Team-Mitglied",
    "category": "team",
    "rarity": "rare",
    "style": "glow",
    "level": 5
  },
  "developer": {
    "name": "Developer",
    "emoji": "💻",
    "color": "#38bdf8",
    "desc": "Entwickelt Bots/Plugins",
    "category": "team",
    "rarity": "epic",
    "style": "shine",
    "level": 6
  },
  "streamer": {
    "name": "Streamer",
    "emoji": "🎥",
    "color": "#e879f9",
    "desc": "Aktiver Streamer",
    "category": "community",
    "rarity": "rare",
    "style": "pulse",
    "level": 3
  },
  "artist": {
    "name": "Artist",
    "emoji": "🖌️",
    "color": "#fb7185",
    "desc": "Kreativer Künstler",
    "category": "community",
    "rarity": "rare",
    "style": "shine",
    "level": 3
  },
  "musician": {
    "name": "Musician",
    "emoji": "🎵",
    "color": "#2dd4bf",
    "desc": "Musik-Talent",
    "category": "community",
    "rarity": "rare",
    "style": "pulse",
    "level": 3
  },
  "gamer": {
    "name": "Gamer",
    "emoji": "🎮",
    "color": "#4ade80",
    "desc": "Aktiver Gamer",
    "category": "community",
    "rarity": "common",
    "style": "solid",
    "level": 1
  },
  "collector": {
    "name": "Collector",
    "emoji": "🏅",
    "color": "#fbbf24",
    "desc": "Sammelt alle Badges",
    "category": "activity",
    "rarity": "epic",
    "style": "shine",
    "level": 5
  },
  "helper": {
    "name": "Helper",
    "emoji": "🙋",
    "color": "#38bdf8",
    "desc": "Hilft anderen Mitgliedern",
    "category": "community",
    "rarity": "rare",
    "style": "glow",
    "level": 3
  },
  "innovator": {
    "name": "Innovator",
    "emoji": "💡",
    "color": "#a3e635",
    "desc": "Hat innovative Ideen eingebracht",
    "category": "team",
    "rarity": "epic",
    "style": "glow",
    "level": 5
  },
  "beta_tester": {
    "name": "Beta Tester",
    "emoji": "🧪",
    "color": "#94a3b8",
    "desc": "Testet neue Features vor Release",
    "category": "team",
    "rarity": "rare",
    "style": "outline",
    "level": 3
  },
  "donator": {
    "name": "Donator",
    "emoji": "❤️",
    "color": "#f43f5e",
    "desc": "Hat ModForge gespendet",
    "category": "support",
    "rarity": "epic",
    "style": "pulse",
    "level": 4
  },
  "og_member": {
    "name": "OG Member",
    "emoji": "👑",
    "color": "#eab308",
    "desc": "Eines der ersten 100 Mitglieder",
    "category": "loyalty",
    "rarity": "legendary",
    "style": "legendary",
    "level": 7
  },
  "message_100": {
    "name": "Chat Aktiv",
    "emoji": "💬",
    "color": "#38bdf8",
    "desc": "Hat 100 Nachrichten geschrieben",
    "category": "activity",
    "rarity": "rare",
    "style": "glow",
    "level": 1
  },
  "invite_10": {
    "name": "Einlader",
    "emoji": "📨",
    "color": "#22c55e",
    "desc": "Hat 10 Mitglieder eingeladen",
    "category": "activity",
    "rarity": "epic",
    "style": "shine",
    "level": 2
  },
  "member_one_year": {
    "name": "1 Jahr Mitglied",
    "emoji": "🎂",
    "color": "#f59e0b",
    "desc": "Ist seit mindestens einem Jahr auf dem Server",
    "category": "loyalty",
    "rarity": "legendary",
    "style": "legendary",
    "level": 3
  },
  "server_booster": {
    "name": "Server Booster",
    "emoji": "💜",
    "color": "#d946ef",
    "desc": "Boostet den Server",
    "category": "support",
    "rarity": "epic",
    "style": "pulse",
    "level": 2
  },
  "bot_owner_dev": {
    "name": "Bot Owner/Dev",
    "emoji": "👑",
    "color": "#f59e0b",
    "desc": "Offizieller ModForge Bot-Owner und Entwickler",
    "category": "team",
    "rarity": "mythic",
    "style": "legendary",
    "level": 999
  },
  "security_expert": {
    "name": "Security Expert",
    "emoji": "🔐",
    "color": "#60a5fa",
    "desc": "Kennt sich mit Discord-Security besonders gut aus",
    "category": "moderation",
    "rarity": "epic",
    "style": "glow",
    "level": 5
  },
  "raid_defender": {
    "name": "Raid Defender",
    "emoji": "🛡️",
    "color": "#22c55e",
    "desc": "Hat beim Abwehren eines Raids geholfen",
    "category": "moderation",
    "rarity": "legendary",
    "style": "shine",
    "level": 7
  },
  "case_master": {
    "name": "Case Master",
    "emoji": "📋",
    "color": "#a78bfa",
    "desc": "Hat viele Cases sauber bearbeitet",
    "category": "moderation",
    "rarity": "rare",
    "style": "outline",
    "level": 4
  },
  "event_host": {
    "name": "Event Host",
    "emoji": "🎤",
    "color": "#fb7185",
    "desc": "Organisiert Community-Events",
    "category": "event",
    "rarity": "rare",
    "style": "pulse",
    "level": 3
  },
  "community_star": {
    "name": "Community Star",
    "emoji": "🌟",
    "color": "#facc15",
    "desc": "Besonders positives Community-Mitglied",
    "category": "community",
    "rarity": "epic",
    "style": "shine",
    "level": 5
  },
  "trusted_member": {
    "name": "Trusted Member",
    "emoji": "✅",
    "color": "#34d399",
    "desc": "Sehr vertrauenswürdiges Mitglied",
    "category": "community",
    "rarity": "rare",
    "style": "glow",
    "level": 2
  },
  "legend": {
    "name": "Server Legende",
    "emoji": "🏆",
    "color": "#f97316",
    "desc": "Legendäres Mitglied mit besonderem Status",
    "category": "loyalty",
    "rarity": "legendary",
    "style": "legendary",
    "level": 10
  },
  "mythic_supporter": {
    "name": "Mythic Supporter",
    "emoji": "💠",
    "color": "#22d3ee",
    "desc": "Außergewöhnlicher Supporter",
    "category": "support",
    "rarity": "mythic",
    "style": "legendary",
    "level": 20
  },
  "founder_friend": {
    "name": "Founder Friend",
    "emoji": "🤝",
    "color": "#c084fc",
    "desc": "Enger Unterstützer des Projekts",
    "category": "team",
    "rarity": "legendary",
    "style": "shine",
    "level": 8
  }
});

const DEFAULT_CONFIG = Object.freeze({
  "security_level": 0,
  "log_channel": null,
  "log_channels": {},
  "mod_role": null,
  "admin_role": null,
  "mute_role": null,
  "prefix": "!",
  "verify_system": {
    "enabled": false,
    "mode": "one_click",
    "verify_channel": null,
    "add_roles": [],
    "remove_roles": [],
    "message_id": null,
    "captcha_difficulty": "medium"
  },
  "ticket_system": {
    "enabled": false,
    "category_id": null,
    "log_channel_id": null,
    "ticket_message_id": null
  },
  "anti_spam": {
    "enabled": true,
    "msg_limit": 5,
    "msg_window": 10,
    "caps_pct": 70,
    "emoji_max": 10,
    "duplicate_max": 3,
    "punishment": "timeout",
    "timeout_duration": 30
  },
  "anti_nuke": {
    "enabled": true,
    "threshold": 5,
    "window": 10,
    "punishment": "ban",
    "remove_roles": true
  },
  "anti_raid": {
    "enabled": true,
    "join_threshold": 10,
    "window": 20,
    "min_account_age": 7,
    "auto_kick": false,
    "lockdown": false,
    "new_account_window": 600,
    "new_account_threshold": 5,
    "suspicious_name_check": true
  },
  "anti_mention": {
    "enabled": true,
    "mention_limit": 5,
    "window": 10,
    "punishment": "timeout",
    "timeout_duration": 60
  },
  "anti_webhook": {
    "enabled": true,
    "threshold": 3,
    "window": 30
  },
  "anti_ghost_ping": {
    "enabled": true
  },
  "anti_scam": {
    "enabled": true,
    "punishment": "ban"
  },
  "anti_url_shortener": {
    "enabled": true,
    "punishment": "warn"
  },
  "automod": {
    "enabled": true,
    "bad_words": [],
    "regex_rules": [],
    "invite_filter": true,
    "link_filter": false,
    "block_all_links": false,
    "allowed_domains": [],
    "zalgo_filter": true,
    "unicode_abuse": true,
    "phishing_check": true,
    "punishment": "warn"
  },
  "warn_decay": {
    "enabled": false,
    "decay_days": 30
  },
  "warn_system": {
    "enabled": true,
    "thresholds": {
      "3": "timeout",
      "5": "kick",
      "7": "ban"
    }
  },
  "message_archive": {
    "enabled": false,
    "ttl_hours": 48
  },
  "perms_audit": {
    "danger_perms": [
      "administrator",
      "manage_guild",
      "manage_roles",
      "manage_channels",
      "ban_members",
      "kick_members",
      "mention_everyone",
      "manage_webhooks",
      "manage_messages",
      "moderate_members"
    ],
    "max_safe_position_pct": 80
  },
  "appeal_log_channel": null,
  "backup_system": {
    "auto_enabled": false,
    "auto_interval_hours": 24,
    "auto_max_backups": 5,
    "auto_last_backup": null
  },
  "welcome": {
    "enabled": false,
    "channel_id": null,
    "embed_title": "👋 Willkommen auf {server}!",
    "embed_description": "Hallo {mention}! Willkommen auf **{server}**! Du bist Mitglied #{count}.",
    "embed_color": "#22c55e",
    "embed_image": "",
    "embed_thumbnail": true,
    "embed": true,
    "mention": true,
    "add_roles": [],
    "dm_enabled": false,
    "dm_description": ""
  },
  "leave": {
    "enabled": false,
    "channel_id": null,
    "embed_title": "👋 Auf Wiedersehen!",
    "embed_description": "**{user}** hat den Server verlassen. Wir haben jetzt {count} Mitglieder.",
    "embed_color": "#ef4444",
    "embed_image": "",
    "embed": true
  },
  "sticky_roles": [],
  "temp_voice": {
    "enabled": false,
    "category_id": null,
    "hub_channel_id": null,
    "name_template": "🔊 {user}'s Kanal",
    "panel_message_id": null,
    "panel_channel_id": null
  },
  "no_prefix": false,
  "no_prefix_users": [],
  "report_channel": null,
  "auto_slowmode": {
    "enabled": false,
    "channels": [],
    "thresholds": {
      "30": 5,
      "60": 15,
      "100": 30
    }
  },
  "auto_responses": [],
  "invite_tracking": {
    "enabled": false,
    "channel_id": null
  },
  "log_filters": {},
  "auto_ban_appeal": {
    "enabled": false
  },
  "anti_vpn": {
    "enabled": false,
    "action": "kick",
    "whitelist_ids": []
  },
  "dashboard_theme": "purple",
  "dashboard_onboarding": {
    "wizard_popup_seen": false,
    "wizard_popup_seen_at": null,
    "wizard_profile": null
  },
  "badge_automation": {
    "enabled": true,
    "message_badge_enabled": true,
    "message_threshold": 100,
    "message_badge_id": "message_100",
    "invite_badge_enabled": true,
    "invite_threshold": 10,
    "invite_badge_id": "invite_10",
    "one_year_enabled": true,
    "one_year_days": 365,
    "one_year_badge_id": "member_one_year",
    "booster_enabled": true,
    "booster_badge_id": "server_booster"
  },
  "server_tag": {
    "enabled": false,
    "tag": null,
    "reward_role": null
  },
  "auto_nickname": {
    "enabled": false,
    "rules": []
  },
  "webhook_logging": {
    "enabled": false,
    "webhooks": {}
  },
  "public_page": {
    "enabled": false,
    "invite_url": null
  },
  "birthday": {
    "enabled": false,
    "channel_id": null,
    "role_id": null
  },
  "nuke_protection": {
    "enabled": true,
    "auto_backup_on_nuke": true,
    "auto_restore_on_nuke": false,
    "channel_mass_delete_limit": 3,
    "role_mass_delete_limit": 3,
    "bot_mass_add_limit": 3,
    "emoji_mass_delete_limit": 5,
    "category_mass_create_limit": 3,
    "voice_mass_delete_limit": 3,
    "invite_mass_delete_limit": 5,
    "window": 15,
    "auto_restore_channels": true,
    "auto_restore_roles": true,
    "nuke_attempt_permaban_threshold": 3,
    "freeze_perms_on_nuke": true,
    "alert_all_admins": true,
    "emergency_contacts": [],
    "nuke_whitelist": []
  },
  "server_protection": {
    "enabled": true,
    "vanity_url_protect": true,
    "server_icon_protect": true,
    "server_banner_protect": true,
    "server_transfer_protect": true,
    "webhook_spam_limit": 5,
    "webhook_spam_window": 10,
    "auto_regen_webhooks": true,
    "bot_approval_required": false,
    "bot_approval_channel": null,
    "approved_bots": [],
    "admin_perm_monitor": true,
    "role_hierarchy_protect": true,
    "channel_topic_spam_limit": 5,
    "suspicious_time_start": 2,
    "suspicious_time_end": 6
  },
  "raid_detection": {
    "multi_server": true,
    "countdown_warning": true,
    "countdown_seconds": 60,
    "timezone_detection": true
  },
  "leak_protection": {
    "enabled": true,
    "token_leak_scan": true,
    "webhook_url_leak_scan": true,
    "ip_leak_scan": true
  },
  "verify_extended": {
    "math_captcha": false,
    "quiz_mode": false,
    "quiz_questions": [],
    "multi_step": false,
    "steps": [],
    "timer_enabled": false,
    "timer_minutes": 10,
    "timer_action": "kick",
    "role_progression": false,
    "progression_roles": [],
    "bypass_trusted_servers": [],
    "bypass_account_age_days": 90,
    "reverify_days": 0,
    "level_system": false,
    "log_channel": null,
    "failed_counter_limit": 5,
    "failed_action": "kick",
    "rate_limit_per_minute": 3,
    "anti_alt_account": true,
    "anti_alt_min_age_hours": 24,
    "trust_score_enabled": true,
    "trust_score_min": 30,
    "blacklist_ids": [],
    "whitelist_ids": [],
    "admin_approval_required": false,
    "admin_approval_channel": null,
    "custom_questions": [],
    "embed_title": "✅ Verifizierung",
    "embed_description": "Klicke den Button um dich zu verifizieren.",
    "embed_color": "#4169E1",
    "button_label": "Verifizieren",
    "button_emoji": "✅",
    "dropdown_mode": false,
    "dropdown_options": []
  },
  "ticket_extended": {
    "categories": [],
    "priority_enabled": true,
    "priority_levels": [
      "low",
      "medium",
      "high",
      "urgent"
    ],
    "assignment_enabled": true,
    "escalation_enabled": false,
    "escalation_minutes": 60,
    "escalation_role": null,
    "sla_enabled": false,
    "sla_minutes": 120,
    "auto_close_hours": 48,
    "auto_archive": true,
    "transcript_format": "html",
    "satisfaction_survey": true,
    "response_tracking": true,
    "tag_system": true,
    "tags": [],
    "canned_responses": [],
    "templates": [],
    "thread_mode": false,
    "forum_mode": false,
    "max_open_per_user": 3,
    "claim_system": true,
    "color_coding": {
      "low": "#22c55e",
      "medium": "#f59e0b",
      "high": "#ef4444",
      "urgent": "#dc2626"
    },
    "duplicate_detection": true,
    "faq_suggestions": []
  },
  "automod_extended": {
    "leetspeak_filter": true,
    "homoglyph_filter": true,
    "zero_width_filter": true,
    "invisible_char_filter": true,
    "spoiler_abuse_filter": true,
    "codeblock_abuse_filter": true,
    "markdown_spam_filter": true,
    "ascii_art_filter": true,
    "copypasta_filter": true,
    "copypasta_min_length": 500,
    "image_spam_limit": 5,
    "image_spam_window": 30,
    "gif_spam_limit": 5,
    "sticker_spam_limit": 5,
    "embed_spam_limit": 3,
    "link_spam_limit": 3,
    "link_spam_window": 10,
    "phishing_live_db": true,
    "crypto_scam_filter": true,
    "gambling_filter": true,
    "nsfw_link_filter": true,
    "token_grabber_filter": true,
    "ip_logger_filter": true,
    "fake_nitro_filter": true,
    "fake_giveaway_filter": true,
    "typosquat_filter": true,
    "self_harm_filter": true,
    "self_harm_response": "Wenn du Hilfe brauchst: Telefonseelsorge 0800 111 0 111",
    "doxxing_filter": true,
    "impersonation_filter": true,
    "account_age_filter_hours": 0,
    "message_length_max": 0,
    "char_repeat_max": 20,
    "word_repeat_max": 10,
    "rapid_message_limit": 10,
    "rapid_message_window": 5,
    "cross_channel_spam_limit": 5,
    "cross_channel_spam_window": 10,
    "ad_filter": true,
    "ad_keywords": [
      "buy",
      "sell",
      "cheap",
      "discount",
      "free robux",
      "free nitro"
    ]
  },
  "stats_system": {
    "enabled": false,
    "track_messages": true,
    "track_voice": true,
    "track_joins": true,
    "track_commands": true,
    "heatmap_enabled": true,
    "retention_days": 90
  },
  "admin_extended": {
    "panic_button_enabled": true,
    "panic_action": "lockdown",
    "emergency_mode": false,
    "scheduler_tasks": [],
    "reminders": [],
    "health_check_channel": null
  },
  "dashboard_extended": {
    "theme": "dark",
    "accent_color": "#7c3aed",
    "custom_css": "",
    "large_text": false,
    "high_contrast": false,
    "reduced_motion": false,
    "language": "de"
  }
});

const FEATURES = [
  { name: 'Anti-Raid', icon: '🚨', description: 'Schützt deinen Server vor Join-Raids.' },
  { name: 'Anti-Nuke', icon: '💥', description: 'Stoppt gefährliche Admin-Aktionen.' },
  { name: 'AutoMod', icon: '🤖', description: 'Filtert Spam, Scam, Invites und Regelverstöße.' },
  { name: 'Tickets', icon: '🎫', description: 'Support-Tickets direkt im Server.' },
  { name: 'Verification', icon: '✅', description: 'Captcha oder One-Click Verifizierung.' },
  { name: 'Dashboard', icon: '📊', description: 'Komfortable Verwaltung über Weboberfläche.' },
];

const CMDS_PREVIEW = [
  '/ban', '/kick', '/warn', '/mute', '/unmute', '/case', '/cases', '/history', '/modstats',
  '/setup', '/doctor', '/panic', '/snapshot', '/ticket_panel', '/setup_verify', '/backup_create'
];

class ActivityBuffer {
  constructor(size = 200) {
    this.size = size;
    this.items = [];
  }
  push(type, message, data = {}) {
    this.items.unshift({ type, message, data, ts: new Date().toISOString() });
    if (this.items.length > this.size) this.items.length = this.size;
  }
  snapshot(limit = 20) {
    return this.items.slice(0, limit);
  }
}
const ACTIVITY = new ActivityBuffer();

function devPrint(message, level = 'info', area = 'Core') {
  const icons = { debug: '🔎', info: 'ℹ️', success: '✅', ok: '✅', done: '✅', warning: '⚠️', warn: '⚠️', error: '❌', err: '❌', fail: '❌', critical: '🚨' };
  const icon = icons[level] || icons.info;
  const ts = new Date().toLocaleTimeString('de-DE', { hour12: false });
  console.log(`${icon} ${ts} ${String(level).toUpperCase().padEnd(7)} ${String(area).padEnd(22)} │ ${message}`);
}

function devBanner(title, ...args) {
  let level = 'info';
  let area = 'Startup';
  const lines = [];
  for (const arg of args) {
    if (typeof arg === 'string') lines.push(arg);
  }
  if (args.length >= 2 && ['info', 'success', 'warning', 'error'].includes(args[args.length - 2])) level = args[args.length - 2];
  if (typeof args[args.length - 1] === 'string' && ['Startup', 'Ready', 'Cogs', 'Commands', 'DB'].includes(args[args.length - 1])) area = args[args.length - 1];
  const clean = lines.filter((line) => !['info', 'success', 'warning', 'error', 'Startup', 'Ready', 'Cogs', 'Commands', 'DB'].includes(line));
  const width = Math.max(title.length, ...clean.map((l) => l.length), 10) + 4;
  devPrint(`╔${'═'.repeat(width)}╗`, level, area);
  devPrint(`║  ${title.padEnd(width - 2)}║`, level, area);
  for (const line of clean) devPrint(`║  ${line.padEnd(width - 2)}║`, level, area);
  devPrint(`╚${'═'.repeat(width)}╝`, level, area);
}

module.exports = {
  BOT_START_TIME,
  EXTRA_UPTIME,
  getUptime,
  BOT_TOKEN,
  COLOR_PRIMARY,
  COLOR_SUCCESS,
  COLOR_WARNING,
  COLOR_DANGER,
  COLOR_INFO,
  COLOR_PURPLE,
  FOOTER_TEXT,
  FOOTER_ICON,
  VERIFY_BANNER_URL,
  E,
  VALID_PUNISHMENTS,
  LOG_MODULES,
  LOG_MODULES_EXTRA,
  LOG_MODS,
  SCAM_DOMAINS,
  URL_SHORTENERS,
  BADGES,
  DEFAULT_CONFIG,
  FEATURES,
  CMDS_PREVIEW,
  ACTIVITY,
  devPrint,
  devBanner,
};
