import logging
import os
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Database Configuration ────────────────────────────────────────────────
# If DATABASE_URL is set (Render PostgreSQL), use PostgreSQL.
# Otherwise, fall back to SQLite for local development.
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import aiopg
    logger.info("🐘 Using PostgreSQL database")
else:
    import aiosqlite
    logger.info("📁 Using SQLite database (local dev)")

DB_NAME = "bot_standart.db"  # SQLite fallback

# ── Connection Helpers ────────────────────────────────────────────────────
_pg_pool = None

async def _get_pg_pool():
    """Get or create PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None or _pg_pool.closed:
        _pg_pool = await aiopg.create_pool(DATABASE_URL, minsize=1, maxsize=5)
    return _pg_pool

async def close_db_pool():
    """Close PostgreSQL connection pool (call on shutdown)."""
    global _pg_pool
    if _pg_pool and not _pg_pool.closed:
        _pg_pool.close()
        await _pg_pool.wait_closed()
        _pg_pool = None

class DBConnection:
    """
    Context manager that works with both PostgreSQL and SQLite.
    Usage:
        async with DBConnection() as (conn, cur):
            await cur.execute(...)
            rows = await cur.fetchall()
    """
    def __init__(self):
        self._conn = None
        self._cur = None
        self._sqlite_db = None

    async def __aenter__(self):
        if USE_POSTGRES:
            pool = await _get_pg_pool()
            self._conn = await pool.acquire()
            self._cur = await self._conn.cursor()
            return (self._conn, self._cur)
        else:
            self._sqlite_db = await aiosqlite.connect(DB_NAME)
            return (self._sqlite_db, self._sqlite_db)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if USE_POSTGRES:
            if self._cur:
                self._cur.close()
            if self._conn:
                pool = await _get_pg_pool()
                pool.release(self._conn)
        else:
            if self._sqlite_db:
                await self._sqlite_db.close()


def q(sql: str) -> str:
    """Convert SQLite-style ? placeholders to PostgreSQL %s if needed."""
    if USE_POSTGRES:
        return sql.replace("?", "%s")
    return sql


# ── Database Initialization ──────────────────────────────────────────────
async def create_users_table():
    """Initialize the database and ensure the users table exists with all required columns."""
    async with DBConnection() as (conn, cur):
        try:
            if USE_POSTGRES:
                # PostgreSQL schema
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        full_name TEXT,
                        region TEXT,
                        district TEXT,
                        mahalla TEXT,
                        age INTEGER,
                        phone TEXT,
                        language TEXT DEFAULT 'uz',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT,
                        is_offer_accepted BOOLEAN DEFAULT FALSE,
                        registration_complete BOOLEAN DEFAULT FALSE,
                        last_active TIMESTAMP,
                        is_premium BOOLEAN DEFAULT FALSE,
                        is_banned BOOLEAN DEFAULT FALSE
                    )
                """)

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Initialize default ad text
                await cur.execute("""
                    INSERT INTO bot_settings (key, value) 
                    VALUES ('ad_text', '📢 Premium obuna: @GvardAdmin')
                    ON CONFLICT (key) DO NOTHING
                """)

                # Commit
                await conn.commit() if hasattr(conn, 'commit') else None

            else:
                # SQLite schema
                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        full_name TEXT,
                        region TEXT,
                        district TEXT,
                        mahalla TEXT,
                        age INTEGER,
                        phone TEXT,
                        language TEXT DEFAULT 'uz',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT,
                        is_offer_accepted BOOLEAN DEFAULT 0
                    )
                """)

                # Migration: add missing columns
                async with conn.execute("PRAGMA table_info(users)") as cursor:
                    columns = [row[1] for row in await cursor.fetchall()]

                required_columns = {
                    "region": "TEXT",
                    "district": "TEXT",
                    "mahalla": "TEXT",
                    "age": "INTEGER",
                    "phone": "TEXT",
                    "is_offer_accepted": "BOOLEAN DEFAULT 0",
                    "status": "TEXT",
                    "registration_complete": "BOOLEAN DEFAULT 0",
                    "last_active": "TIMESTAMP",
                    "is_premium": "BOOLEAN DEFAULT 0",
                    "is_banned": "BOOLEAN DEFAULT 0"
                }

                for col, dtype in required_columns.items():
                    if col not in columns:
                        try:
                            await conn.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                            logger.info(f"Added missing column '{col}' to users table.")
                        except Exception as e:
                            logger.error(f"Error adding column {col}: {e}")

                await cur.execute("""
                    CREATE TABLE IF NOT EXISTS bot_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                await cur.execute(
                    "INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('ad_text', '📢 Premium obuna: @GvardAdmin')"
                )

                await conn.commit()

            logger.info("✅ Database initialized successfully.")

        except Exception as e:
            logger.error(f"Critical database initialization error: {e}")


# ── User Queries ─────────────────────────────────────────────────────────

async def is_registered(user_id: int) -> bool:
    """Check if a user has completed registration."""
    async with DBConnection() as (conn, cur):
        await cur.execute(
            q("SELECT registration_complete, phone FROM users WHERE user_id = ?"),
            (user_id,)
        )
        row = await cur.fetchone()
        if row:
            return bool(row[0]) or bool(row[1])
        return False


async def update_last_active(user_id: int):
    """Update the last_active timestamp for a user."""
    async with DBConnection() as (conn, cur):
        try:
            await cur.execute(
                q("UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?"),
                (user_id,)
            )
            if USE_POSTGRES:
                pass  # autocommit via pool
            else:
                await conn.commit()
        except Exception as e:
            logger.error(f"Error updating last_active for {user_id}: {e}")


async def save_webapp_data(user_id: int, full_name: str, region: str, district: str, mahalla: str, age: int) -> bool:
    """Save or update user data received from the Web App."""
    async with DBConnection() as (conn, cur):
        try:
            await cur.execute(
                q("SELECT user_id FROM users WHERE user_id = ?"),
                (user_id,)
            )
            exists = await cur.fetchone()

            if USE_POSTGRES:
                if exists:
                    await cur.execute(q("""
                        UPDATE users 
                        SET full_name=?, region=?, district=?, mahalla=?, age=?, 
                            is_offer_accepted=TRUE, status='verified', last_active=CURRENT_TIMESTAMP
                        WHERE user_id=?
                    """), (full_name, region, district, mahalla, age, user_id))
                else:
                    await cur.execute(q("""
                        INSERT INTO users (user_id, full_name, region, district, mahalla, age, 
                                           is_offer_accepted, status, created_at, last_active)
                        VALUES (?, ?, ?, ?, ?, ?, TRUE, 'verified', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """), (user_id, full_name, region, district, mahalla, age))
            else:
                if exists:
                    await cur.execute("""
                        UPDATE users 
                        SET full_name=?, region=?, district=?, mahalla=?, age=?, 
                            is_offer_accepted=1, status='verified', last_active=CURRENT_TIMESTAMP
                        WHERE user_id=?
                    """, (full_name, region, district, mahalla, age, user_id))
                else:
                    await cur.execute("""
                        INSERT INTO users (user_id, full_name, region, district, mahalla, age, 
                                           is_offer_accepted, status, created_at, last_active)
                        VALUES (?, ?, ?, ?, ?, ?, 1, 'verified', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (user_id, full_name, region, district, mahalla, age))

            if not USE_POSTGRES:
                await conn.commit()

            logger.info(f"Saved Web App data for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error saving Web App data for user {user_id}: {e}")
            return False


async def update_user_phone(user_id: int, phone: str) -> bool:
    """Update the user's phone number and mark registration as complete."""
    async with DBConnection() as (conn, cur):
        try:
            if USE_POSTGRES:
                await cur.execute(
                    q("UPDATE users SET phone=?, registration_complete=TRUE, last_active=CURRENT_TIMESTAMP WHERE user_id=?"),
                    (phone, user_id)
                )
            else:
                await cur.execute(
                    "UPDATE users SET phone=?, registration_complete=1, last_active=CURRENT_TIMESTAMP WHERE user_id=?",
                    (phone, user_id)
                )
                await conn.commit()
            logger.info(f"Updated phone and registration status for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating phone for user {user_id}: {e}")
            return False


async def get_user(user_id: int):
    """Retrieve a user by ID."""
    async with DBConnection() as (conn, cur):
        await cur.execute(q("SELECT * FROM users WHERE user_id = ?"), (user_id,))
        return await cur.fetchone()


async def add_user(user_id: int, full_name: str, language: str, status: str, 
                   is_offer_accepted: bool = True, region: str = None, 
                   district: str = None, age: int = None):
    """Legacy function wrapper to maintain compatibility."""
    async with DBConnection() as (conn, cur):
        try:
            if USE_POSTGRES:
                await cur.execute(q("""
                    INSERT INTO users (user_id, full_name, language, status, is_offer_accepted, region, district, age, last_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        language = EXCLUDED.language,
                        status = EXCLUDED.status,
                        is_offer_accepted = EXCLUDED.is_offer_accepted,
                        region = EXCLUDED.region,
                        district = EXCLUDED.district,
                        age = EXCLUDED.age,
                        last_active = CURRENT_TIMESTAMP
                """), (user_id, full_name, language, status, is_offer_accepted, region, district, age))
            else:
                await cur.execute("""
                    INSERT OR REPLACE INTO users (user_id, full_name, language, status, is_offer_accepted, region, district, age, last_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (user_id, full_name, language, status, is_offer_accepted, region, district, age))
                await conn.commit()
        except Exception as e:
            logger.error(f"Error in add_user for {user_id}: {e}")


# ── Admin Panel Functions ────────────────────────────────────────────────

async def get_admin_statistics() -> dict:
    """Get complete statistics for admin dashboard."""
    async with DBConnection() as (conn, cur):
        await cur.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]

        await cur.execute("SELECT COUNT(*) FROM users WHERE is_premium = TRUE" if USE_POSTGRES 
                         else "SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium_users = (await cur.fetchone())[0]

        today_registrations = 0
        try:
            await cur.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = CURRENT_DATE" if USE_POSTGRES
                             else "SELECT COUNT(*) FROM users WHERE DATE(created_at) = DATE('now')")
            today_registrations = (await cur.fetchone())[0]
        except Exception:
            try:
                await cur.execute("SELECT COUNT(*) FROM users WHERE DATE(last_active) = CURRENT_DATE" if USE_POSTGRES
                                 else "SELECT COUNT(*) FROM users WHERE DATE(last_active) = DATE('now')")
                today_registrations = (await cur.fetchone())[0]
            except Exception:
                today_registrations = 0

        await cur.execute("""
            SELECT region, COUNT(*) as count 
            FROM users 
            WHERE region IS NOT NULL
            GROUP BY region 
            ORDER BY count DESC
        """)
        regional_data = await cur.fetchall()
        regional_stats = {row[0]: row[1] for row in regional_data}

        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "today_registrations": today_registrations,
            "regional_stats": regional_stats
        }


async def get_users_paginated(page: int = 1, search: str = "", limit: int = 20) -> dict:
    """Return paginated user list with optional search."""
    offset = (page - 1) * limit
    search_query = f"%{search}%"

    async with DBConnection() as (conn, cur):
        if USE_POSTGRES:
            await cur.execute(q("""
                SELECT COUNT(*) FROM users 
                WHERE full_name LIKE ? OR username LIKE ? OR CAST(user_id AS TEXT) LIKE ?
            """), (search_query, search_query, search_query))
        else:
            await cur.execute("""
                SELECT COUNT(*) FROM users 
                WHERE full_name LIKE ? OR username LIKE ? OR CAST(user_id AS TEXT) LIKE ?
            """, (search_query, search_query, search_query))

        total_records = (await cur.fetchone())[0]

        if USE_POSTGRES:
            await cur.execute(q("""
                SELECT user_id, full_name, region, is_premium, is_banned 
                FROM users 
                WHERE full_name LIKE ? OR username LIKE ? OR CAST(user_id AS TEXT) LIKE ?
                ORDER BY user_id DESC 
                LIMIT ? OFFSET ?
            """), (search_query, search_query, search_query, limit, offset))
        else:
            await cur.execute("""
                SELECT user_id, full_name, region, is_premium, is_banned 
                FROM users 
                WHERE full_name LIKE ? OR username LIKE ? OR CAST(user_id AS TEXT) LIKE ?
                ORDER BY user_id DESC 
                LIMIT ? OFFSET ?
            """, (search_query, search_query, search_query, limit, offset))

        rows = await cur.fetchall()
        users = []
        for row in rows:
            users.append({
                'user_id': row[0],
                'full_name': row[1] or "No Name",
                'region': row[2] or "Unknown",
                'is_premium': bool(row[3]),
                'is_banned': bool(row[4])
            })

        return {
            'users': users,
            'total': total_records,
            'pages': (total_records + limit - 1) // limit
        }


async def toggle_user_premium(user_id: int) -> bool:
    """Toggle premium status, return new status."""
    async with DBConnection() as (conn, cur):
        if USE_POSTGRES:
            await cur.execute(q("SELECT is_premium FROM users WHERE user_id = ?"), (user_id,))
        else:
            await cur.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))

        row = await cur.fetchone()
        if not row:
            return False
        current_status = bool(row[0])

        new_status = not current_status
        if USE_POSTGRES:
            await cur.execute(q("UPDATE users SET is_premium = ? WHERE user_id = ?"), (new_status, user_id))
        else:
            await cur.execute("UPDATE users SET is_premium = ? WHERE user_id = ?", (new_status, user_id))
            await conn.commit()
        return new_status


async def ban_user(user_id: int) -> bool:
    """Toggle ban status, return new status."""
    async with DBConnection() as (conn, cur):
        if USE_POSTGRES:
            await cur.execute(q("SELECT is_banned FROM users WHERE user_id = ?"), (user_id,))
        else:
            await cur.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))

        row = await cur.fetchone()
        if not row:
            return False
        current_status = bool(row[0])

        new_status = not current_status
        if USE_POSTGRES:
            await cur.execute(q("UPDATE users SET is_banned = ? WHERE user_id = ?"), (new_status, user_id))
        else:
            await cur.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, user_id))
            await conn.commit()
        return new_status


async def get_all_user_ids(premium_only: bool = False) -> list[int]:
    """Get list of user IDs for broadcasting."""
    query = "SELECT user_id FROM users"
    if premium_only:
        query += " WHERE is_premium = TRUE" if USE_POSTGRES else " WHERE is_premium = 1"

    async with DBConnection() as (conn, cur):
        await cur.execute(query)
        return [row[0] for row in await cur.fetchall()]


async def get_ad_text() -> str:
    """Get current global ad text."""
    async with DBConnection() as (conn, cur):
        await cur.execute("SELECT value FROM bot_settings WHERE key = 'ad_text'")
        row = await cur.fetchone()
        return row[0] if row else ""


async def update_ad_text(new_text: str) -> bool:
    """Update global ad text."""
    async with DBConnection() as (conn, cur):
        try:
            if USE_POSTGRES:
                await cur.execute(q("""
                    INSERT INTO bot_settings (key, value, updated_at) 
                    VALUES ('ad_text', ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
                """), (new_text, new_text))
            else:
                await cur.execute(
                    "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES ('ad_text', ?, CURRENT_TIMESTAMP)",
                    (new_text,)
                )
                await conn.commit()
            return True
        except Exception:
            return False
