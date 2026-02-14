from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from states import Registration
from keyboards import get_language_keyboard, get_agreement_keyboard, get_phone_keyboard, get_main_menu_keyboard
from database import save_webapp_data, update_user_phone, add_user
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
    
    # Save initial user record (optional, but good for tracking language preference early)
    # We use a placeholder name/status until they verify via Web App
    await add_user(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        language=lang_code,
        status="started"
    )

    text = {
        "uz": "Ro'yxatdan o'tish uchun quyidagi tugmani bosing:",
        "ru": "Нажмите кнопку ниже для регистрации:",
        "en": "Press the button below to register:"
    }
    
    # Send WebApp button
    await message.answer(
        text.get(lang_code, "en"),
        reply_markup=get_agreement_keyboard(lang_code)
    )
    await state.set_state(Registration.waiting_for_webapp)

@router.message(Registration.waiting_for_webapp, F.web_app_data)
async def process_webapp_data(message: types.Message, state: FSMContext):
    """
    Handles data received from the Web App.
    Parses JSON payload with keys: f, r, d, m, a, s.
    """
    try:
        # Parse JSON data
        data = json.loads(message.web_app_data.data)
        logger.info(f"Received Web App data: {data}")

        # Extract fields based on Web App keys
        full_name = data.get("f")
        region = data.get("r")
        district = data.get("d")
        mahalla = data.get("m")
        age = data.get("a")
        status = data.get("s")

        # Basic Validation
        if not all([full_name, region, district, mahalla, age]):
            await message.answer("⚠️ Incomplete data received. Please try again.")
            return

        if status == "verified":
             # Save to database
            success = await save_webapp_data(
                user_id=message.from_user.id,
                full_name=full_name,
                region=region,
                district=district,
                mahalla=mahalla,
                age=int(age)
            )

            if success:
                user_data = await state.get_data()
                language = user_data.get("language", "en")
                
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

            text = {
                "uz": "🎉 Ro'yxatdan o'tish muvaffaqiyatli yakunlandi! Xavfsizlik tizimi faollashdi.",
                "ru": "🎉 Регистрация успешно завершена! Система безопасности активирована.",
                "en": "🎉 Registration completed successfully! Security system activated."
            }
            
            await message.answer(
                text.get(language, "en"),
                reply_markup=get_main_menu_keyboard(language, is_premium)
            )
            await state.set_state(Registration.main_menu)
            logger.info(f"Registration completed for user {user_id}")
        else:
            await message.answer("❌ Failed to save phone number.")
            
    except Exception as e:
        logger.error(f"Error in phone handler: {e}")
        await message.answer("❌ An error occurred while processing your phone number.")
