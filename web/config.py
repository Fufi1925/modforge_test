import os

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
OAUTH2_REDIRECT = os.getenv("OAUTH2_REDIRECT")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
# Wichtig: stabiler Secret-Key, sonst verlieren Browser-Cookies/Admin-Login bei jedem Neustart ihre Gültigkeit.
# Best Practice: SESSION_SECRET explizit setzen. Fallback nutzt DISCORD_CLIENT_SECRET, weil es in Deployments stabil ist.
SESSION_SECRET = os.getenv("SESSION_SECRET") or os.getenv("DISCORD_CLIENT_SECRET") or "modforge-dashboard-session-secret-change-me"
