from aiogram import Router, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from database import is_registered, update_last_active
from keyboards import get_main_menu_keyboard, get_language_keyboard
from states import Registration
import logging

router = Router()
logger = logging.getLogger(__name__)

@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """
    Smart /start handler.
    Checks if user is already registered.
    Handles Referral Deep Links.
    """
    user_id = message.from_user.id
    valid_referrer_id = None
    
    # Check for referral args
    command_args = message.text.split()
    if len(command_args) > 1:
        try:
            referrer_id = int(command_args[1])
            # Prevent self-referral
            if referrer_id != user_id:
                valid_referrer_id = referrer_id
                logger.info(f"User {user_id} referred by {referrer_id}")
        except ValueError:
            pass
    
    # Update activity
    await update_last_active(user_id)
    
    # Check registration and status
    from database import get_user
    user = await get_user(user_id)
    
    if user:
        # Check if banned
        if user['is_banned']:
            await message.answer("⛔️ Sizning hisobingiz bloklangan.\n\nAdmin bilan bog'laning: @GvardAdmin")
            return

        # Check registration complete
        if user['registration_complete']:
            await state.clear()
            lang = user['language'] or 'uz'
            await message.answer(
                "🏠 Asosiy menyu",
                reply_markup=get_main_menu_keyboard(lang, bool(user['is_premium']))
            )
            return

    # Welcome screen from drawing
    welcome_text = (
        "<b>[ SARHAD KIBERXAVFSIZLIK TIZIMI ]</b>\n\n"
        "● <b>HOLAT:</b> TIZIM FAOL\n"
        "● <b>VERSIYA:</b> 1.15.5-BARQAROR\n"
        "■ <b>NAZORAT:</b> SARHAD MONITORING MARKAZI\n\n"
        "<b>TIZIMNING ASOSIY VAZIFALARI:</b>\n"
        "> HAVOLALARNI TEKSHIRISH: ShubhalI sayt manzillarini tahlil qilish.\n"
        "> FAYLLARNI SKANERLASH: Virus va zararli dasturlarni aniqlash.\n"
        "> ILOVA NAZORATI: Zararli fayllarni ochishdan oldin avtomatik skanerlash.\n"
        "> DOIMIY HIMOYA: Premium foydalanuvchilar uchun 24/7 nazorat.\n\n"
        "<b>FOYDALANUVCHI DIQQATIGA:</b>\n"
        "Xavfsizlik tekshiruvini boshlash va tizimga kirish uchun pastdagi tilni tanlang.\n\n"
        "<i>ESLATMA: BARCHA AMALLAR XAVFSIZLIK YUZASIDAN QAYD ETIB BORILADI. RUXSATSIZ HARAKATLAR CHEKLANADI.</i>"
    )

    # New or incomplete user -> Start Onboarding
    await state.clear()
    
    if valid_referrer_id:
        await state.update_data(referrer_id=valid_referrer_id)
        
    await message.answer(
        welcome_text,
        reply_markup=get_language_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.choosing_language)
    logger.info(f"New/Incomplete user {user_id} started onboarding.")
