"""
database.py — Sarhad Bot | asyncpg bilan toza asinxron PostgreSQL

BARCHA MUAMMOLAR HAL QILINDI:
  aiopg + psycopg2 wrapper → asyncpg (native async driver)
  commit() / set_session() / isolation_level → YO'Q (kerak emas)
  ResourceWarning → pool.close() to'liq await qilinadi
"""

import logging
import asyncpg
from typing import Optional

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


# ══════════════════════════════════════════════
# INIT VA CLOSE
# ══════════════════════════════════════════════

async def init_db(dsn: str) -> None:
    """
    asyncpg Pool yaratish + jadvallarni tayyorlash.
    dsn = Render → PostgreSQL → Internal Database URL
    format: postgresql://user:password@host:5432/dbname
    """
    global _pool

    if _pool is not None:
        logger.warning("init_db: pool allaqachon mavjud.")
        return

    try:
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=10,
            command_timeout=30,
            max_inactive_connection_lifetime=300,
        )
        await _create_tables()
        logger.info("✅ asyncpg pool ishga tushirildi.")

    except Exception as e:
        logger.critical(f"❌ init_db xatosi: {e}", exc_info=True)
        raise


async def close_db() -> None:
    """
    Pool'ni xavfsiz yopish.
    pool.close() — graceful, mavjud querylar tugashini kutadi.
    ResourceWarning chiqmasligi uchun await qilinadi.
    """
    global _pool

    if _pool is None:
        return

    try:
        await _pool.close()
    except Exception as e:
        logger.warning(f"pool.close() xatosi: {e}")
    finally:
        _pool = None
        logger.info("✅ asyncpg pool yopildi.")


# ══════════════════════════════════════════════
# ICHKI YORDAMCHI
# ══════════════════════════════════════════════

def _get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError(
            "Pool ishga tushirilmagan! Avval await init_db(dsn) chaqiring."
        )
    return _pool


async def _create_tables() -> None:
    """
    Jadvallar yaratish.
    asyncpg DDL — autocommit. commit() kerak emas.
    """
    pool = _get_pool()

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     BIGINT      PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                language    TEXT        NOT NULL DEFAULT 'uz',
                is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        await conn.execute("""
            DROP TRIGGER IF EXISTS users_updated_at ON users;
            CREATE TRIGGER users_updated_at
                BEFORE UPDATE ON users
                FOR EACH ROW EXECUTE FUNCTION update_updated_at();
        """)

    logger.info("✅ Jadvallar va triggerlar tayyor.")


# ══════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════

async def get_user(user_id: int) -> Optional[dict]:
    """
    Foydalanuvchini ID bo'yicha olish.
    asyncpg: $1, $2 ... (psycopg2 dagi %s emas!)
    fetchrow() → asyncpg.Record | None
    """
    pool = _get_pool()

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT user_id, username, full_name, language, is_active, created_at
                FROM users WHERE user_id = $1
                """,
                user_id
            )
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"DB get_user({user_id}) xatosi: {e}", exc_info=True)
        return None


async def create_user(
    user_id:   int,
    username:  Optional[str],
    full_name: Optional[str],
    language:  str = "uz",
) -> bool:
    """
    Yangi foydalanuvchi yaratish.
    ON CONFLICT DO NOTHING — race condition xavfsiz.
    Returns: True = yangi yaratildi, False = allaqachon bor
    """
    pool = _get_pool()

    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, language)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id) DO NOTHING
                """,
                user_id, username, full_name, language
            )
        # asyncpg: "INSERT 0 1" = qo'shildi, "INSERT 0 0" = conflict
        return result.endswith("1")
    except Exception as e:
        logger.error(f"DB create_user({user_id}) xatosi: {e}", exc_info=True)
        return False


async def update_user_activity(user_id: int, is_active: bool = True) -> None:
    """Foydalanuvchi faolligini yangilash. Trigger updated_at ni o'zi yangilaydi."""
    pool = _get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_active = $1 WHERE user_id = $2",
                is_active, user_id
            )
    except Exception as e:
        logger.error(f"DB update_user_activity({user_id}) xatosi: {e}", exc_info=True)


async def get_all_users_count() -> int:
    """Jami foydalanuvchilar soni (admin statistika uchun)."""
    pool = _get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM users")
        return row["cnt"] if row else 0
    except Exception as e:
        logger.error(f"DB get_all_users_count xatosi: {e}", exc_info=True)
        return 0


async def get_active_users_count() -> int:
    """Faol foydalanuvchilar soni."""
    pool = _get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS cnt FROM users WHERE is_active = TRUE"
            )
        return row["cnt"] if row else 0
    except Exception as e:
        logger.error(f"DB get_active_users_count xatosi: {e}", exc_info=True)
        return 0
