from aiogram import Router, F, types
from aiogram.filters import StateFilter
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from states import ScanningState
import aiohttp
import hashlib
import os
from config import VT_API_KEY, AD_PLACEHOLDER_TEXT
from keyboards import get_main_menu_keyboard, get_back_keyboard, get_upgrade_keyboard
from utils.formatter import format_scan_report
import asyncio
import re
import logging
import json
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from database import (
    get_user_pricing_info, 
    update_referral_balance, 
    activate_premium, 
    set_test_used,
    get_user
)
from config import WEBAPP_URL, PLANS_WEBAPP_URL

router = Router()
logger = logging.getLogger(__name__)

class SecurityStates(StatesGroup):
    waiting_for_link = State()
    waiting_for_file = State()


# ── VirusTotal Core Functions ─────────────────────────────────────────

async def get_analysis_result(session, analysis_id, language='uz', progress_callback=None):
    """
    Polls VirusTotal for analysis completion with adaptive timing and real-time updates.
    - First 30s: Poll every 3s.
    - After 30s: Poll every 7s.
    - Max attempts: 60 (~5 minutes total).
    """
    url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
    headers = {"x-apikey": VT_API_KEY}
    
    max_attempts = 60
    
    # Progress labels
    labels = {
        "uz": "[AUDIT] Integrity tahlili jarayoni... Urinish {current}/{max}",
        "ru": "[AUDIT] Процесс аудита целостности... Попытка {current}/{max}",
        "en": "[AUDIT] Integrity audit in progress... Attempt {current}/{max}"
    }
    label = labels.get(language, labels["en"])
    
    for attempt in range(1, max_attempts + 1):
        try:
            # Send progress update to UI
            if progress_callback:
                await progress_callback(label.format(current=attempt, max=max_attempts))

            async with session.get(url, headers=headers) as resp:
                if resp.status == 429:
                    await asyncio.sleep(10)
                    continue
                    
                if resp.status != 200:
                    await asyncio.sleep(5)
                    continue
                    
                data = await resp.json()
                attributes = data['data']['attributes']
                status = attributes['status']
                
                if status == 'completed':
                    return attributes
                
                # Adaptive timing
                wait_time = 3 if attempt <= 10 else 7
                await asyncio.sleep(wait_time)
                
        except Exception as e:
            logger.error(f"VT poll error: {e}")
            await asyncio.sleep(5)
    
    return None


async def check_file_hash(session, file_path):
    """Check if file hash already exists in VT database (instant result!)."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()
    
    url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
    headers = {"x-apikey": VT_API_KEY}
    
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                stats = data['data']['attributes']['last_analysis_stats']
                link = f"https://www.virustotal.com/gui/file/{file_hash}/detection"
                logger.info(f"File found in VT cache by hash: {file_hash}")
                return {"stats": stats, "link": link}
    except Exception as e:
        logger.error(f"Hash check error: {e}")
    
    return None


async def scan_url_virustotal(url: str, language='uz', progress_callback=None):
    """Scan URL via VirusTotal with progress tracking."""
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        error_msg = {
            "uz": "VirusTotal API Key o'rnatilmagan.",
            "ru": "API ключ VirusTotal не установлен.",
            "en": "VirusTotal API Key not set."
        }
        return {"error": error_msg.get(language, error_msg["en"])}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        try:
            # Step 1: Submit URL
            if progress_callback:
                await progress_callback("[NETWORK] Global Integrity Nodes bilan aloqa o'rnatilmoqda...")
                
            async with session.post(
                "https://www.virustotal.com/api/v3/urls", 
                data={"url": url}, 
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return {"error": f"API Error: {resp.status}"}
                data = await resp.json()
                analysis_id = data['data']['id']
            
            # Step 2: Poll for results
            result = await get_analysis_result(session, analysis_id, language, progress_callback)
            
            # Build VT link
            try:
                url_id = analysis_id.split('-')[1]
                vt_link = f"https://www.virustotal.com/gui/url/{url_id}/detection"
            except:
                vt_link = f"https://www.virustotal.com/gui/search/{url}"
            
            if result:
                return {"stats": result['stats'], "link": vt_link}
            else:
                to_msg = {
                    "uz": "Tahlil vaqti tugadi (5 min). Natija hali tayyor emas.",
                    "ru": "Время анализа истёкло (5 мин). Результат еще не готов.",
                    "en": "Analysis timed out (5 min). Result is not ready yet."
                }
                return {"error": to_msg.get(language, to_msg["en"])}
                
        except Exception as e:
            return {"error": f"System Error: {e}"}


async def scan_file_virustotal(file_path: str, language='uz', progress_callback=None):
    """Scan file via VirusTotal with progress tracking."""
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        error_msg = {
            "uz": "VirusTotal API Key o'rnatilmagan.",
            "ru": "API ключ VirusTotal не установлен.",
            "en": "VirusTotal API Key not set."
        }
        return {"error": error_msg.get(language, error_msg["en"])}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        
        # ═══ FAST PATH: Check hash first ═══
        if progress_callback:
            await progress_callback("[DATABASE] Global tahlil ma'lumotlar bazasidan qidirilmoqda...")
            
        hash_result = await check_file_hash(session, file_path)
        if hash_result:
            if progress_callback:
                await progress_callback("[INDEX] Integrity indeksi bo'yicha natija topildi!")
            return hash_result
        
        # ═══ SLOW PATH: Upload ═══
        try:
            if progress_callback:
                await progress_callback("[UPLOADER] Ob'ekt chuqur tahlil uchun xavfsiz tugunga yuklanmoqda...")
                
            data = aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=os.path.basename(file_path))
            
            async with session.post(
                "https://www.virustotal.com/api/v3/files", 
                data=data, 
                headers=headers
            ) as resp:
                resp_data = await resp.json()
                
                if resp.status == 409:
                    # Rare but possible if check_file_hash missed something
                    sha256 = hashlib.sha256()
                    with open(file_path, 'rb') as f:
                        for chunk in iter(lambda: f.read(8192), b''):
                            sha256.update(chunk)
                    file_hash = sha256.hexdigest()
                    
                    async with session.get(
                        f"https://www.virustotal.com/api/v3/files/{file_hash}", 
                        headers=headers
                    ) as hash_resp:
                        if hash_resp.status == 200:
                            hash_data = await hash_resp.json()
                            stats = hash_data['data']['attributes']['last_analysis_stats']
                            link = f"https://www.virustotal.com/gui/file/{file_hash}/detection"
                            return {"stats": stats, "link": link}
                    return {"error": "API Error: 409 Fetch Failure"}
                
                elif resp.status != 200:
                    return {"error": f"Upload Error: {resp.status}"}
                
                analysis_id = resp_data['data']['id']
            
            # Poll for results
            result = await get_analysis_result(session, analysis_id, language, progress_callback)
            vt_link = f"https://www.virustotal.com/gui/file-analysis/{analysis_id}/detection"
            
            if result:
                return {"stats": result['stats'], "link": vt_link}
            else:
                to_msg = {
                    "uz": "Tahlil vaqti tugadi (5 min). Fayl juda katta bo'lishi mumkin.",
                    "ru": "Время анализа истёкло (5 мин). Файл может быть слишком большим.",
                    "en": "Analysis timed out (5 min). File might be too large."
                }
                return {"error": to_msg.get(language, to_msg["en"])}
        except Exception as e:
            return {"error": f"System Error: {e}"}


# ── Navigation Handlers ──────────────────────────────────────────────

@router.message(StateFilter("*"), F.text.in_({"🔗 Havola Auditi", "🔗 Аудит ссылки", "🔗 Link Audit", "🔗 Havolani tekshirish", "🔗 Проверка ссылки", "🔗 Link Check"}))
async def nav_link_check(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user['language'] if user else "uz"
    
    responses = {
        "uz": "Havolani yuboring (http:// yoki https:// bilan):",
        "ru": "Отправьте ссылку (с http:// или https://):",
        "en": "Please send the link (with http:// or https://):"
    }
    
    await message.answer(responses.get(lang, responses["en"]), reply_markup=get_back_keyboard(lang))
    await state.set_state(SecurityStates.waiting_for_link)

@router.message(StateFilter("*"), F.text.in_({"📂 Fayl Xavfsizligi", "📂 Безопасность файла", "📂 File Security Audit", "📂 Faylni tekshirish", "📂 Проверка файла", "📂 File Check"}))
async def nav_file_check(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user['language'] if user else "uz"
    
    responses = {
        "uz": "Tekshirish uchun faylni yuboring (max 20MB):",
        "ru": "Отправьте файл для проверки (макс 20МБ):",
        "en": "Please send the file to check (max 20MB):"
    }
    
    await message.answer(responses.get(lang, responses["en"]), reply_markup=get_back_keyboard(lang))
    await state.set_state(SecurityStates.waiting_for_file)

@router.message(StateFilter("*"), F.text.in_({"🛡 Himoya Ekotizimi", "🛡 Экосистема защиты", "🛡 Protection Ecosystem", "🛡 Himoya ilovasini faollashtirish", "🛡 Активировать защиту", "🛡 Activate Protection App"}))
async def nav_protection_app(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_pricing_info(user_id)
    user_info = await get_user(user_id)
    lang = user_info['language'] if user_info else "uz"
    
    if stats:
        balance = stats['balance']
        is_premium = str(stats['is_premium']).lower()
        test_used = str(stats['test_used']).lower()
        is_tg_premium = str(message.from_user.is_premium or False).lower()
        
        # Build URL with params
        base_url = PLANS_WEBAPP_URL if PLANS_WEBAPP_URL else f"{WEBAPP_URL}/plans.html"
        url = f"{base_url}?lang={lang}&balance={balance}&test_used={test_used}&tg_premium={is_tg_premium}"
        
        # Use centralized keyboard
        keyboard = get_upgrade_keyboard(url, lang)

        # Labels
        titles = {
            "uz": "🛡 <b>Integrity Protection (Pro)</b>",
            "ru": "🛡 <b>Integrity Protection (Pro)</b>",
            "en": "🛡 <b>Integrity Protection (Pro)</b>"
        }
        
        test_prompt = {
            "uz": (
                "Siz hozirda <b>Bazaviy Sinov</b> rejimidamisiz. Ushbu modul to'liq xizmat ko'rsatish doirasida ishlaydi.\n"
                "To'liq ekotizimni faollashtirish va maxsus identifikatsiya kodini olish uchun <b>Standart</b> yoki <b>Premium</b> darajaga o'ting.\n\n"
                "⬇️ <b>Xizmatni faollashtirish uchun:</b>"
            ),
            "ru": (
                "Вы находитесь в режиме <b>Базового Тестирования</b>. Данный модуль работает в рамках полного пакета услуг.\n"
                "Для активации полной экосистемы и получения идентификационного кода перейдите на <b>Стандарт</b> или <b>Премиум</b>.\n\n"
                "⬇️ <b>Для активации функции:</b>"
            ),
            "en": (
                "You are currently in <b>Base Trial</b> mode. This module operates within the full service scope.\n"
                "To activate the full ecosystem and receive an identification code, please upgrade to <b>Standard</b> or <b>Premium</b>.\n\n"
                "⬇️ <b>To activate the service:</b>"
            )
        }

        # If user is on TEST PLAN
        if stats['test_used'] and stats['is_premium']:
             await message.answer(
                f"{titles.get(lang, titles['en'])}\n\n{test_prompt.get(lang, test_prompt['en'])}",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
             return
        
        # If user is Standard/Premium (Paid) or Not Premium
        main_prompt = {
            "uz": (
                "🛡 <b>SARHAD Premium</b>\n\n"
                "Tarif rejasini tanlash va himoyani kuchaytirish uchun quyidagi tugmani bosing:\n\n"
                "⬇️ <b>Pastdagi tugmani bosing:</b>"
            ),
            "ru": (
                "🛡 <b>SARHAD Premium</b>\n\n"
                "Нажмите кнопку ниже, чтобы выбрать тариф и усилить защиту:\n\n"
                "⬇️ <b>Нажмите на кнопку ниже:</b>"
            ),
            "en": (
                "🛡 <b>SARHAD Premium</b>\n\n"
                "Press the button below to choose a plan and strengthen protection:\n\n"
                "⬇️ <b>Press the button below:</b>"
            )
        }
        await message.answer(
            main_prompt.get(lang, main_prompt['en']),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        error_msg = {
            "uz": "⚠️ Ma'lumotlarni yuklashda xatolik bo'ldi.",
            "ru": "⚠️ Ошибка загрузки данных.",
            "en": "⚠️ Error loading data."
        }
        await message.answer(error_msg.get(lang, error_msg["en"]))


@router.message(F.web_app_data)
async def process_buy_plan(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "buy_plan":
            plan = data.get("plan")
            user_id = message.from_user.id
            stats = await get_user_pricing_info(user_id)
            user_info = await get_user(user_id)
            language = user_info['language'] if user_info else "uz"
            
            if not stats:
                error_msgs = {
                    "uz": "❌ Xatolik yuz berdi.",
                    "ru": "❌ Произошла ошибка.",
                    "en": "❌ An error occurred."
                }
                await message.answer(error_msgs.get(language, error_msgs["en"]))
                return

            balance = stats['balance']
            
            if plan == "test":
                if stats['test_used']:
                    test_used_msg = {
                        "uz": "⚠️ Siz allaqachon bepul sinov davridan foydalangansiz.",
                        "ru": "⚠️ Вы уже использовали бесплатный пробный период.",
                        "en": "⚠️ You have already used the free trial period."
                    }
                    await message.answer(test_used_msg.get(language, test_used_msg["en"]))
                else:
                    await set_test_used(user_id)
                    success_msg = {
                        "uz": "✅ <b>XIZMAT FAOLLASHTIRILDI</b>\n\nSizning 24 soatlik sinov auditi davringiz faollashtirildi. Operatsion cheklovlar vaqtinchalik olib tashlandi.",
                        "ru": "✅ <b>СЕРВИС АКТИВИРОВАН</b>\n\nВаш 24-часовой период пробного аудита активирован. Операционные ограничения временно сняты.",
                        "en": "✅ <b>SERVICE ACTIVATED</b>\n\nYour 24-hour trial audit period has been activated. Operational restrictions have been temporarily removed."
                    }
                    await message.answer(
                        success_msg.get(language, success_msg["en"]), 
                        parse_mode="HTML",
                        reply_markup=get_main_menu_keyboard(language, is_premium=True)
                    )

            elif plan == "standard":
                price = 8000
                card_number = "0000 0000 0000 0000"
                admin_contact = "@admin"
                
                pay_text = {
                    "uz": (
                        f"🛡 <b>Xizmatni faollashtirish uchun rekvizitlar:</b>\n\n"
                        f"🔢 Tranzaksiya manzili: <code>{card_number}</code>\n"
                        f"💰 Qiymati: <b>{price} so'm</b>\n\n"
                        f"❗️ Tranzaksiyadan so'ng, tasdiqlovchi hujjatni (faktura/skrinshot) administratorga yuboring:\n"
                        f"👤 Inspektor: {admin_contact}\n\n"
                        f"⏳ <i>Xizmat darajasi tasdiqlash jarayonidan so'ng faollashtiriladi.</i>"
                    ),
                    "ru": (
                        f"🛡 <b>Реквизиты для активации сервиса:</b>\n\n"
                        f"🔢 Адрес транзакции: <code>{card_number}</code>\n"
                        f"💰 Стоимость: <b>{price} сум</b>\n\n"
                        f"❗️ После совершения транзакции отправьте подтверждающий документ (фактуру/скриншот) администратору:\n"
                        f"👤 Инспектор: {admin_contact}\n\n"
                        f"⏳ <i>Уровень сервиса будет активирован после процедуры подтверждения.</i>"
                    ),
                    "en": (
                        f"🛡 <b>Service activation details:</b>\n\n"
                        f"🔢 Transaction address: <code>{card_number}</code>\n"
                        f"💰 Value: <b>{price} UZS</b>\n\n"
                        f"❗️ After transaction, send the confirmation document (invoice/screenshot) to the administrator:\n"
                        f"👤 Inspector: {admin_contact}\n\n"
                        f"⏳ <i>Service level will be activated after the verification process.</i>"
                    )
                }
                await message.answer(pay_text.get(language, pay_text["en"]), parse_mode="HTML")

            elif plan == "premium":
                price = 20000
                if not message.from_user.is_premium:
                     prem_req = {
                         "uz": "🔒 Bu tarif faqat Telegram Premium egalari uchun.",
                         "ru": "🔒 Этот тариф только для владельцев Telegram Premium.",
                         "en": "🔒 This plan is for Telegram Premium users only."
                     }
                     await message.answer(prem_req.get(language, prem_req["en"]))
                     return
                     
                card_number = "0000 0000 0000 0000"
                admin_contact = "@admin"
                
                pay_text_p = {
                    "uz": (
                        f"💳 <b>To'lov uchun rekvizitlar (Premium):</b>\n\n"
                        f"🔢 Karta: <code>{card_number}</code>\n"
                        f"💰 Narxi: <b>{price} so'm</b>\n\n"
                        f"❗️ To'lovni amalga oshirgandan so'ng, chekni (skrinshot) administratorga yuboring:\n"
                        f"👤 Admin: {admin_contact}\n\n"
                        f"⏳ <i>To'lov tasdiqlangach, tarifingiz faollashtiriladi.</i>"
                    ),
                    "ru": (
                        f"💳 <b>Реквизиты для оплаты (Premium):</b>\n\n"
                        f"🔢 Карта: <code>{card_number}</code>\n"
                        f"💰 Цена: <b>{price} сум</b>\n\n"
                        f"❗️ После оплаты отправьте чек (скриншот) администратору:\n"
                        f"👤 Админ: {admin_contact}\n\n"
                        f"⏳ <i>Ваш тариф будет активирован после подтверждения оплаты.</i>"
                    ),
                    "en": (
                        f"💳 <b>Payment details (Premium):</b>\n\n"
                        f"🔢 Card: <code>{card_number}</code>\n"
                        f"💰 Price: <b>{price} UZS</b>\n\n"
                        f"❗️ After payment, send the receipt (screenshot) to the administrator:\n"
                        f"👤 Admin: {admin_contact}\n\n"
                        f"⏳ <i>Plan will be activated after confirmation.</i>"
                    )
                }
                await message.answer(pay_text_p.get(language, pay_text_p["en"]), parse_mode="HTML")
    except Exception as e:
        logger.error(f"WebApp data error: {e}")
        await message.answer("⚠️ Xatolik yuz berdi.")

@router.message(StateFilter("*"), F.text.in_({"👥 Hamkorlik Dasturi", "👥 Партнерская программа", "👥 Partnership Program", "👥 Do'stlarni taklif qilish", "👥 Пригласить друзей", "👥 Invite Friends"}))
async def nav_invite(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    lang = user['language'] if user else "uz"
    
    # Fetch bot username dynamically
    bot_user = await message.bot.get_me()
    bot_username = bot_user.username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    responses = {
        "uz": (
            f"👥 <b>Do'stlarni Taklif Qilish</b>\n\n"
            f"Sizning shaxsiy taklif havolangiz:\n"
            f"🔗 <code>{referral_link}</code>\n\n"
            f"Do'stingiz shu havola orqali kirib, Premium xarid qilsa, sizga <b>1000 so'm</b> bonus beriladi!"
        ),
        "ru": (
            f"👥 <b>Пригласить Друзей</b>\n\n"
            f"Ваша личная реферальная ссылка:\n"
            f"🔗 <code>{referral_link}</code>\n\n"
            f"Если друг перейдет по ссылке и купит Premium, вы получите <b>1000 сум</b> бонуса!"
        ),
        "en": (
            f"👥 <b>Invite Friends</b>\n\n"
            f"Your personal referral link:\n"
            f"🔗 <code>{referral_link}</code>\n\n"
            f"If a friend joins via this link and buys Premium, you will receive a <b>1,000 UZS</b> bonus!"
        )
    }
    
    await message.answer(responses.get(lang, responses["en"]), parse_mode="HTML")

@router.message(StateFilter("*"), F.text.in_({"✨ 24/7 Monitoring", "✨ 24/7 Мониторинг"}))
async def nav_monitoring(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_pricing_info(user_id)

    if stats and stats['test_used'] and stats['is_premium']:
        # User is on Test Plan -> Restrict Access
        user_info = await get_user(user_id)
        lang = user_info['language'] if user_info else "uz"
        
        balance = stats['balance']
        test_used = str(stats['test_used']).lower()
        is_tg_premium = str(message.from_user.is_premium or False).lower()
        
        base_url = PLANS_WEBAPP_URL if PLANS_WEBAPP_URL else f"{WEBAPP_URL}/plans.html"
        url = f"{base_url}?lang={lang}&balance={balance}&test_used={test_used}&tg_premium={is_tg_premium}"
        
        # Use centralized keyboard
        keyboard = get_upgrade_keyboard(url, lang)
        
        text = {
            "uz": (
                "🚫 <b>Ruxsat cheklangan</b>\n\n"
                "24/7 Monitoring funksiyasi <b>Test Tarifida</b> ishlamaydi.\n"
                "To'liq himoya uchun <b>Standart</b> yoki <b>Premium</b> tarifni tanlang.\n\n"
                "⬇️ <b>Pastdagi tugmani bosing:</b>"
            ),
            "ru": (
                "🚫 <b>Доступ ограничен</b>\n\n"
                "Функция 24/7 Мониторинга не работает в <b>Тестовом Тарифе</b>.\n"
                "Выберите <b>Стандарт</b> или <b>Премиум</b> для полной защиты.\n\n"
                "⬇️ <b>Нажмите кнопку ниже:</b>"
            ),
            "en": (
                "🚫 <b>Access Restricted</b>\n\n"
                "The 24/7 Monitoring feature is not available in the <b>Test Plan</b>.\n"
                "Please choose a <b>Standard</b> or <b>Premium</b> plan for full protection.\n\n"
                "⬇️ <b>Click the button below:</b>"
            )
        }
        
        await message.answer(
            text.get(lang, text["en"]),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    success_msg = {
        "uz": "✅ 24/7 Monitoring Premium hisobingiz uchun faol.",
        "ru": "✅ 24/7 Мониторинг активен для вашего Премиум аккаунта.",
        "en": "✅ 24/7 Monitoring is active for your Premium account."
    }
    await message.answer(success_msg.get(lang, success_msg["en"]))

@router.message(StateFilter("*"), F.text.in_({"⬅️ Ortga", "⬅️ Назад", "⬅️ Back"}))
async def nav_back(message: types.Message, state: FSMContext):
    user = await get_user(message.from_user.id)
    lang = user['language'] if user else "uz"
    is_premium = bool(user['is_premium']) if user else False
    
    responses = {
        "uz": "Bosh menyu:",
        "ru": "Главное меню:",
        "en": "Main Menu:"
    }
    
    await message.answer(responses.get(lang, "en"), reply_markup=get_main_menu_keyboard(lang, is_premium))
    await state.clear()


# ── Scan Handlers ─────────────────────────────────────────────────────

@router.message(SecurityStates.waiting_for_link, F.text)
async def process_link_check(message: types.Message, state: FSMContext):
    url = message.text
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'

    if not url.startswith("http"):
        err_msg = {
            "uz": "⚠️ Noto'g'ri URL. http:// yoki https:// bilan boshlang.",
            "ru": "⚠️ Неверный URL. Начните с http:// или https://.",
            "en": "⚠️ Invalid URL. Start with http:// or https://."
        }
        await message.reply(err_msg.get(lang, err_msg["en"]))
        return

    try:
        await message.delete()
    except:
        pass

    # Terminal-style initial message
    init_msg = {
        "uz": f"<b>[SYSTEM]</b> Havolani tahlil qilish tayyorlanmoqda...\n<code>TARGET: {url}</code>",
        "ru": f"<b>[SYSTEM]</b> Подготовка к анализу ссылки...\n<code>TARGET: {url}</code>",
        "en": f"<b>[SYSTEM]</b> Preparing link analysis...\n<code>TARGET: {url}</code>"
    }
    status_msg = await message.answer(init_msg.get(lang, init_msg["en"]), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    
    await state.set_state(ScanningState.processing)

    async def progress_update(text):
        try:
            # We wrap the update in a code block for terminal feel
            await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
        except:
            pass

    result = await scan_url_virustotal(url, lang, progress_update)
    
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="HTML")
        
    await message.answer("Menyu:", reply_markup=get_main_menu_keyboard(lang, user_db['is_premium'] if user_db else False))
    await state.clear()

@router.message(SecurityStates.waiting_for_file, F.document)
async def process_file_check(message: types.Message, state: FSMContext):
    document = message.document
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'
    
    if document.file_size > 20 * 1024 * 1024:
        limit_msg = {
            "uz": "⚠️ Fayl juda katta. Maksimum 20MB.",
            "ru": "⚠️ Файл слишком большой. Максимум 20МБ.",
            "en": "⚠️ File too large. Maximum 20MB."
        }
        await message.reply(limit_msg.get(lang, limit_msg["en"]))
        return

    try:
        await message.delete()
    except:
        pass

    init_msg = {
        "uz": f"<b>[SYSTEM]</b> Fayl qabul qilindi: <code>{document.file_name}</code>\nInisializatsiya...",
        "ru": f"<b>[SYSTEM]</b> Файл получен: <code>{document.file_name}</code>\nИнициализация...",
        "en": f"<b>[SYSTEM]</b> File received: <code>{document.file_name}</code>\nInitializing..."
    }
    status_msg = await message.answer(init_msg.get(lang, init_msg["en"]), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    
    await state.set_state(ScanningState.processing)

    async def progress_update(text):
        try:
            await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
        except:
            pass

    # Download
    try:
        await progress_update("[DL] Transferring to secure buffer...")
        file_id = document.file_id
        file_info = await message.bot.get_file(file_id)
        local_path = f"downloads/{document.file_name}"
        os.makedirs("downloads", exist_ok=True)
        await message.bot.download_file(file_info.file_path, local_path)
    except Exception as e:
        logger.error(f"Download error: {e}")
        error_msgs = {
            "uz": "❌ Faylni yuklab olishda xatolik.",
            "ru": "❌ Ошибка при загрузке файла.",
            "en": "❌ Download error."
        }
        await status_msg.edit_text(error_msgs.get(lang, error_msgs["en"]))
        await message.answer("Menyu:", reply_markup=get_main_menu_keyboard(lang, user_db['is_premium'] if user_db else False))
        await state.clear()
        return
    
    result = await scan_file_virustotal(local_path, lang, progress_update)
    
    try:
        os.remove(local_path)
    except:
        pass

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="HTML")
        
    await message.answer("Menyu:", reply_markup=get_main_menu_keyboard(lang, user_db['is_premium'] if user_db else False))
    await state.clear()

@router.message(StateFilter(ScanningState.processing))
async def block_while_scanning(message: types.Message):
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'
    err_msg = {
        "uz": "❌ [XATO]: Tizim band. Skanerlash jarayoni tugashini kuting.",
        "ru": "❌ [ОШИБКА]: Система занята. Подождите завершения сканирования.",
        "en": "❌ [ERROR]: System busy. Please wait for the scan to complete."
    }
    await message.delete()  # Remove the user's message
    await message.answer(err_msg.get(lang, err_msg["en"]))

# ── 24/7 Monitoring (Private Chat) ───────────────────────────────────

@router.message(F.text.startswith("http") | F.document)
async def monitor_messages(message: types.Message):
    """Background listener for Premium users."""

    user = message.from_user
    is_premium = user.is_premium or False
    
    if not is_premium:
        return
    
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'

    if message.text and message.text.startswith("http"):
        # We find all URLs to be safe
        import re
        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message.text)
        if not urls: return

        mon_msg = {
            "uz": "🛡 <b>Integrity Monitoring:</b> Havola aniqlandi. Xavfsizlik auditi boshlanmoqda...",
            "ru": "🛡 <b>Integrity Monitoring:</b> Обнаружена ссылка. Запуск экспресс-аудита...",
            "en": "🛡 <b>Integrity Monitoring:</b> Link detected. Initiating security audit..."
        }
        status_msg = await message.reply(mon_msg.get(lang, mon_msg["en"]), parse_mode="HTML")

        async def progress_update(text):
            try: await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
            except: pass

        for url in urls:
            result = await scan_url_virustotal(url, lang, progress_update)
            if "error" in result:
                await status_msg.edit_text(f"❌ {result['error']}")
            else:
                text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                await status_msg.edit_text(text, parse_mode="HTML")
    
    elif message.document:
        if message.document.file_size > 20 * 1024 * 1024:
            return
        
        mon_msg_f = {
            "uz": "🛡 <b>Integrity Monitoring:</b> Fayl ob'ekti aniqlandi. Audit jarayoni faollashtirilmoqda...",
            "ru": "🛡 <b>Integrity Monitoring:</b> Обнаружен файл. Активация процесса аудита...",
            "en": "🛡 <b>Integrity Monitoring:</b> File object detected. Activating audit sequence..."
        }
        status_msg = await message.reply(mon_msg_f.get(lang, mon_msg_f["en"]), parse_mode="HTML")

        async def progress_update(text):
            try: await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
            except: pass

        try:
            await progress_update("[NETWORK] Ob'ekt qabul qilinmoqda...")
            file = await message.bot.get_file(message.document.file_id)
            local_path = f"downloads/mon_{message.document.file_name}"
            os.makedirs("downloads", exist_ok=True)
            await message.bot.download_file(file.file_path, local_path)
            
            result = await scan_file_virustotal(local_path, lang, progress_update)
            try: os.remove(local_path)
            except: pass
            
            if "error" in result:
                await status_msg.edit_text(f"❌ {result['error']}")
            else:
                text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                await status_msg.edit_text(text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Monitoring error: {e}")


# ── 24/7 Monitoring (Business Connection) ────────────────────────────

@router.business_message(F.text | F.document)
async def business_monitoring(message: types.Message):
    """Monitors messages from Telegram Business connection."""
    try:
        data = await message.bot.get_business_connection(message.business_connection_id)
        owner_chat_id = data.user_chat_id
    except Exception as e:
        logger.error(f"Business connection error: {e}")
        return

    user_db = await get_user(owner_chat_id)
    lang = user_db['language'] if user_db else 'uz'

    # Process URLs
    if message.text:
        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message.text)
        for url in urls:
            # For business messages, we might not want to flood with status updates, 
            # but let's provide a final report or a single "Scanning" message.
            status_msg = await message.bot.send_message(owner_chat_id, f"🛡 <b>[BIZ_MONITOR]</b> Scanning link: <code>{url}</code>", parse_mode="HTML")
            
            async def progress_update(text):
                try: await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
                except: pass

            result = await scan_url_virustotal(url, lang, progress_update)
            if "error" in result:
                await status_msg.edit_text(f"⚠️ {result['error']} ({url})")
            else:
                text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                await status_msg.edit_text(text, parse_mode="HTML")

    # Process Document
    if message.document:
        doc = message.document
        if doc.file_size > 20 * 1024 * 1024:
            await message.bot.send_message(owner_chat_id, f"⚠️ Fayl juda katta: {doc.file_name}")
        else:
            try:
                mon_msg_b = {
                    "uz": f"🛡 <b>[BIZ_AUDIT]</b> Ob'ekt aniqlandi: <code>{doc.file_name}</code>",
                    "ru": f"🛡 <b>[BIZ_AUDIT]</b> Объект обнаружен: <code>{doc.file_name}</code>",
                    "en": f"🛡 <b>[BIZ_AUDIT]</b> Object detected: <code>{doc.file_name}</code>"
                }
                status_msg = await message.bot.send_message(owner_chat_id, mon_msg_b.get(lang, mon_msg_b["en"]), parse_mode="HTML")
                
                async def progress_update(text):
                    try: await status_msg.edit_text(f"<code>{text}</code>", parse_mode="HTML")
                    except: pass
                
                await progress_update("[NETWORK] Ob'ekt transferi...")
                file_info = await message.bot.get_file(doc.file_id)
                local_path = f"downloads/biz_{doc.file_name}"
                os.makedirs("downloads", exist_ok=True)
                await message.bot.download_file(file_info.file_path, local_path)
                
                result = await scan_file_virustotal(local_path, lang, progress_update)
                try: os.remove(local_path)
                except: pass
                
                if "error" in result:
                    await status_msg.edit_text(f"❌ {result['error']}")
                else:
                    text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                    await status_msg.edit_text(text, parse_mode="HTML")
            except Exception as e:
                await message.bot.send_message(owner_chat_id, f"❌ Xatolik: {e}")
