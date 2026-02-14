import asyncio
import logging
import os
import signal
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
from config import BOT_TOKEN, VT_API_KEY, ADMIN_MSG_ID  # Ensure these are in config.py or use os.getenv directly
from handlers import onboarding, security, start, admin
from database import create_users_table, get_db_path # Ensure database.py exports get_db_path or handle path here

# Configure Logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Environment Variables (Fallback if config.py missing attributes)
BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN)
VT_API_KEY = os.getenv("VT_API_KEY", VT_API_KEY)
# We assume ADMIN_IDS are managed in handlers/admin.py or config.py

# ── Manual CORS + Logging Middleware ──────────────────────────────────────
ALLOWED_ORIGINS = "*"

@web.middleware
async def cors_and_logging_middleware(request, handler):
    """Logs requests and adds CORS headers."""
    # ... logic ...
    # (Simplified for brevity in replacement, but keep full logic from original file if desired)
    # Re-using original logic for robustness:
    origin = request.headers.get("Origin", "*")
    logger.info(f"📡 Incoming Request: {request.method} {request.path} from {origin}")

    if request.method == "OPTIONS":
        response = web.Response(status=200)
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-Init-Data, X-Init-Data, ngrok-skip-browser-warning"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response

    try:
        response = await handler(request)
    except web.HTTPException as ex:
        response = ex

    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-Init-Data, X-Init-Data, ngrok-skip-browser-warning"
    return response

# ── Health Check ──────────────────────────────────────────────────────────
async def health_check(request):
    return web.json_response({"status": "ok", "service": "gvard-bot-docker"})

# ── Main ──────────────────────────────────────────────────────────────────
async def main():
    # 1. Initialize Bot
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 2. Setup Routers
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(onboarding.router)
    dp.include_router(security.router)

    # 3. Database & Webhook Cleanup
    await create_users_table() # Ensure this uses data/bot.db
    
    # Drop pending updates to avoid conflict loop on restart
    logger.info("♻️  Dropping pending updates...")
    await bot.delete_webhook(drop_pending_updates=True)

    # 4. Web App Setup
    app = web.Application(middlewares=[cors_and_logging_middleware, admin.admin_middleware])
    app['bot'] = bot
    admin.setup_admin_routes(app)
    app.router.add_get('/', health_check)

    # 5. Start Web Server
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000)) # Default to 10000 for Render Docker
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    logger.info(f"🚀 Starting Bot & Web Server on port {port}...")
    await site.start()

    # 6. Polling with Signal Handling
    # We turn off internal handle_signals so we can manage the loop stop manually below
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    # 7. Graceful Shutdown Logic
    stop_event = asyncio.Event()

    def signal_handler(sig, frame):
        logger.warning(f"⚠️  Signal {sig} received. Stopping...")
        stop_event.set()

    # Register signals
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: stop_event.set())
    loop.add_signal_handler(signal.SIGINT, lambda: stop_event.set())

    # Wait for stop signal
    await stop_event.wait()

    # Cleanup
    logger.info("🛑 Stopping polling...")
    try:
        await dp.stop_polling()
        polling_task.cancel()
        await polling_task
    except asyncio.CancelledError:
        pass

    logger.info("🧹 Closing resources...")
    await bot.session.close()
    await runner.cleanup()
    logger.info("✅ Shutdown complete.")

if __name__ == "__main__":
    if not BOT_TOKEN:
        sys.exit("CRITICAL: BOT_TOKEN is not set.")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
