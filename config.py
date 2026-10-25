import os
from pathlib import Path
from dotenv import dotenv_values

# Paths
BASE_DIR = Path(__file__).resolve().parent
HQBOT_ENV_PATH = Path(os.path.expandvars(r"%LOCALAPPDATA%\hermes\profiles\hqbot\.env"))

env_data = {}
if HQBOT_ENV_PATH.exists():
    env_data.update(dotenv_values(HQBOT_ENV_PATH))

LOCAL_ENV_PATH = BASE_DIR / ".env"
if LOCAL_ENV_PATH.exists():
    env_data.update(dotenv_values(LOCAL_ENV_PATH))

NINEROUTER_URL = env_data.get("NINEROUTER_URL", "http://127.0.0.1:20128/v1")
NINEROUTER_KEY = env_data.get("HERMES_CUSTOM_LOCALHOST_20128_API_KEY", "")
DEFAULT_MODEL = env_data.get("AFFILIATE_MODEL", "ag/gemini-3.8-flash-high")

TELEGRAM_BOT_TOKEN = env_data.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = env_data.get("TELEGRAM_ALLOWED_USERS", "")
if "," in TELEGRAM_CHAT_ID:
    TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID.split(",")[0].strip()

# Shopee Affiliate Open API
SHOPEE_APP_ID = env_data.get("SHOPEE_APP_ID", "")
SHOPEE_SECRET = env_data.get("SHOPEE_SECRET", "")

