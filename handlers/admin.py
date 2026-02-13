from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.types import WebAppInfo
from database import (
    get_admin_statistics, get_users_paginated, toggle_user_premium, 
    ban_user, get_all_user_ids, get_ad_text, update_ad_text
)
from config import BOT_TOKEN, ADMIN_WEBAPP_URL
import json
import logging
import hmac
import hashlib
from urllib.parse import parse_qs
from aiohttp import web

router = Router()
logger = logging.getLogger(__name__)

ADMIN_IDS = [1052080030, 578676876]

# --- Authentication Logic ---
def verify_telegram_webapp_data(init_data: str, bot_token: str) -> dict:
    """
    Verify Telegram Web App initData signature.
    Returns user data if valid, raises exception if invalid.
    """
    try:
        parsed = parse_qs(init_data)
        
        # Extract hash
        received_hash = parsed.get('hash', [''])[0]
        
        # Remove hash from data
        data_check_string = '\n'.join(
            f"{k}={v[0]}" 
            for k, v in sorted(parsed.items()) 
            if k != 'hash'
        )
        
        # Calculate expected hash
        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256
        ).digest()
        
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Verify hash
        if received_hash != expected_hash:
            raise ValueError("Invalid hash")
        
        # Extract user data
        user_data = json.loads(parsed.get('user', ['{}'])[0])
        
        return user_data
        
    except Exception as e:
        raise ValueError(f"Authentication failed: {e}")

@web.middleware
async def admin_middleware(request, handler):
    """
    Auth middleware:
    - Skip auth for OPTIONS (CORS preflight)
    - Skip auth for non-API routes (health check, etc.)
    - Require Telegram WebApp auth for /api/admin/* routes
    """
    # Skip auth for OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
        return await handler(request)

    # Skip auth for non-admin-API routes (health check, static, etc.)
    if not request.path.startswith("/api/admin"):
        return await handler(request)

    # ── /api/admin/* routes require authentication ──
    init_data = (
        request.headers.get('X-Telegram-Init-Data') or 
        request.headers.get('X-Init-Data')
    )
    
    if not init_data:
        logger.warning(f"⚠️ No auth header on {request.method} {request.path}")
        return web.json_response(
            {"success": False, "error": "No authentication data provided. Open panel from Telegram."},
            status=401
        )
    
    try:
        user_data = verify_telegram_webapp_data(init_data, BOT_TOKEN)
        user_id = user_data.get('id')
        
        if user_id not in ADMIN_IDS:
            return web.json_response(
                {"success": False, "error": "Unauthorized — not an admin"},
                status=403
            )
        
        # Store user_id in request for handlers
        request['admin_id'] = user_id
        logger.info(f"✅ Admin authenticated: {user_id} → {request.method} {request.path}")
        return await handler(request)
        
    except ValueError as e:
        logger.warning(f"❌ Auth failed on {request.path}: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=401
        )

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
    """GET /api/admin/stats — Dashboard statistics."""
    try:
        stats = await get_admin_statistics()
        return web.json_response({"success": True, "data": stats})
    except Exception as e:
        logger.error(f"API Error [stats]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_users(request):
    """GET /api/admin/users — Paginated user list."""
    try:
        page = int(request.query.get('page', 1))
        search = request.query.get('search', "")
        data = await get_users_paginated(page, search)
        return web.json_response({"success": True, "data": data})
    except Exception as e:
        logger.error(f"API Error [users]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def handle_toggle_action(request):
    """POST /api/admin/toggle — Toggle premium/ban status."""
    try:
        data = await request.json()
        user_id = int(data.get('user_id'))
        action = data.get('action')  # 'premium' or 'ban'
        
        success = False
        new_status = False
        
        if action == 'premium':
            new_status = await toggle_user_premium(user_id)
            success = True
        elif action == 'ban':
            new_status = await ban_user(user_id)
            success = True
        else:
            return web.json_response({"success": False, "error": f"Unknown action: {action}"}, status=400)
            
        return web.json_response({"success": success, "new_status": new_status})
    except Exception as e:
        logger.error(f"API Error [toggle]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_user_action_shim(request):
    """POST /api/admin/user/{action} — Compatibility shim for frontend."""
    try:
        data = await request.json()
        action = request.match_info['action']
        user_id = int(data.get('user_id'))
        
        success = False
        new_status = False
        
        if action == 'premium':
            new_status = await toggle_user_premium(user_id)
            success = True
        elif action == 'ban':
            new_status = await ban_user(user_id)
            success = True
        else:
            return web.json_response({"success": False, "error": f"Unknown action: {action}"}, status=400)
            
        return web.json_response({"success": success, "new_status": new_status})
    except Exception as e:
        logger.error(f"API Error [user_action]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_settings(request):
    """GET /api/admin/settings — Get ad text settings."""
    try:
        text = await get_ad_text()
        return web.json_response({"success": True, "data": {"ad_text": text}})
    except Exception as e:
        logger.error(f"API Error [settings]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_update_ad(request):
    """POST /api/admin/settings/ad or /api/admin/ad-update — Update ad text."""
    try:
        data = await request.json()
        text = data.get('text')
        success = await update_ad_text(text)
        return web.json_response({"success": success})
    except Exception as e:
        logger.error(f"API Error [update_ad]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)

async def api_broadcast(request):
    """POST /api/admin/broadcast — Send broadcast message to users."""
    try:
        data = await request.json()
        message_text = data.get('message')
        target = data.get('target', 'all')  # 'all' or 'premium'
        
        if not message_text:
            return web.json_response({"success": False, "error": "Message text is required"}, status=400)
        
        premium_only = (target == 'premium')
        user_ids = await get_all_user_ids(premium_only)
        
        # Use the bot instance from the app, not create a new one
        bot = request.app.get('bot')
        if not bot:
            # Fallback: create a temporary bot instance
            bot = Bot(token=BOT_TOKEN)
            should_close = True
        else:
            should_close = False
        
        count = 0
        errors = 0
        for uid in user_ids:
            try:
                await bot.send_message(uid, message_text)
                count += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Failed to send to {uid}: {e}")
        
        if should_close:
            await bot.session.close()
        
        logger.info(f"📨 Broadcast sent: {count} successful, {errors} failed")
        return web.json_response({"success": True, "count": count, "errors": errors})
    except Exception as e:
        logger.error(f"API Error [broadcast]: {e}")
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ── Route Setup (called from main.py) ──
def setup_admin_routes(app):
    app.router.add_get('/api/admin/stats', api_stats)
    app.router.add_get('/api/admin/users', api_users)
    app.router.add_post('/api/admin/toggle', handle_toggle_action)
    app.router.add_post('/api/admin/user/{action}', api_user_action_shim)
    app.router.add_get('/api/admin/settings', api_settings)
    app.router.add_post('/api/admin/settings/ad', api_update_ad)
    app.router.add_post('/api/admin/ad-update', api_update_ad)
    app.router.add_post('/api/admin/broadcast', api_broadcast)
    
    logger.info("✅ Admin routes registered:")
    logger.info("   GET  /api/admin/stats")
    logger.info("   GET  /api/admin/users")
    logger.info("   POST /api/admin/toggle")
    logger.info("   POST /api/admin/user/{action}")
    logger.info("   GET  /api/admin/settings")
    logger.info("   POST /api/admin/settings/ad")
    logger.info("   POST /api/admin/ad-update")
    logger.info("   POST /api/admin/broadcast")
