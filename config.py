import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "@HanimeStuffBot")
OWNER_ID = int(os.environ.get("OWNER_ID", "6444277321"))
ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
API_ID = int(os.environ.get("API_ID", "39972638"))
API_HASH = os.environ.get("API_HASH", "77c904291d4f7a61952fac3e81cac08a")
NEON_DB_URL = os.environ.get("NEON_DB_URL", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE = os.environ.get("LOG_FILE", "bot_logs.log")
AUTO_BIO_TEMPLATE = os.environ.get("AUTO_BIO_TEMPLATE", "Auto Broadcast With Multiple Userbots @HanimeStuffBot 🔥")
