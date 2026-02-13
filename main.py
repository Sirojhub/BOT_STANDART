"""
main.py — Sarhad Bot: Entry point
═══════════════════════════════════
Render.com Web Service sifatida ishlaydi:
  - aiohttp → health check (PORT ga bind)
  - aiogram → long polling (Telegram API)
  - asyncio.gather → ikkalasi parallel

Hal qilingan muammolar:
  ✅ ConflictError — delete_webhook + drop_pending_updates
  ✅ Async session — asyncpg (native async, commit() yo'q)
  ✅ User persistence — /start da get_user → create_user
"""

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiohttp import web

from database import init_db, get_user, create_user, update_user_activity, close_db

# ── Logging ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("sarhad")

# ── Environment variables ────────────────────────────────────────────────
# Render Dashboard → Environment tab'da qo'yilishi shart
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))  # Render o'zi beradi
HOST = "0.0.0.0"

if not BOT_TOKEN:
    logger.critical("❌ BOT_TOKEN environment variable topilmadi!")
    sys.exit(1)

if not DATABASE_URL:
    logger.critical("❌ DATABASE_URL environment variable topilmadi!")
    sys.exit(1)

# ── Bot va Dispatcher ────────────────────────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


# ══════════════════════════════════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    """
    /start handler — asosiy entry point.

    Mantiq:
      1. DB'dan user_id qidirish
      2. Bor → salomlash, qayta ro'yxatga olmaydi
      3. Yo'q → create_user(), keyin salomlash
    """
    try:
        user_id = message.from_user.id
        username = message.from_user.username
        full_name = message.from_user.full_name

        # Bazadan tekshirish
        existing = await get_user(user_id)

        if existing:
            # ── Tanish foydalanuvchi ──
            logger.info(f"🔄 Returning user: {user_id} (@{username})")
            await update_user_activity(user_id, is_active=True)
            await message.answer(
                f"👋 <b>Xush kelibsiz, {existing['full_name'] or 'do\'stim'}!</b>\n\n"
                f"🛡 <b>Sarhad</b> — kiberxavfsizlik yordamchingiz.\n"
                f"Buyruqlar uchun /help bosing."
            )
        else:
            # ── Yangi foydalanuvchi ──
            logger.info(f"🆕 New user: {user_id} (@{username})")
            ok = await create_user(user_id, username, full_name)
            if ok:
                await message.answer(
                    f"🛡 <b>Sarhad</b>ga xush kelibsiz!\n\n"
                    f"Men sizning kiberxavfsizlik yordamchingizman.\n"
                    f"Buyruqlar uchun /help bosing."
                )
            else:
                await message.answer("⚠️ Xato yuz berdi. Iltimos qayta urinib ko'ring.")

    except Exception as e:
        logger.error(f"cmd_start xatosi: {e}", exc_info=True)
        await message.answer("⚠️ Kutilmagan xato yuz berdi.")


@dp.message(Command("help"))
async def cmd_help(message: types.Message) -> None:
    """/help — buyruqlar ro'yxati."""
    try:
        await message.answer(
            "🛡 <b>Sarhad Bot — Buyruqlar</b>\n\n"
            "/start — Botni boshlash\n"
            "/help  — Yordam\n\n"
            "📎 Fayl yoki link yuboring — xavfsizlik tekshiruvi."
        )
    except Exception as e:
        logger.error(f"cmd_help xatosi: {e}", exc_info=True)


@dp.message(F.text)
async def handle_text(message: types.Message) -> None:
    """Umumiy matn handler — placeholder."""
    try:
        await message.answer(
            "📝 Xabaringiz qabul qilindi.\n"
            "Link yoki fayl yuboring — xavfsizlik tekshiruvi uchun."
        )
    except Exception as e:
        logger.error(f"handle_text xatosi: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════
# AIOHTTP — Health Check (Render uchun)
# ══════════════════════════════════════════════════════════════════════════

async def health_check(request: web.Request) -> web.Response:
    """Render GET / va /health ping qiladi — 200 OK qaytaramiz."""
    return web.json_response({"status": "ok", "service": "sarhad-bot"})


def create_aiohttp_app() -> web.Application:
    """aiohttp Application yaratadi health check endpoint bilan."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    return app


# ══════════════════════════════════════════════════════════════════════════
# ON_STARTUP — DB init + webhook tozalash
# ══════════════════════════════════════════════════════════════════════════

async def on_startup() -> None:
    """Bot ishga tushishidan oldin bajariladigan vazifalar."""

    # 1. Database pool yaratish va jadval hosil qilish
    logger.info("🗄 Initializing database...")
    await init_db(DATABASE_URL)

    # 2. Eski webhook'ni tozalash — ConflictError'ni oldini oladi
    # drop_pending_updates=True — eski xabarlarni tashlab yuboradi
    logger.info("🔄 Clearing any existing webhook...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook cleared successfully.")
    except Exception as e:
        logger.warning(f"⚠️ Webhook clearing warning: {e}")


# ══════════════════════════════════════════════════════════════════════════
# MAIN — Entry point
# ══════════════════════════════════════════════════════════════════════════

async def _run_forever() -> None:
    """aiohttp server tirik turishi uchun cheksiz kutish."""
    try:
        while True:
            await asyncio.sleep(3600)  # har 1 soatda uyg'onadi
    except asyncio.CancelledError:
        pass


async def main() -> None:
    """Asosiy funksiya — web server, DB, va bot polling'ni boshlaydi."""

    # ── 1. aiohttp server — PORT BIRINCHI OCHILADI ──
    # Render port scan qiladi → agar topmasa 60 soniyada o'ldiradi
    # Shu sababli port BIRINCHI ochilishi SHART, DB init keyin
    app = create_aiohttp_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()
    logger.info(f"🌐 Health check server running on {HOST}:{PORT}")

    # ── 2. DB init + webhook tozalash ──
    try:
        await on_startup()
    except Exception as e:
        logger.critical(f"❌ Startup failed: {e}", exc_info=True)
        await runner.cleanup()
        return

    # ── 3. Bot polling + web server parallel ishlaydi ──
    try:
        logger.info("🚀 Starting Sarhad bot polling...")
        await asyncio.gather(
            dp.start_polling(
                bot,
                drop_pending_updates=True,
                handle_signals=False,
            ),
            _run_forever(),
        )
    except asyncio.CancelledError:
        logger.info("🛑 Polling cancelled.")
    except Exception as e:
        logger.error(f"❌ Critical error in main loop: {e}", exc_info=True)
    finally:
        # ── 4. Graceful shutdown ──
        logger.info("🧹 Shutting down...")

        try:
            await close_db()
        except Exception as e:
            logger.error(f"Error closing DB: {e}")

        try:
            await bot.session.close()
            logger.info("✅ Bot session closed.")
        except Exception as e:
            logger.error(f"Error closing bot session: {e}")

        try:
            await runner.cleanup()
            logger.info("✅ Web runner cleaned up.")
        except Exception as e:
            logger.error(f"Error cleaning web runner: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Bot stopped by user (Ctrl+C).")
    except Exception as e:
        logger.critical(f"💀 Fatal error: {e}", exc_info=True)
        sys.exit(1)
