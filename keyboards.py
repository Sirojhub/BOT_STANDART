from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from config import WEBAPP_URL, PLANS_WEBAPP_URL
import time

def get_language_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🇺🇿 O'zbekcha"), KeyboardButton(text="🇷🇺 Русский")],
        [KeyboardButton(text="🇬🇧 English")]
    ], resize_keyboard=True, one_time_keyboard=True)
    return keyboard

def get_agreement_keyboard(language="en"):
    """
    Returns text keyboard with Web App button.
    Uses cache-busting parameter to prevent Telegram from caching old Web App versions.
    """
    btn_text = {
        "uz": "🚀 Taklifni Ochish",
        "ru": "🚀 Открыть Предложение",
        "en": "🚀 Open Offer"
    }
    
    # Validation for WEBAPP_URL
    base_url = WEBAPP_URL if WEBAPP_URL else "https://sirojhub.github.io/BOT_STANDART/webapp/offer.html"
    
    # Add timestamp for cache busting
    timestamp = int(time.time())
    url = f"{base_url}?lang={language}&v={timestamp}"
    
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn_text.get(language, "en"), web_app=WebAppInfo(url=url))]
    ], resize_keyboard=True)
    return keyboard

def get_phone_keyboard(language="en"):
    """
    Returns keyboard to request phone number contact.
    """
    btn_text = {
        "uz": "📱 Telefon raqamni yuborish",
        "ru": "📱 Отправить номер телефона",
        "en": "📱 Share Phone Number"
    }
    
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn_text.get(language, "en"), request_contact=True)]
    ], resize_keyboard=True)
    return keyboard

def get_main_menu_keyboard(language="en", is_premium=False):
    """
    Returns the main menu keyboard based on language and premium status.
    """
    btn_link = {
        "uz": "🔗 Havolani tekshirish",
        "ru": "🔗 Проверка ссылки",
        "en": "🔗 Link Check"
    }
    btn_file = {
        "uz": "📂 Faylni tekshirish",
        "ru": "📂 Проверка файла",
        "en": "📂 File Check"
    }
    btn_app = {
        "uz": "🛡 Himoya ilovasini faollashtirish",
        "ru": "🛡 Активировать защиту",
        "en": "🛡 Activate Protection App"
    }
    
    # Premium exclusive button text
    btn_monitoring = {
        "uz": "✨ 24/7 Monitoring",
        "ru": "✨ 24/7 Мониторинг",
        "en": "✨ 24/7 Monitoring"
    }

    # Regular user "Coming Soon" text
    btn_app_regular = {
        "uz": "🛡 Himoya (Tez kunda)",
        "ru": "🛡 Защита (Скоро)",
        "en": "🛡 Protection (Coming Soon)"
    }
    
    btn_invite = {
        "uz": "👥 Do'stlarni taklif qilish",
        "ru": "👥 Пригласить друзей",
        "en": "👥 Invite Friends"
    }
    
    rows = [
        [KeyboardButton(text=btn_link.get(language, "en")), KeyboardButton(text=btn_file.get(language, "en"))]
    ]

    if is_premium:
        # Premium users get the active app button and monitoring
        rows.append([KeyboardButton(text=btn_app.get(language, "en"))])
        rows.append([KeyboardButton(text=btn_monitoring.get(language, "en"))])
    else:
        # Regular users get the "Coming Soon" app button
        rows.append([KeyboardButton(text=btn_app_regular.get(language, "en"))])
    
    # Add Invite button for everyone
    rows.append([KeyboardButton(text=btn_invite.get(language, "en"))])
    
    keyboard = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
    return keyboard

def get_back_keyboard(language="en"):
    btn_back = {
        "uz": "⬅️ Ortga",
        "en": "⬅️ Back"
    }
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn_back.get(language, "en"))]
    ], resize_keyboard=True)
    return keyboard

def get_plans_keyboard(language="en", balance=0, test_used="false", is_tg_premium="false"):
    """
    Returns keyboard with a button to open Plans Web App.
    """
    btn_text = {
        "uz": "💎 Tarifni Tanlash",
        "ru": "💎 Выбрать Тариф",
        "en": "💎 Choose Plan"
    }

    # Construct dynamic URL
    # Use explicit PLANS_WEBAPP_URL
    base_url = PLANS_WEBAPP_URL if PLANS_WEBAPP_URL else "https://sirojhub.github.io/BOT_STANDART/webapp/plans.html"

    timestamp = int(time.time())
    
    url = f"{base_url}?lang={language}&balance={balance}&test_used={test_used}&tg_premium={is_tg_premium}&v={timestamp}"
    
    keyboard = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn_text.get(language, "en"), web_app=WebAppInfo(url=url))]
    ], resize_keyboard=True)
    return keyboard
