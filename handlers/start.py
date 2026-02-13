from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from database import is_registered, update_last_active, get_user
from keyboards import get_main_menu_keyboard, get_language_keyboard
from states import Registration
import logging

router = Router()
logger = logging.getLogger(__name__)

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Smart /start handler.
    - If user exists in DB → show main menu (even after stop/block)
    - If user is banned → show ban message
    - If user is NEW (no DB record) → start onboarding
    """
    user_id = message.from_user.id
    
    # ── Step 1: Check if user exists in database ──
    user = await get_user(user_id)
    
    if user:
        # User EXISTS in DB → they've used the bot before
        logger.info(f"Returning user detected: {user_id}")
        
        # Update activity timestamp
        await update_last_active(user_id)
        
        # Column indices:
        # 0:user_id, 1:username, 2:full_name, 3:region, 4:district, 
        # 5:mahalla, 6:age, 7:phone, 8:language, 9:created_at, 
        # 10:status, 11:is_offer_accepted, 12:registration_complete, 
        # 13:last_active, 14:is_premium, 15:is_banned
        
        # Check if banned
        is_banned = len(user) > 15 and user[15]
        if is_banned:
            await message.answer(
                "⛔️ Sizning hisobingiz bloklangan.\n\n"
                "Admin bilan bog'laning: @GvardAdmin"
            )
            return
        
        # ── User is NOT banned → Show main menu ──
        # Get language (default 'uz') and premium status
        lang = user[8] if user[8] else "uz"
        is_premium = bool(user[14]) if len(user) > 14 else False
        
        await state.clear()
        
        welcome_texts = {
            "uz": "🏠 Xush kelibsiz! Asosiy menyu:",
            "ru": "🏠 Добро пожаловать! Главное меню:",
            "en": "🏠 Welcome back! Main Menu:"
        }
        
        await message.answer(
            welcome_texts.get(lang, welcome_texts["uz"]),
            reply_markup=get_main_menu_keyboard(lang, is_premium)
        )
        return
    
    # ── Step 2: User NOT in DB → completely new user ──
    logger.info(f"New user detected: {user_id}, starting onboarding.")
    await state.clear()
    await message.answer(
        "👋 Xush kelibsiz! Iltimos, tilni tanlang:\n"
        "Добро пожаловать! Пожалуйста, выберите язык:\n"
        "Welcome! Please select your language:",
        reply_markup=get_language_keyboard()
    )
    await state.set_state(Registration.choosing_language)
