import aiosqlite
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "bot_standart.db"

async def create_users_table():
    """
    Initialize the database and ensure the users table exists with all required columns.
    Renamed from init_db to maintain compatibility with main.py.
    """
    async with aiosqlite.connect(DB_NAME) as db:
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
                    is_offer_accepted BOOLEAN DEFAULT 0
                )
            """)
            
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
                "is_banned": "BOOLEAN DEFAULT 0"
            }

            for col, dtype in required_columns.items():
                if col not in columns:
                    try:
                        await db.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
                        logger.info(f"Added missing column '{col}' to users table.")
                    except Exception as e:
                        logger.error(f"Error adding column {col}: {e}")

            # Create bot_settings table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Initialize default ad text
            await db.execute("INSERT OR IGNORE INTO bot_settings (key, value) VALUES ('ad_text', '📢 Premium obuna: @GvardAdmin')")

            await db.commit()
            logger.info("Database initialized successfully.")
            
        except Exception as e:
            logger.error(f"Critical database initialization error: {e}")

async def is_registered(user_id: int) -> bool:
    """Check if a user has completed registration."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT registration_complete, phone FROM users WHERE user_id = ?", 
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                # Considered registered if flag is true OR phone is present (legacy support)
                return bool(row[0]) or bool(row[1])
            return False

async def update_last_active(user_id: int):
    """Update the last_active timestamp for a user."""
    async with aiosqlite.connect(DB_NAME) as db:
        try:
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
                    INSERT INTO users (user_id, full_name, region, district, mahalla, age, is_offer_accepted, status, created_at, last_active)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 'verified', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def add_user(user_id: int, full_name: str, language: str, status: str, is_offer_accepted: bool = True, region: str = None, district: str = None, age: int = None):
    """
    Legacy function wrapper to maintain compatibility if called from other modules.
    Delegates to appropriate logic or basic insert.
    """
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute("""
                INSERT OR REPLACE INTO users (user_id, full_name, language, status, is_offer_accepted, region, district, age, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (user_id, full_name, language, status, is_offer_accepted, region, district, age))
            await db.commit()
        except Exception as e:
            logger.error(f"Error in add_user for {user_id}: {e}")

# --- Admin Panel Functions ---

async def get_admin_statistics() -> dict:
    """
    Get complete statistics for admin dashboard
    """
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
        cursor = await db.execute(
            """SELECT COUNT(*) FROM users 
               WHERE DATE(created_at) = DATE('now')"""
        )
        today_registrations = (await cursor.fetchone())[0]
        
        # Regional breakdown
        cursor = await db.execute(
            """SELECT region, COUNT(*) as count 
               FROM users 
               WHERE region IS NOT NULL
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

async def get_users_paginated(page: int = 1, search: str = "", limit: int = 20) -> dict:
    """
    Return paginated user list with optional search.
    """
    offset = (page - 1) * limit
    search_query = f"%{search}%"
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Count total matches
        async with db.execute(
            """
            SELECT COUNT(*) FROM users 
            WHERE full_name LIKE ? OR username LIKE ? OR str(user_id) LIKE ?
            """, 
            (search_query, search_query, search_query)
        ) as cursor:
            total_records = (await cursor.fetchone())[0]
            
        # Fetch records
        users = []
        async with db.execute(
            """
            SELECT user_id, full_name, region, is_premium, is_banned 
            FROM users 
            WHERE full_name LIKE ? OR username LIKE ? OR str(user_id) LIKE ?
            ORDER BY created_at DESC 
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
                    'is_banned': bool(row[4])
                })
                
        return {
            'users': users,
            'total': total_records,
            'pages': (total_records + limit - 1) // limit
        }

async def toggle_user_premium(user_id: int) -> bool:
    """Toggle premium status, return new status."""
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

async def ban_user(user_id: int) -> bool:
    """Toggle ban status, return new status."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row: return False
            current_status = bool(row[0])
            
        new_status = not current_status
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (new_status, user_id))
        await db.commit()
        return new_status

async def get_all_user_ids(premium_only: bool = False) -> list[int]:
    """Get list of user IDs for broadcasting."""
    query = "SELECT user_id FROM users"
    if premium_only:
        query += " WHERE is_premium = 1"
        
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(query) as cursor:
            return [row[0] for row in await cursor.fetchall()]

async def get_ad_text() -> str:
    """Get current global ad text."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key = 'ad_text'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

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
        except Exception:
            return False
