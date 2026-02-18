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
        # Check if banned (Index 15 assumed based on previous check, let's verify)
        # 0:id, 1:username, 2:name, 3:region, 4:dist, 5:mahalla, 6:age, 7:phone, 8:lang, 9:created, 10:status, 11:offer, 12:reg_complete, 13:last_active, 14:premium, 15:banned
        if len(user) > 15 and user[15]:
            await message.answer("⛔️ Sizning hisobingiz bloklangan.\n\nAdmin bilan bog'laning: @GvardAdmin")
            return

        # Check registration complete
        if user[12]: # registration_complete
            await state.clear()
            await message.answer(
                "🏠 Asosiy menyu",
                reply_markup=get_main_menu_keyboard('uz', bool(user[14])) # user[14] is is_premium
            )
            return

    # New or incomplete user -> Start Onboarding
    await state.clear()
    
    # Re-apply referral if valid
    if valid_referrer_id:
        await state.update_data(referrer_id=valid_referrer_id)
        
    await message.answer(
        "👋 Xush kelibsiz! Iltimos, tilni tanlang:\n"
        "Добро пожаловать! Пожалуйста, выберите язык:\n"
        "Welcome! Please select your language:",
        reply_markup=get_language_keyboard()
    )
    await state.set_state(Registration.choosing_language)
    logger.info(f"New/Incomplete user {user_id} started onboarding.")
