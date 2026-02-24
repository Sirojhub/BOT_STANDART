from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from database import get_user, update_last_active, get_db_path, add_user
from keyboards import get_main_menu_keyboard, get_settings_keyboard, get_language_keyboard
import aiosqlite
import logging

router = Router()
logger = logging.getLogger(__name__)

async def get_referral_count(user_id: int) -> int:
    """Helper to count how many people this user invited."""
    async with aiosqlite.connect(get_db_path()) as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

@router.message(StateFilter("*"), F.text.in_({"👤 Shaxsiy Kabinet", "👤 Личный кабинет", "👤 Personal Account", "👤 Men haqimda", "👤 Обо мне", "👤 About Me"}))
async def cmd_profile(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    if not user:
        await message.answer("⚠️ Ma'lumot topilmadi.")
        return

    # Indexes based on database.py:
    # 0:id, 1:username, 2:name, 3:region, 4:dist, 5:mahalla, 6:age, 7:phone, 8:lang, 9:created, 10:status, 11:offer, 12:reg_complete, 13:last_active, 14:premium
    lang = user[8] or "uz"
    full_name = user[2] or "Noma'lum"
    phone = user[7] or "Kiritilmagan"
    reg_date = user[9].split()[0] if user[9] else "Noma'lum"
    is_premium = bool(user[14])
    balance = user[44] if len(user) > 44 else user[16] # Fallback to referral_balance index (needs verification)
    # Let's re-verify indexes or use row_factory. database.py uses aiosqlite.Row in some places but get_user doesn't seem to set it explicitly everywhere.
    # Actually, get_user uses db.row_factory = aiosqlite.Row. So we can use names!
    
    ref_count = await get_referral_count(user_id)
    plan_name = {
        "uz": "Integrity Pro ✨" if is_premium else "Bazaviy Standart 🆓",
        "ru": "Integrity Pro ✨" if is_premium else "Базовый Стандарт 🆓",
        "en": "Integrity Pro ✨" if is_premium else "Basic Standard 🆓"
    }

    text = {
        "uz": (
            f"👤 <b>Shaxsiy Kabinet</b>\n\n"
            f"Identifikator: <code>{user_id}</code>\n"
            f"Foydalanuvchi: <b>{full_name}</b>\n"
            f"Aloqa: <code>{phone}</code>\n\n"
            f"💎 Xizmat darajasi: <b>{plan_name['uz']}</b>\n"
            f"💰 Depozit: <b>{user['referral_balance']} UZS</b>\n"
            f"👥 Hamkorlar: <b>{ref_count} ta</b>\n"
            f"📅 Faollashtirilgan sana: <b>{reg_date}</b>"
        ),
        "ru": (
            f"👤 <b>Личный Кабинет</b>\n\n"
            f"Идентификатор: <code>{user_id}</code>\n"
            f"Пользователь: <b>{full_name}</b>\n"
            f"Связь: <code>{phone}</code>\n\n"
            f"💎 Уровень сервиса: <b>{plan_name['ru']}</b>\n"
            f"💰 Депозит: <b>{user['referral_balance']} СУМ</b>\n"
            f"👥 Партнеры: <b>{ref_count}</b>\n"
            f"📅 Дата активации: <b>{reg_date}</b>"
        ),
        "en": (
            f"👤 <b>Personal Cabinet</b>\n\n"
            f"Identifier: <code>{user_id}</code>\n"
            f"Subscriber: <b>{full_name}</b>\n"
            f"Contact: <code>{phone}</code>\n\n"
            f"💎 Service Level: <b>{plan_name['en']}</b>\n"
            f"💰 Deposit: <b>{user['referral_balance']} UZS</b>\n"
            f"👥 Partners: <b>{ref_count}</b>\n"
            f"📅 Activation Date: <b>{reg_date}</b>"
        )
    }
    
    await message.answer(text.get(lang, text["en"]), parse_mode="HTML")

@router.message(StateFilter("*"), F.text.in_({"⚙️ Konfiguratsiya", "⚙️ Конфигурация", "⚙️ Configuration", "⚙️ Sozlamalar", "⚙️ Настройки", "⚙️ Settings"}))
async def cmd_settings(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    lang = user['language'] if user else "uz"
    
    text = {
        "uz": "⚙️ <b>Konfiguratsiya boshqaruvi</b>\n\nInterfeys tilini optimallashtirish uchun tanlovni amalga oshiring:",
        "ru": "⚙️ <b>Управление конфигурацией</b>\n\nСделайте выбор для оптимизации языка интерфейса:",
        "en": "⚙️ <b>Configuration Management</b>\n\nSelect a language to optimize the interface:"
    }
    
    await message.answer(text.get(lang, text["en"]), reply_markup=get_settings_keyboard(lang), parse_mode="HTML")

@router.message(F.text.in_({"🌐 Tilni o'zgartirish", "🌐 Сменить язык", "🌐 Change Language"}))
async def cmd_change_lang(message: types.Message):
    await message.answer(
        "🌐 Iltimos, yangi tilni tanlang:\nПожалуйста, выберите новый язык:\nPlease select a new language:",
        reply_markup=get_language_keyboard()
    )

@router.message(StateFilter("*"), F.text.in_({"🇺🇿 O'zbekcha", "🇷🇺 Русский", "🇬🇧 English"}))
async def process_new_lang(message: types.Message):
    lang_map = {"🇺🇿 O'zbekcha": "uz", "🇷🇺 Русский": "ru", "🇬🇧 English": "en"}
    new_lang = lang_map.get(message.text)
    if not new_lang: return
    
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    async with aiosqlite.connect(get_db_path()) as db:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?", (new_lang, user_id))
        await db.commit()
    
    res = {
        "uz": "✅ Til muvaffaqiyatli o'zgartirildi!",
        "ru": "✅ Язык успешно изменен!",
        "en": "✅ Language changed successfully!"
    }
    
    await message.answer(res[new_lang], reply_markup=get_main_menu_keyboard(new_lang, bool(user['is_premium'])))
