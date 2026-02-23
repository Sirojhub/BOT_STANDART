import aiosqlite
import logging
import os
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Ensure data directory exists
os.makedirs("data", exist_ok=True)
DB_NAME = "data/bot.db"

def get_db_path():
    return DB_NAME

async def create_users_table():
    """
    Initialize the database and ensure the users table exists with all required columns.
    Renamed from init_db to maintain compatibility with main.py.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        try:
            # Create table if it doesn't exist
            await db.execute("""
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
                    is_offer_accepted BOOLEAN DEFAULT 0,
                    registration_complete BOOLEAN DEFAULT 0,
                    last_active TIMESTAMP,
                    is_premium BOOLEAN DEFAULT 0,
                    is_banned BOOLEAN DEFAULT 0,
                    referral_balance INTEGER DEFAULT 0,
                    referrer_id INTEGER,
                    test_used BOOLEAN DEFAULT 0,
                    is_tg_premium BOOLEAN DEFAULT 0
                )
            """)

            # Create bot_settings table for global configurations (e.g., AD text)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Initialize default ad_text if missing
            async with db.execute("SELECT key FROM bot_settings WHERE key = 'ad_text'") as cursor:
                if not await cursor.fetchone():
                    await db.execute(
                        "INSERT INTO bot_settings (key, value) VALUES ('ad_text', ?)",
                        ("Reklama joyi uchun: @admin",)
                    )
            
            # Check for missing columns and add them (Migration logic)
            async with db.execute("PRAGMA table_info(users)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
            
            # List of columns to check and add if missing
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
                "is_banned": "BOOLEAN DEFAULT 0",
                "daily_scans": "INTEGER DEFAULT 0",
                "referral_balance": "INTEGER DEFAULT 0",
                "referrer_id": "INTEGER",
                "test_used": "BOOLEAN DEFAULT 0",
                "is_tg_premium": "BOOLEAN DEFAULT 0"
            }

            for col, dtype in required_columns.items():
                if col not in columns:
                    try:
                        await db.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                        logger.info(f"Added missing column '{col}' to users table.")
                    except Exception as e:
                        logger.error(f"Error adding column {col}: {e}")

            # Create Index on referrer_id for faster referral lookups
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_referrer ON users (referrer_id)")

            await db.commit()
            logger.info(f"✅ Database initialized successfully at {DB_NAME}.")
            
        except Exception as e:
            logger.error(f"Critical database initialization error: {e}")

async def is_registered(user_id: int) -> bool:
    """Check if a user has completed registration."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT registration_complete, phone FROM users WHERE user_id = ?", 
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return bool(row['registration_complete']) or bool(row['phone'])
                return False
    except Exception as e:
        logger.error(f"Error in is_registered for {user_id}: {e}")
        return False

async def update_last_active(user_id: int):
    """Update the last_active timestamp for a user."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                "UPDATE users SET last_active = CURRENT_TIMESTAMP WHERE user_id = ?", 
                (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Error updating last_active for {user_id}: {e}")

async def save_webapp_data(user_id: int, full_name: str, region: str, district: str, mahalla: str, age: int) -> bool:
    """
    Save or update user data received from the Web App.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            # Check if user exists
            async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                exists = await cursor.fetchone()

            if exists:
                # Update existing user
                await db.execute("""
                    UPDATE users 
                    SET full_name=?, region=?, district=?, mahalla=?, age=?, is_offer_accepted=1, status='verified', last_active=CURRENT_TIMESTAMP
                    WHERE user_id=?
                """, (full_name, region, district, mahalla, age, user_id))
            else:
                # Insert new user
                await db.execute("""
                    INSERT INTO users (user_id, full_name, region, district, mahalla, age, is_offer_accepted, status, registration_complete, created_at, last_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 'verified', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (user_id, full_name, region, district, mahalla, age))
            
            await db.commit()
            logger.info(f"Saved Web App data for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving Web App data for user {user_id}: {e}")
            return False

async def update_user_phone(user_id: int, phone: str) -> bool:
    """
    Update the user's phone number and mark registration as complete.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "UPDATE users SET phone=?, registration_complete=1, last_active=CURRENT_TIMESTAMP WHERE user_id=?", 
                (phone, user_id)
            )
            await db.commit()
            logger.info(f"Updated phone and registration status for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating phone for user {user_id}: {e}")
            return False

async def get_user(user_id: int):
    """
    Retrieve a user by ID.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def add_user(user_id: int, full_name: str, language: str, status: str, is_offer_accepted: bool = True, region: Optional[str] = None, district: Optional[str] = None, age: Optional[int] = None, referrer_id: Optional[int] = None):
    """
    Legacy function wrapper to maintain compatibility if called from other modules.
    Delegates to appropriate logic or basic insert.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("""
                INSERT OR REPLACE INTO users (user_id, full_name, language, status, is_offer_accepted, region, district, age, last_active, referrer_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, COALESCE((SELECT created_at FROM users WHERE user_id=?), CURRENT_TIMESTAMP))
            """, (user_id, full_name, language, status, is_offer_accepted, region, district, age, referrer_id, user_id))
            await db.commit()
        except Exception as e:
            logger.error(f"Error in add_user for {user_id}: {e}")

async def update_referral_balance(user_id: int, amount: int) -> bool:
    """Add (or subtract) amount to user's referral balance."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET referral_balance = referral_balance + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error in update_referral_balance for {user_id}: {e}")
        return False

async def get_user_balance(user_id: int) -> int:
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT referral_balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row['referral_balance'] if row else 0
    except Exception as e:
        logger.error(f"Error in get_user_balance for {user_id}: {e}")
        return 0

async def set_test_used(user_id: int) -> bool:
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("UPDATE users SET test_used = 1, is_premium = 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error in set_test_used for {user_id}: {e}")
        return False

async def activate_premium(user_id: int, duration_days: int = 30) -> bool:
    """Activate premium and handle referrer cashback."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Activate premium
            await db.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (user_id,))
            
            # Get referrer
            async with db.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                referrer_id = row[0] if row else None
                
            # Cashback (1000 UZS)
            if referrer_id:
                await db.execute("UPDATE users SET referral_balance = referral_balance + 1000 WHERE user_id = ?", (referrer_id,))
                
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error in activate_premium for {user_id}: {e}")
        return False

async def get_user_pricing_info(user_id: int):
    """Get info needed for Plans Web App."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT referral_balance, is_premium, test_used, is_tg_premium FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "balance": row[0],
                    "is_premium": bool(row[1]),
                    "test_used": bool(row[2]),
                    "is_tg_premium": bool(row[3])
                }
            return None

# --- Admin Panel Functions ---

async def get_admin_statistics() -> dict:
    """
    Get complete statistics for admin dashboard
    """
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Total users
            cursor = await db.execute("SELECT COUNT(*) FROM users")
            total_users = (await cursor.fetchone())[0]
            
            # Premium users
            cursor = await db.execute(
                "SELECT COUNT(*) FROM users WHERE is_premium = 1"
            )
            premium_users = (await cursor.fetchone())[0]
            
            # Today's registrations
            today_registrations = 0
            try:
                cursor = await db.execute(
                    """SELECT COUNT(*) FROM users 
                       WHERE DATE(created_at) = DATE('now')"""
                )
                today_registrations = (await cursor.fetchone())[0]
            except Exception:
                today_registrations = 0
            
            # Regional breakdown
            cursor = await db.execute(
                """SELECT region, COUNT(*) as count 
                   FROM users 
                   WHERE region IS NOT NULL AND region != ''
                   GROUP BY region 
                   ORDER BY count DESC"""
            )
            regional_data = await cursor.fetchall()
            regional_stats = {row[0]: row[1] for row in regional_data}
            
            return {
                "total_users": total_users,
                "premium_users": premium_users,
                "today_registrations": today_registrations,
                "regional_stats": regional_stats
            }
    except Exception as e:
        logger.error(f"Error in get_admin_statistics: {e}")
        return {"total_users": 0, "premium_users": 0, "today_registrations": 0, "regional_stats": {}}

async def get_users_paginated(page: int = 1, search: str = "", limit: int = 20) -> dict:
    """
    Return paginated user list with optional search.
    """
    offset = (page - 1) * limit
    search_query = f"%{search}%"
    
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Count total matches
            async with db.execute(
                """
                SELECT COUNT(*) FROM users 
                WHERE full_name LIKE ? OR username LIKE ? OR CAST(user_id AS TEXT) LIKE ?
                """, 
                (search_query, search_query, search_query)
            ) as cursor:
                total_records = (await cursor.fetchone())[0]
                
            # Fetch records
            users = []
            async with db.execute(
                """
                SELECT u.user_id, u.full_name, u.region, u.is_premium, u.is_banned, r.full_name, u.referrer_id
                FROM users u
                LEFT JOIN users r ON u.referrer_id = r.user_id
                WHERE u.full_name LIKE ? OR u.username LIKE ? OR CAST(u.user_id AS TEXT) LIKE ?
                ORDER BY u.user_id DESC 
                LIMIT ? OFFSET ?
                """,
                (search_query, search_query, search_query, limit, offset)
            ) as cursor:
                async for row in cursor:
                    users.append({
                        'user_id': row[0],
                        'full_name': row[1] or "No Name",
                        'region': row[2] or "Unknown",
                        'is_premium': bool(row[3]),
                        'is_banned': bool(row[4]),
                        'referrer_name': row[5], # Can be None
                        'referrer_id': row[6]    # Can be None
                    })
                    
            return {
                'users': users,
                'total': total_records,
                'pages': (total_records + limit - 1) // limit
            }
    except Exception as e:
        logger.error(f"Error in get_users_paginated: {e}")
        return {'users': [], 'total': 0, 'pages': 0}

async def toggle_user_premium(user_id: int) -> bool:
    """Toggle premium status, return new status."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            # Get current status
            async with db.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row: return False
                current_status = bool(row[0])
                
            new_status = not current_status
            await db.execute("UPDATE users SET is_premium = ? WHERE user_id = ?", (new_status, user_id))
            await db.commit()
            return new_status
    except Exception as e:
        logger.error(f"Error in toggle_user_premium for {user_id}: {e}")
        return False

async def ban_user(user_id: int) -> bool:
    """Toggle ban status, return new status."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if not row: return False
                current_status = bool(row[0])
                
            new_status = not current_status
            await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, user_id))
            await db.commit()
            return new_status
    except Exception as e:
        logger.error(f"Error in ban_user for {user_id}: {e}")
        return False

async def get_all_user_ids(premium_only: bool = False) -> list[int]:
    """Get list of user IDs for broadcasting."""
    query = "SELECT user_id FROM users"
    if premium_only:
        query += " WHERE is_premium = 1"
        
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute(query) as cursor:
                return [row[0] for row in await cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error in get_all_user_ids: {e}")
    return []

async def get_ad_text() -> str:
    """Get current global ad text."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute("SELECT value FROM bot_settings WHERE key = 'ad_text'") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else "Reklama joyi uchun: @admin"
    except Exception as e:
        logger.error(f"Error in get_ad_text: {e}")
        return "Reklama joyi uchun: @admin"

async def update_ad_text(new_text: str) -> bool:
    """Update global ad text."""
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT OR REPLACE INTO bot_settings (key, value, updated_at) VALUES ('ad_text', ?, CURRENT_TIMESTAMP)",
                (new_text,)
            )
            await db.commit()
            return True
        except Exception as e:
            logger.error(f"Error in update_user_phone: {e}")
            return False

async def reset_daily_stats():
    """Reset daily statistics (e.g., daily_scans) for all users."""
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            # Assumes 'daily_scans' column exists (added in create_users_table)
            await db.execute("UPDATE users SET daily_scans = 0")
            await db.commit()
            logger.info("Daily stats (daily_scans) reset to 0.")
        except Exception as e:
            logger.error(f"Error resetting daily stats: {e}")

