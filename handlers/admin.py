from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import WebAppInfo
from database import (
    get_admin_statistics, get_users_paginated, toggle_user_premium, 
    ban_user, get_all_user_ids, get_ad_text, update_ad_text
)
from config import BOT_TOKEN, ADMIN_WEBAPP_URL, ADMIN_MSG_ID
import json
import logging
import hmac
import hashlib
from urllib.parse import parse_qs
from aiohttp import web
import asyncio

router = Router()
logger = logging.getLogger(__name__)

# Use ADMIN_MSG_ID from config/env as the primary admin, or add more hardcoded
try:
    ADMIN_IDS = [int(x) for x in str(ADMIN_MSG_ID).split(',') if x.strip().isdigit()]
except:
    ADMIN_IDS = []
if 1052080030 not in ADMIN_IDS: ADMIN_IDS.append(1052080030) # Ensure default admin

# --- Authentication Logic ---
def verify_telegram_webapp_data(init_data: str, bot_token: str) -> dict:
    """Verify Telegram Web App initData signature."""
    try:
        parsed = parse_qs(init_data)
        received_hash = parsed.get('hash', [''])[0]
        
        data_check_string = '\n'.join(
            f"{k}={v[0]}" for k, v in sorted(parsed.items()) if k != 'hash'
        )
        
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        if received_hash != expected_hash:
            raise ValueError("Invalid hash")
        
        return json.loads(parsed.get('user', ['{}'])[0])
    except Exception as e:
        raise ValueError(f"Authentication failed: {e}")

@web.middleware
async def admin_middleware(request, handler):
    """Middleware to secure admin API routes."""
    if request.method == "OPTIONS":
        return await handler(request)

    # Only secure /api/admin routes
    if not request.path.startswith("/api/admin"):
        return await handler(request)

    init_data = request.headers.get('X-Telegram-Init-Data') or request.headers.get('X-Init-Data')
    
    if not init_data:
        # Development bypass if needed, but strictly require auth for production
        return web.json_response({"success": False, "error": "Missing auth data"}, status=401)
    
    try:
        user_data = verify_telegram_webapp_data(init_data, BOT_TOKEN)
        user_id = user_data.get('id')
        
        if user_id not in ADMIN_IDS:
            return web.json_response({"success": False, "error": "Unauthorized"}, status=403)
        
        request['admin_id'] = user_id
        return await handler(request)
    except ValueError as e:
        return web.json_response({"success": False, "error": str(e)}, status=401)

# --- Command Handler ---
@router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛠 Open Admin Panel", web_app=WebAppInfo(url=ADMIN_WEBAPP_URL))]
    ])
    await message.answer("🔒 Admin Panelga xush kelibsiz.", reply_markup=markup)

# --- API Endpoints ---
async def api_stats(request):
    try:
        stats = await get_admin_statistics()
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"API Error: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_users(request):
    page = int(request.query.get('page', 1))
    search = request.query.get('search', "")
    data = await get_users_paginated(page, search)
    return web.json_response({"success": True, "data": data})

async def handle_toggle_action(request):
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        action = data.get('action') # 'premium' or 'ban'
        
        success = False
        new_status = False
        
        if action == 'premium':
            new_status = await toggle_user_premium(user_id)
            success = True
        elif action == 'ban':
            new_status = await ban_user(user_id)
            success = True
            
        return web.json_response({"success": success, "new_status": new_status})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)

async def api_settings(request):
    text = await get_ad_text()
    return web.json_response({"success": True, "data": {"ad_text": text}})

async def api_update_ad(request):
    try:
        data = await request.json()
        text = data.get('text')
        success = await update_ad_text(text)
        return web.json_response({"success": success})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)

async def api_broadcast(request):
    try:
        data = await request.json()
        message_text = data.get('message')
        target = data.get('target') # all or premium
        
        premium_only = (target == 'premium')
        user_ids = await get_all_user_ids(premium_only)
        
        bot = request.app['bot'] # Access bot instance from app
        count = 0
        for uid in user_ids:
            try:
                await bot.send_message(uid, message_text)
                count += 1
                await asyncio.sleep(0.05) # Rate limit protection
            except:
                pass
        return web.json_response({"success": True, "count": count})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

# --- Routes Setup ---
def setup_admin_routes(app):
    app.router.add_get('/api/admin/stats', api_stats)
    app.router.add_get('/api/admin/users', api_users)
    app.router.add_post('/api/admin/toggle', handle_toggle_action)
    app.router.add_get('/api/admin/settings', api_settings)
    app.router.add_post('/api/admin/ad-update', api_update_ad)
    app.router.add_post('/api/admin/settings/ad', api_update_ad) # Fix for 404 error
    app.router.add_post('/api/admin/broadcast', api_broadcast)
