"""
database.py — Sarhad Bot: Asinxron PostgreSQL operatsiyalar
═══════════════════════════════════════════════════════════
Qoidalar:
  ✅ Faqat aiopg (psycopg2 async wrapper)
  ✅ Pool orqali connection boshqaruv
  ✅ Har bir connection AUTOCOMMIT rejimida
  ❌ commit(), rollback(), set_session() HECH QAERDA YO'Q
"""

import logging
from typing import Optional

import aiopg
import psycopg2.extensions  # faqat ISOLATION_LEVEL_AUTOCOMMIT konstanta uchun

logger = logging.getLogger(__name__)

# ── Global pool ──────────────────────────────────────────────────────────
_pool: Optional[aiopg.Pool] = None


# ── Pool yaratish va yopish ──────────────────────────────────────────────

async def init_db(dsn: str) -> aiopg.Pool:
    """
    PostgreSQL connection pool yaratadi va users jadvalini hosil qiladi.

    Har bir yangi connection uchun ISOLATION_LEVEL_AUTOCOMMIT o'rnatiladi.
    Bu shuni anglatadiki:
      - Har bir cur.execute() natijasi darhol diskka yoziladi
      - commit() chaqirish KERAK EMAS (va chaqirsa XATO beradi)
      - set_session() chaqirish KERAK EMAS (va chaqirsa XATO beradi)
    """
    global _pool

    # Pool yaratish
    # on_connect — har bir yangi raw psycopg2 connection uchun chaqiriladi
    _pool = await aiopg.create_pool(dsn, minsize=1, maxsize=5)

    # Har bir connection'ga autocommit o'rnatish
    # aiopg pool'dan acquire() qilganda internal psycopg2 connection oladi
    # Bu connection'ning isolation_level'ini AUTOCOMMIT qilish kerak
    # Lekin buni pool yaratgandan keyin, birinchi connection orqali qilamiz
    async with _pool.acquire() as conn:
        # aiopg connection'ning ichki psycopg2 connection'iga erishamiz
        # va AUTOCOMMIT rejimini o'rnatamiz
        conn._conn.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
        )
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id    BIGINT PRIMARY KEY,
                    username   TEXT,
                    full_name  TEXT,
                    language   TEXT DEFAULT 'uz',
                    is_active  BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            logger.info("✅ Database initialized — users table ready.")

    return _pool


def _get_pool() -> aiopg.Pool:
    """Pool'ni qaytaradi. None bo'lsa RuntimeError ko'taradi."""
    if _pool is None or _pool.closed:
        raise RuntimeError("Database pool is not initialized. Call init_db() first.")
    return _pool


async def close_db() -> None:
    """Pool'ni yopadi — bot to'xtashida chaqiriladi."""
    global _pool
    if _pool is not None and not _pool.closed:
        _pool.close()
        await _pool.wait_closed()
        logger.info("✅ Database pool closed.")
        _pool = None


# ── Yordamchi: autocommit connection olish ───────────────────────────────

class _AutocommitConnection:
    """
    Context manager: pool'dan connection oladi va AUTOCOMMIT qiladi.

    Ishlatish:
        async with _ac() as (conn, cur):
            await cur.execute("SELECT ...")

    Ichida commit/rollback CHAQIRISH MUMKIN EMAS.
    """

    def __init__(self):
        self._conn = None
        self._cur = None

    async def __aenter__(self):
        pool = _get_pool()
        self._conn = await pool.acquire()
        # AUTOCOMMIT — har bir execute darhol yoziladi
        self._conn._conn.set_isolation_level(
            psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
        )
        self._cur = await self._conn.cursor()
        return self._conn, self._cur

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._cur is not None:
            self._cur.close()
        if self._conn is not None:
            pool = _get_pool()
            pool.release(self._conn)
        return False  # exception'ni qayta ko'taramiz


def _ac() -> _AutocommitConnection:
    """Qisqa nom — autocommit connection context manager."""
    return _AutocommitConnection()


# ── CRUD operatsiyalar ───────────────────────────────────────────────────

async def get_user(user_id: int) -> Optional[dict]:
    """
    Foydalanuvchini user_id bo'yicha topadi.
    Topilmasa None qaytaradi.
    """
    try:
        async with _ac() as (conn, cur):
            await cur.execute(
                "SELECT user_id, username, full_name, language, is_active, "
                "created_at, updated_at FROM users WHERE user_id = %s",
                (user_id,)
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                "user_id": row[0],
                "username": row[1],
                "full_name": row[2],
                "language": row[3],
                "is_active": row[4],
                "created_at": row[5],
                "updated_at": row[6],
            }
    except Exception as e:
        logger.error(f"DB get_user({user_id}) xatosi: {e}", exc_info=True)
        return None


async def create_user(
    user_id: int,
    username: Optional[str],
    full_name: Optional[str],
    language: str = "uz",
) -> bool:
    """
    Yangi foydalanuvchi yaratadi.
    Agar allaqachon mavjud bo'lsa — hech narsa qilmaydi (ON CONFLICT DO NOTHING).
    True — muvaffaqiyatli, False — xato.
    """
    try:
        async with _ac() as (conn, cur):
            await cur.execute(
                """
                INSERT INTO users (user_id, username, full_name, language)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (user_id, username, full_name, language),
            )
            logger.info(f"👤 User created/exists: {user_id} (@{username})")
            return True
    except Exception as e:
        logger.error(f"DB create_user({user_id}) xatosi: {e}", exc_info=True)
        return False


async def update_user_activity(user_id: int, is_active: bool = True) -> None:
    """
    Foydalanuvchining is_active va updated_at maydonlarini yangilaydi.
    """
    try:
        async with _ac() as (conn, cur):
            await cur.execute(
                """
                UPDATE users
                SET is_active = %s, updated_at = NOW()
                WHERE user_id = %s
                """,
                (is_active, user_id),
            )
    except Exception as e:
        logger.error(f"DB update_user_activity({user_id}) xatosi: {e}", exc_info=True)
