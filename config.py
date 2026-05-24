import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "movie_bot")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", 5))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", 3600))

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

HISTORY_CONTEXT_COUNT = 5

MIN_AGE = 6
MAX_AGE = 120

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не задано у .env")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY не задано у .env")