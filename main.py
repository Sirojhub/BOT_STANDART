import asyncio
import logging
import os
import signal
import sys
from aiogram import Bot, Dispatcher
from aiohttp import web
from config import BOT_TOKEN
from handlers import onboarding, security, start, admin
from database import create_users_table, close_db_pool

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


# ── Manual CORS + Logging Middleware ──────────────────────────────────────
# Instead of aiohttp_cors (which can conflict with other middlewares),
# we handle CORS manually. This guarantees every response gets the
# correct headers, including error responses (401/403/500).

ALLOWED_ORIGINS = "*"

@web.middleware
async def cors_and_logging_middleware(request, handler):
    """
    1) Log every incoming request to the terminal.
    2) Handle OPTIONS preflight requests immediately.
    3) Add CORS headers to every response.
    """
    origin = request.headers.get("Origin", "*")
    logger.info(f"📡 Incoming Request: {request.method} {request.path} from {origin}")

    # ── Preflight (OPTIONS) ──
    if request.method == "OPTIONS":
        response = web.Response(status=200)
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-Init-Data, X-Init-Data, ngrok-skip-browser-warning"
        response.headers["Access-Control-Max-Age"] = "86400"
        logger.info(f"✅ Preflight OK for {request.path}")
        return response

    # ── Normal request ──
    try:
        response = await handler(request)
    except web.HTTPException as ex:
        response = ex

    # Add CORS headers to every response
    response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGINS
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Telegram-Init-Data, X-Init-Data, ngrok-skip-browser-warning"

    return response


# ── Health Check Endpoint ─────────────────────────────────────────────────
async def health_check(request):
    """Render health check — returns 200 so Render knows the service is alive."""
    return web.json_response({"status": "ok", "service": "gvard-bot"})


async def main():
    # Initialize Bot and Dispatcher
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Include routers
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(onboarding.router)
    dp.include_router(security.router)

    # Database initialization
    await create_users_table()

    # ── Web Application ──────────────────────────────────────────────────
    # Middleware order: cors_and_logging runs FIRST, then admin_middleware.
    # This ensures CORS headers are always present, even on 401/403 errors.
    app = web.Application(middlewares=[
        cors_and_logging_middleware, 
        admin.admin_middleware
    ])

    # Assign bot to app so broadcast handler can use it
    app['bot'] = bot

    # Setup Admin Routes (from handlers/admin.py)
    admin.setup_admin_routes(app)

    # Health check route (Render pings this to verify service is alive)
    app.router.add_get('/', health_check)

    # ── Start Server ─────────────────────────────────────────────────────
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port, reuse_address=True)

    logger.info(f"🚀 Starting Bot and Web Server on 0.0.0.0:{port}...")
    logger.info("📋 Routes registered:")
    for route in app.router.routes():
        logger.info(f"   {route.method} {route.resource}")

    # ── Graceful SIGTERM Handling ─────────────────────────────────────────
    # When Render sends SIGTERM, stop polling FIRST so the next instance
    # can start without TelegramConflictError.
    stop_event = asyncio.Event()

    def handle_sigterm(*args):
        logger.info("⚠️ SIGTERM received — stopping polling gracefully...")
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    try:
        await site.start()

        # ── Clear webhook to prevent TelegramConflictError ──
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("🔄 Webhook cleared, starting fresh polling...")
        except Exception as e:
            logger.warning(f"⚠️ Could not clear webhook: {e}")

        polling_task = asyncio.create_task(dp.start_polling(bot))

        # Wait until SIGTERM is received
        await stop_event.wait()

        # Stop polling gracefully
        logger.info("🛑 Stopping bot polling...")
        await dp.stop_polling()
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error(f"Error in main loop: {e}", exc_info=True)
    finally:
        logger.info("🧹 Cleaning up...")
        try:
            await close_db_pool()
            logger.info("✅ Database pool closed.")
        except Exception as e:
            logger.error(f"Error closing DB pool: {e}")
        try:
            await bot.session.close()
            logger.info("✅ Bot session closed.")
        except Exception as e:
            logger.error(f"Error closing bot session: {e}")
        try:
            await runner.cleanup()
            logger.info("✅ Web runner cleaned up.")
        except Exception as e:
            logger.error(f"Error cleaning up runner: {e}")


if __name__ == "__main__":
    if not BOT_TOKEN:
        logging.warning("⚠️ BOT_TOKEN is not set!")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Bot stopped by user.")
    except Exception as e:
        logger.error(f"⚠️ Critical Error: {e}")
