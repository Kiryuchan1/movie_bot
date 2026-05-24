import logging
import time
from aiohttp import web
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

logger = logging.getLogger(__name__)


REQUESTS_TOTAL = Counter(
    "bot_requests_total",
    "Загальна кількість запитів до бота",
    ["status"],   
)

USERS_REGISTERED = Counter(
    "bot_users_registered_total",
    "Кількість зареєстрованих користувачів",
)

GEMINI_ERRORS = Counter(
    "bot_gemini_errors_total",
    "Помилки при зверненні до Gemini API",
)

RATE_LIMIT_HITS = Counter(
    "bot_rate_limit_hits_total",
    "Скільки разів користувачі упиралися в ліміт",
)

GEMINI_RESPONSE_TIME = Histogram(
    "bot_gemini_response_seconds",
    "Час відповіді Gemini API у секундах",
    buckets=[1, 2, 3, 5, 8, 13, 21, 30],
)

ACTIVE_USERS_GAUGE = Gauge(
    "bot_active_users_last_hour",
    "Унікальних користувачів за останню годину",
)

BOT_UP = Gauge(
    "bot_up",
    "1 якщо бот працює, 0 якщо ні",
)

BOT_UP.set(1)



class GeminiTimer:
    async def __aenter__(self):
        self._start = time.time()
        return self

    async def __aexit__(self, exc_type, *_):
        elapsed = time.time() - self._start
        GEMINI_RESPONSE_TIME.observe(elapsed)
        if exc_type:
            GEMINI_ERRORS.inc()
        return False



async def metrics_handler(request: web.Request) -> web.Response:
    data = generate_latest()
    return web.Response(
        body=data,
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


async def health_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def start_metrics_server(port: int = 8000):
    app = web.Application()
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Сервер метрик запущено на порту {port} → http://localhost:{port}/metrics")