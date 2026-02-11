import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiohttp import web
import aiohttp_cors
from config import BOT_TOKEN
from handlers import onboarding, security, start, admin
from database import create_users_table

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def setup_cors(app):
    cors = aiohttp_cors.setup(app, defaults={
        "https://sirojhub.github.io": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        ),
        # Allow localhost for testing if needed, or remove
        "http://localhost:8080": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
            allow_methods="*"
        )
    })
    
    # Configure CORS on all routes.
    for route in list(app.router.routes()):
        cors.add(route)

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

    # Create Web App
    # We add admin_middleware here.
    app = web.Application(middlewares=[admin.admin_middleware])
    
    # Assign bot to app 
    app['bot'] = bot
    
    # Setup Admin Routes (this adds routes to app)
    admin.setup_admin_routes(app)
    
    # Setup CORS (must be after routes are added)
    await setup_cors(app)
    
    # Run Bot polling and Web Server concurrently
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    
    logging.info("Starting Bot and Web Server...")
    
    await asyncio.gather(
        dp.start_polling(bot),
        site.start()
    )

if __name__ == "__main__":
    if not BOT_TOKEN:
        logging.warning("⚠️ BOT_TOKEN is not set!")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
