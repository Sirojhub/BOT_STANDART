from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from states import Registration
from keyboards import get_language_keyboard, get_agreement_keyboard, get_phone_keyboard, get_main_menu_keyboard, get_plans_keyboard
from database import save_webapp_data, update_user_phone, add_user, get_user_pricing_info
import json
import logging

# Configure router
router = Router()
logger = logging.getLogger(__name__)



@router.message(Registration.choosing_language)
async def process_language(message: types.Message, state: FSMContext):
    """
    Handles language selection and sends the Web App link.
    """
    # Mapping button text to language codes
    lang_map = {
        "🇺🇿 O'zbekcha": "uz",
        "🇷🇺 Русский": "ru",
        "🇬🇧 English": "en"
    }
    
    selected_text = message.text
    if selected_text not in lang_map:
        await message.answer("Please select a valid language using the keyboard below.")
        return

    lang_code = lang_map[selected_text]
    await state.update_data(language=lang_code)
    
    # Retrieve referrer_id from state if exists
    user_data = await state.get_data()
    referrer_id = user_data.get("referrer_id")

    # Save initial user record (optional, but good for tracking language preference early)
    # We use a placeholder name/status until they verify via Web App
    await add_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        language=lang_code,
        status="started",
        referrer_id=referrer_id
    )

    text = {
        "uz": "Ro'yxatdan o'tish uchun quyidagi tugmani bosing:",
        "ru": "Нажмите кнопку ниже для регистрации:",
        "en": "Press the button below to register:"
    }
    
    await message.answer(
        text.get(lang_code, text["en"]),
        reply_markup=get_agreement_keyboard(lang_code)
    )
    await state.set_state(Registration.waiting_for_webapp)

@router.message(Registration.waiting_for_webapp, F.web_app_data)
async def process_webapp_data(message: types.Message, state: FSMContext):
    """
    Handles data received from the Web App.
    Parses JSON payload. Supports both legacy full form and new agreement-only flow.
    """
    try:
        # Parse JSON data
        data = json.loads(message.web_app_data.data)
        logger.info(f"Received Web App data: {data}")

        # Check for new flow (Offer Accepted)
        if data.get("offer_accepted"):
            # Use defaults for missing fields since we removed the form
            full_name = message.from_user.full_name or "Unknown"
            region = ""
            district = ""
            mahalla = ""
            age = 0
            status = "verified"
            
            # Save to database (Updating existing record or creating new)
            success = await save_webapp_data(
                user_id=message.from_user.id,
                full_name=full_name,
                region=region,
                district=district,
                mahalla=mahalla,
                age=age
            )

            if success:
                user_data = await state.get_data()
                language = user_data.get("language", "en")
                
                logger.info(f"User {message.from_user.id} accepted offer. Redirecting to phone input.")
                
                text = {
                    "uz": "✅ Offerta qabul qilindi! 📱 Endi telefon raqamingizni yuboring:",
                    "ru": "✅ Оферта принята! 📱 Теперь отправьте ваш номер телефона:",
                    "en": "✅ Offer accepted! 📱 Now please share your phone number:"
                }
                
                await message.answer(
                    text.get(language, "en"),
                    reply_markup=get_phone_keyboard(language)
                )
                await state.set_state(Registration.waiting_for_phone)
            else:
                logger.error(f"Failed to save offer acceptance for user {message.from_user.id}")
                await message.answer("❌ Server error while saving data. Please contact support.")
            return

        # Legacy Flow (Keep for backward compatibility if needed)
        f_name = data.get("f")
        r_name = data.get("r")
        d_name = data.get("d")
        m_name = data.get("m")
        u_age = data.get("a")
        u_status = data.get("s")

        # Basic Validation
        if not all([f_name, r_name, d_name, m_name, u_age]):
            logger.warning(f"Incomplete legacy data from user {message.from_user.id}: {data}")
            await message.answer("⚠️ Incomplete data received. Please try again.")
            return

        if u_status == "verified":
             # Save to database
            success = await save_webapp_data(
                user_id=message.from_user.id,
                full_name=f_name,
                region=r_name,
                district=d_name,
                mahalla=m_name,
                age=int(u_age)
            )

            if success:
                user_data = await state.get_data()
                language = user_data.get("language", "en")
                
                logger.info(f"User {message.from_user.id} verified via legacy form.")
                
                text = {
                    "uz": "✅ Ma'lumotlar qabul qilindi! 📱 Endi telefon raqamingizni yuboring:",
                    "ru": "✅ Данные приняты! 📱 Теперь отправьте ваш номер телефона:",
                    "en": "✅ Data received! 📱 Now please share your phone number:"
                }
                
                await message.answer(
                    text.get(language, "en"),
                    reply_markup=get_phone_keyboard(language)
                )
                await state.set_state(Registration.waiting_for_phone)
            else:
                logger.error(f"Failed to save legacy data for user {message.from_user.id}")
                await message.answer("❌ Server error while saving data. Please contact support.")

    except json.JSONDecodeError:
        logger.error("Failed to decode Web App JSON data")
        await message.answer("❌ Error processing data format.")
    except Exception as e:
        logger.error(f"Unexpected error in webapp handler: {e}")
        await message.answer("❌ An unexpected error occurred.")

@router.callback_query(F.data == "open_agreement")
async def open_agreement_callback(callback: types.CallbackQuery, state: FSMContext):
    """
    Fallback or explicit handler if needed for callback buttons related to agreement.
    Note: Web App is usually opened via keyboard, not callback, but keeping logic resilient.
    """
    await state.set_state(Registration.waiting_for_webapp)
    await callback.answer()

@router.message(Registration.waiting_for_phone, F.contact)
async def process_phone(message: types.Message, state: FSMContext):
    """
    Handles phone number submission via contact sharing.
    """
    try:
        phone = message.contact.phone_number
        user_id = message.from_user.id
        
        success = await update_user_phone(user_id, phone)
        
        if success:
            user_data = await state.get_data()
            language = user_data.get("language", "en")
            
            # Use 'is_premium' from user object directly
            # Note: In real app, you might want to check DB or specific logic, 
            # but user.is_premium is the Telegram status.
            is_premium = message.from_user.is_premium or False

            # Get user pricing info to pass to plans keyboard
            # At this stage, balance is likely 0, test_used false, but good to be explicit
            pricing_info = await get_user_pricing_info(user_id)
            balance = pricing_info['balance'] if pricing_info else 0
            test_used = str(pricing_info['test_used']).lower() if pricing_info else "false"
            is_tg_premium = str(message.from_user.is_premium or False).lower()

            text = {
                "uz": "🎉 Ro'yxatdan o'tish muvaffaqiyatli yakunlandi!\n\nEndi botdan to'liq foydalanish uchun o'zingizga mos tarifni tanlang:",
                "ru": "🎉 Регистрация успешно завершена!\n\nТеперь выберите подходящий тариф для использования бота:",
                "en": "🎉 Registration completed successfully!\n\nNow please choose a plan to start using the bot:"
            }
            
            await message.answer(
                text.get(language, "en"),
                reply_markup=get_plans_keyboard(language, balance, test_used, is_tg_premium)
            )
            # Clear state so security router picks up web_app_data
            await state.clear() 
            logger.info(f"Registration completed for user {user_id}")
        else:
            await message.answer("❌ Failed to save phone number.")
            
    except Exception as e:
        logger.error(f"Error in phone handler: {e}")
        await message.answer("❌ An error occurred while processing your phone number.")
