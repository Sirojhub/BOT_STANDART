import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
import pytz
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from config import BOT_TOKEN, VT_API_KEY, ADMIN_MSG_ID # config import optional if using os.getenv
from config import BOT_TOKEN 
from handlers import onboarding, security, start, admin
from database import create_users_table, get_db_path, reset_daily_stats

# Configure Logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN", BOT_TOKEN)
# RENDER_EXTERNAL_URL is provided by Render, or we use the one user gave
dict_env_url = os.getenv("RENDER_EXTERNAL_URL", "https://bot-standart.onrender.com")
PING_URL = dict_env_url if dict_env_url.startswith("http") else f"https://{dict_env_url}"

# ── Keep-Alive Function ───────────────────────────────────────────────────
async def keep_alive():
    """Pings the web server to prevent sleep."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PING_URL) as response:
                if response.status == 200:
                    logger.info("⏰ Self-ping successful")
                else:
                    logger.warning(f"⚠️ Ping failed: {response.status}")
    except Exception as e:
        logger.error(f"⚠️ Ping error: {e}")

# ── Cron Job: Reset Daily Stats ───────────────────────────────────────────
async def scheduled_reset_daily_stats():
    """Wrapper to call database reset function."""
    try:
        await reset_daily_stats()
        logger.info("🔄 Daily stats reset successfully.")
    except Exception as e:
        logger.error(f"❌ Daily stats reset error: {e}")

# ── Manual CORS ───────────────────────────────────────────────────────────
ALLOWED_ORIGINS = "*"

@web.middleware
async def cors_and_logging_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-Init-Data, X-Init-Data, ngrok-skip-browser-warning"
        return response

    try:
        response = await handler(request)
    except web.HTTPException as ex:
        response = ex

    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
    return response

# ── Health Check ──────────────────────────────────────────────────────────
async def health_check(request):
    return web.json_response({"status": "ok", "service": "gvard-bot-docker"})

# ── Main ──────────────────────────────────────────────────────────────────
async def main():
    # 1. Initialize Bot & Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # 2. Setup Routers
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(onboarding.router)
    dp.include_router(security.router)

    # 3. Database & Webhook Cleanup
    await create_users_table()
    logger.info("♻️  Dropping pending updates...")
    await bot.delete_webhook(drop_pending_updates=True)

    # 4. Scheduler Setup
    # Use Asia/Tashkent explicitly
    tz_tashkent = pytz.timezone("Asia/Tashkent")
    scheduler = AsyncIOScheduler(timezone=tz_tashkent)
    
    # Add Self-Ping (Every 10 minutes)
    scheduler.add_job(keep_alive, "interval", minutes=10)
    
    # Add Daily Reset (Every day at 00:00 Tashkent time)
    scheduler.add_job(scheduled_reset_daily_stats, "cron", hour=0, minute=0)
    
    scheduler.start()
    logger.info("⏳ Scheduler started (Timezone: Asia/Tashkent)")

    # 5. Web App Setup
    app = web.Application(middlewares=[cors_and_logging_middleware, admin.admin_middleware])
    app['bot'] = bot
    admin.setup_admin_routes(app)
    app.router.add_get('/', health_check)

    # 6. Start Web Server
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    logger.info(f"🚀 Starting Bot & Web Server on port {port}...")
    await site.start()

    # 7. Polling with Signal Handling
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    # 8. Graceful Shutdown Logic
    stop_event = asyncio.Event()

    def signal_handler():
        logger.warning(f"⚠️  Signal received. Stopping...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

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
    
    logger.info("⏳ Shutting down scheduler...")
    scheduler.shutdown()

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
        pass
