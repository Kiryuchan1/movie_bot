import asyncpg
import logging
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, RATE_LIMIT_WINDOW, RATE_LIMIT_MESSAGES

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            min_size=2, max_size=10,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id  BIGINT PRIMARY KEY,
                username     TEXT,
                gender       TEXT NOT NULL,
                age          INTEGER NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id           SERIAL PRIMARY KEY,
                telegram_id  BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
                user_query   TEXT NOT NULL,
                bot_response TEXT NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_time
            ON messages (telegram_id, created_at DESC);
        """)
    logger.info("БД ініціалізовано успішно")



async def get_user(telegram_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )


async def save_user(telegram_id: int, username: str | None, gender: str, age: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, username, gender, age)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (telegram_id) DO UPDATE
              SET username=$2, gender=$3, age=$4, updated_at=NOW()
        """, telegram_id, username, gender, age)


async def delete_user(telegram_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM users WHERE telegram_id = $1", telegram_id
        )



async def save_message(telegram_id: int, user_query: str, bot_response: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO messages (telegram_id, user_query, bot_response)
            VALUES ($1, $2, $3)
        """, telegram_id, user_query, bot_response)


async def get_recent_history(telegram_id: int, limit: int = 5) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_query, bot_response, created_at
            FROM messages
            WHERE telegram_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """, telegram_id, limit)
    return list(reversed(rows))



async def count_recent_messages(telegram_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS cnt
            FROM messages
            WHERE telegram_id = $1
              AND created_at > NOW() - ($2 || ' seconds')::INTERVAL
        """, telegram_id, str(RATE_LIMIT_WINDOW))
        return row["cnt"]


async def is_rate_limited(telegram_id: int) -> bool:
    return await count_recent_messages(telegram_id) >= RATE_LIMIT_MESSAGES



async def count_active_users_last_hour() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(DISTINCT telegram_id) AS cnt
            FROM messages
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """)
        return row["cnt"]