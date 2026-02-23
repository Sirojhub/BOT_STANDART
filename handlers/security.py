from aiogram import Router, F, types
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp
import hashlib
import os
from config import VT_API_KEY, AD_PLACEHOLDER_TEXT
from keyboards import get_main_menu_keyboard, get_back_keyboard
from utils.formatter import format_scan_report
import asyncio
import re
import logging
import json
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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

async def get_analysis_result(session, analysis_id, max_attempts=15, interval=3):
    """Polls VirusTotal for analysis completion with configurable retries."""
    url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
    headers = {"x-apikey": VT_API_KEY}
    
    for attempt in range(max_attempts):
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"VT poll attempt {attempt+1}: status {resp.status}")
                    await asyncio.sleep(interval)
                    continue
                data = await resp.json()
                attributes = data['data']['attributes']
                status = attributes['status']
                logger.info(f"VT poll attempt {attempt+1}: status={status}")
                
                if status == 'completed':
                    return attributes
                elif status == 'queued':
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"VT poll error: {e}")
            await asyncio.sleep(interval)
    
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


async def scan_url_virustotal(url: str):
    """Scan URL via VirusTotal."""
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        return {"error": "VirusTotal API Key o'rnatilmagan."}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        try:
            # Step 1: Submit URL
            async with session.post(
                "https://www.virustotal.com/api/v3/urls", 
                data={"url": url}, 
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return {"error": f"URL yuborishda xatolik: {resp.status}"}
                data = await resp.json()
                analysis_id = data['data']['id']
            
            # Step 2: Poll for results (URL scans are usually fast)
            result = await get_analysis_result(session, analysis_id, max_attempts=10, interval=2)
            
            # Build VT link
            try:
                url_id = analysis_id.split('-')[1]
                link = f"https://www.virustotal.com/gui/url/{url_id}/detection"
            except:
                link = f"https://www.virustotal.com/gui/search/{url}"
            
            if result:
                return {"stats": result['stats'], "link": link}
            else:
                return {"error": "Tahlil vaqti tugadi. Keyinroq urinib ko'ring."}
                
        except Exception as e:
            return {"error": f"URL tekshirishda xatolik: {e}"}


async def scan_file_virustotal(file_path: str):
    """Scan file via VirusTotal — first checks hash cache for instant results."""
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        return {"error": "VirusTotal API Key o'rnatilmagan."}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        
        # ═══ FAST PATH: Check hash first (instant!) ═══
        hash_result = await check_file_hash(session, file_path)
        if hash_result:
            return hash_result
        
        # ═══ SLOW PATH: Upload file for new analysis ═══
        try:
            data = aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=os.path.basename(file_path))
            
            async with session.post(
                "https://www.virustotal.com/api/v3/files", 
                data=data, 
                headers=headers
            ) as resp:
                resp_data = await resp.json()
                
                if resp.status == 409:
                    # File already exists in VT — get results by hash
                    logger.info("VT 409: File already exists, fetching by hash")
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
                    return {"error": "Fayl VT bazasida bor, lekin natijani olishda xatolik."}
                
                elif resp.status != 200:
                    return {"error": f"Fayl yuklashda xatolik: {resp.status}"}
                
                analysis_id = resp_data['data']['id']
            
            # Poll for results (file scans take longer)
            result = await get_analysis_result(session, analysis_id, max_attempts=15, interval=3)
            link = f"https://www.virustotal.com/gui/file-analysis/{analysis_id}/detection"
            
            if result:
                return {"stats": result['stats'], "link": link}
            else:
                return {"error": "Tahlil vaqti tugadi. Fayl katta bo'lishi mumkin — keyinroq urinib ko'ring."}
        except Exception as e:
            return {"error": f"Fayl tekshirishda xatolik: {e}"}


# ── Navigation Handlers ──────────────────────────────────────────────

@router.message(F.text.in_({"🔗 Havolani tekshirish", "🔗 Проверка ссылки", "🔗 Link Check"}))
async def nav_link_check(message: types.Message, state: FSMContext):
    lang = "en"
    if "Havolani" in message.text: lang = "uz"
    elif "Проверка" in message.text: lang = "ru"
    
    responses = {
        "uz": "Havolani yuboring (http:// yoki https:// bilan):",
        "ru": "Отправьте ссылку (с http:// или https://):",
        "en": "Please send the link (with http:// or https://):"
    }
    
    await state.update_data(language=lang)
    await message.answer(responses[lang], reply_markup=get_back_keyboard(lang))
    await state.set_state(SecurityStates.waiting_for_link)

@router.message(F.text.in_({"📂 Faylni tekshirish", "📂 Проверка файла", "📂 File Check"}))
async def nav_file_check(message: types.Message, state: FSMContext):
    lang = "en"
    if "Faylni" in message.text: lang = "uz"
    elif "Проверка" in message.text: lang = "ru"
    
    responses = {
        "uz": "Tekshirish uchun faylni yuboring (max 20MB):",
        "ru": "Отправьте файл для проверки (макс 20МБ):",
        "en": "Please send the file to check (max 20MB):"
    }
    
    await state.update_data(language=lang)
    await message.answer(responses[lang], reply_markup=get_back_keyboard(lang))
    await state.set_state(SecurityStates.waiting_for_file)

@router.message(F.text.in_({"🛡 Himoya ilovasini faollashtirish", "🛡 Активировать защиту", "🛡 Activate Protection App", 
                           "🛡 Himoya (Tez kunda)", "🛡 Защита (Скоро)", "🛡 Protection (Coming Soon)"}))
async def nav_protection_app(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_pricing_info(user_id)
    
    if stats:
        balance = stats['balance']
        is_premium = str(stats['is_premium']).lower()
        test_used = str(stats['test_used']).lower()
        is_tg_premium = str(message.from_user.is_premium or False).lower()
        
        # Build URL with params
        base_url = PLANS_WEBAPP_URL if PLANS_WEBAPP_URL else f"{WEBAPP_URL}/plans.html"
        url = f"{base_url}?lang={message.from_user.language_code}&balance={balance}&test_used={test_used}&tg_premium={is_tg_premium}"
        
        # Use ReplyKeyboardMarkup because InlineWebApps cannot send data back to the bot via sendData
        keyboard = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="💎 Upgrade Plan / Tarifni Kuchaytirish", web_app=WebAppInfo(url=url))],
            [KeyboardButton(text="⬅️ Ortga")]
        ], resize_keyboard=True)

        # If user is on TEST PLAN (test_used=True and is_premium=True), show Upgrade Prompt
        # Note: We assume is_premium=True if test is active. 
        if stats['test_used'] and stats['is_premium']:
             await message.answer(
                "🔒 <b>Himoya Ilovasi (Pro)</b>\n\n"
                "Siz hozir <b>Test Tarifidasiz</b>. Bu funksiya faqat to'liq versiyada ishlaydi.\n"
                "Ilovani yuklab olish va aktivatsiya kodi olish uchun <b>Standart</b> yoki <b>Premium</b> tarifga o'ting.\n\n"
                "Вы находитесь на <b>Тестовом Тарифе</b>. Эта функция доступна только в полной версии.\n"
                "Перейдите на <b>Стандарт</b> или <b>Премиум</b>, чтобы получить приложение и код активации.\n\n"
                "⬇️ <b>Pastdagi tugmani bosing:</b>",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
             return
        
        # If user is Standard/Premium (Paid) or Not Premium
        await message.answer(
            "🛡 <b>SARHAD Premium</b>\n\n"
            "Tarif rejasini tanlash va himoyani kuchaytirish uchun quyidagi tugmani bosing:\n"
            "Нажмите кнопку ниже, чтобы выбрать тариф и усилить защиту:\n\n"
            "⬇️ <b>Pastdagi tugmani bosing:</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await message.answer("⚠️ Ma'lumotlarni yuklashda xatolik bo'ldi.")


@router.message(F.web_app_data)
async def process_buy_plan(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "buy_plan":
            plan = data.get("plan")
            user_id = message.from_user.id
            stats = await get_user_pricing_info(user_id)
            
            if not stats:
                await message.answer("❌ Xatolik yuz berdi.")
                return

            # Fetch user language for consistent UI
            user_info = await get_user(user_id)
            language = user_info[8] if user_info else "en"  # user_info[8] is language column

            balance = stats['balance']
            
            if plan == "test":
                if stats['test_used']:
                    await message.answer("⚠️ Siz allaqachon bepul sinov davridan foydalangansiz.")
                else:
                    await set_test_used(user_id)
                    await message.answer(
                        "✅ <b>TABRIKLAYMIZ!</b>\n\nSizning 24 soatlik sinov davringiz faollashtirildi. Barcha cheklovlar olib tashlandi.", 
                        parse_mode="HTML",
                        reply_markup=get_main_menu_keyboard(language, is_premium=True)
                    )

            elif plan == "standard":
                price = 8000
                # Manual Payment Flow
                card_number = "0000 0000 0000 0000"
                admin_contact = "@admin"
                
                await message.answer(
                    f"💳 <b>To'lov uchun rekvizitlar:</b>\n\n"
                    f"🔢 Karta: <code>{card_number}</code>\n"
                    f"💰 Narxi: <b>{price} so'm</b>\n\n"
                    f"❗️ To'lovni amalga oshirgandan so'ng, chekni (skrinshot) administratorga yuboring:\n"
                    f"👤 Admin: {admin_contact}\n\n"
                    f"⏳ <i>To'lov tasdiqlangach, tarifingiz faollashtiriladi.</i>\n\n"
                    f"💳 <b>Реквизиты для оплаты:</b>\n\n"
                    f"🔢 Карта: <code>{card_number}</code>\n"
                    f"💰 Цена: <b>{price} сум</b>\n\n"
                    f"❗️ После оплаты отправьте чек (скриншот) администратору:\n"
                    f"👤 Админ: {admin_contact}",
                    parse_mode="HTML"
                )

            elif plan == "premium":
                price = 20000
                # Check TG Premium requirement
                if not message.from_user.is_premium:
                     await message.answer("🔒 Bu tarif faqat Telegram Premium egalari uchun.")
                     return
                     
                # Manual Payment Flow
                card_number = "0000 0000 0000 0000"
                admin_contact = "@admin"
                
                await message.answer(
                    f"💳 <b>To'lov uchun rekvizitlar (Premium):</b>\n\n"
                    f"🔢 Karta: <code>{card_number}</code>\n"
                    f"💰 Narxi: <b>{price} so'm</b>\n\n"
                    f"❗️ To'lovni amalga oshirgandan so'ng, chekni (skrinshot) administratorga yuboring:\n"
                    f"👤 Admin: {admin_contact}\n\n"
                    f"⏳ <i>To'lov tasdiqlangach, tarifingiz faollashtiriladi.</i>\n\n"
                    f"💳 <b>Реквизиты для оплаты (Premium):</b>\n\n"
                    f"🔢 Карта: <code>{card_number}</code>\n"
                    f"💰 Цена: <b>{price} сум</b>\n\n"
                    f"❗️ После оплаты отправьте чек (скриншот) администратору:\n"
                    f"👤 Админ: {admin_contact}",
                    parse_mode="HTML"
                )
    except Exception as e:
        logger.error(f"WebApp data error: {e}")
        await message.answer("⚠️ Xatolik yuz berdi.")

@router.message(F.text.in_({"👥 Do'stlarni taklif qilish", "👥 Пригласить друзей", "👥 Invite Friends"}))
async def nav_invite(message: types.Message):
    user_id = message.from_user.id
    user_id = message.from_user.id
    # Fetch bot username dynamically
    bot_user = await message.bot.get_me()
    bot_username = bot_user.username
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    await message.answer(
        f"👥 <b>Do'stlarni Taklif Qilish</b>\n\n"
        f"Sizning shaxsiy taklif havolangiz:\n"
        f"🔗 <code>{referral_link}</code>\n\n"
        f"Do'stingiz shu havola orqali kirib, Premium xarid qilsa, sizga <b>1000 so'm</b> bonus beriladi!\n\n"
        f"👥 <b>Пригласить Друзей</b>\n\n"
        f"Ваша личная реферальная ссылка:\n"
        f"🔗 <code>{referral_link}</code>\n\n"
        f"Если друг перейдет по ссылке и купит Premium, вы получите <b>1000 сум</b> бонуса!",
        parse_mode="HTML"
    )

@router.message(F.text.in_({"✨ 24/7 Monitoring", "✨ 24/7 Мониторинг"}))
async def nav_monitoring(message: types.Message):
    user_id = message.from_user.id
    stats = await get_user_pricing_info(user_id)

    if stats and stats['test_used'] and stats['is_premium']:
        # User is on Test Plan -> Restrict Access
        balance = stats['balance']
        test_used = str(stats['test_used']).lower()
        is_tg_premium = str(message.from_user.is_premium or False).lower()
        
        base_url = PLANS_WEBAPP_URL if PLANS_WEBAPP_URL else f"{WEBAPP_URL}/plans.html"
        url = f"{base_url}?lang={message.from_user.language_code}&balance={balance}&test_used={test_used}&tg_premium={is_tg_premium}"
        
        # Use ReplyKeyboardMarkup
        keyboard = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="💎 Upgrade Plan / Tarifni Kuchaytirish", web_app=WebAppInfo(url=url))],
            [KeyboardButton(text="⬅️ Ortga")]
        ], resize_keyboard=True)
        
        await message.answer(
            "🚫 <b>Ruxsat cheklangan</b>\n\n"
            "24/7 Monitoring funksiyasi <b>Test Tarifida</b> ishlamaydi.\n"
            "To'liq himoya uchun <b>Standart</b> yoki <b>Premium</b> tarifni tanlang.\n\n"
            "🚫 <b>Доступ ограничен</b>\n"
            "Функция 24/7 Мониторинга не работает в <b>Тестовом Тарифе</b>.\n"
            "Выберите <b>Стандарт</b> или <b>Премиум</b> для полной защиты.\n\n"
            "⬇️ <b>Pastdagi tugmani bosing:</b>",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        return

    await message.answer("✅ 24/7 Monitoring is active for your Premium account.")

@router.message(F.text.in_({"⬅️ Ortga", "⬅️ Назад", "⬅️ Back"}))
async def nav_back(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    lang = user_data.get("language", "en")
    is_premium = message.from_user.is_premium or False
    
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
    if not url.startswith("http"):
        await message.reply("⚠️ Noto'g'ri URL. http:// yoki https:// bilan boshlang.")
        return

    try:
        await message.delete()
    except:
        pass

    status_msg = await message.answer(f"🔍 Tekshirilmoqda: {url} ...")
    result = await scan_url_virustotal(url)
    
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="HTML")

@router.message(SecurityStates.waiting_for_file, F.document)
async def process_file_check(message: types.Message, state: FSMContext):
    document = message.document
    
    if document.file_size > 20 * 1024 * 1024:
        await message.reply("⚠️ Fayl juda katta. Maksimum 20MB.")
        return

    try:
        await message.delete()
    except:
        pass

    status_msg = await message.answer(f"⬇️ Fayl yuklanmoqda: {document.file_name}...")
    
    file_id = document.file_id
    file = await message.bot.get_file(file_id)
    file_path = file.file_path
    
    local_path = f"downloads/{document.file_name}"
    os.makedirs("downloads", exist_ok=True)
    await message.bot.download_file(file_path, local_path)
    
    await status_msg.edit_text(f"🔍 Tahlil qilinmoqda: {document.file_name}...")
    result = await scan_file_virustotal(local_path)
    
    try:
        os.remove(local_path)
    except:
        pass
        
    user_db = await get_user(message.from_user.id)
    lang = user_db['language'] if user_db else 'uz'

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="HTML")


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
        status_msg = await message.reply("🛡 24/7 Monitoring: Tekshirilmoqda...")
        result = await scan_url_virustotal(message.text)
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="HTML")
    
    elif message.document:
        if message.document.file_size > 20 * 1024 * 1024:
            return
        status_msg = await message.reply("🛡 24/7 Monitoring: Fayl tekshirilmoqda...")
        file = await message.bot.get_file(message.document.file_id)
        local_path = f"downloads/{message.document.file_name}"
        os.makedirs("downloads", exist_ok=True)
        await message.bot.download_file(file.file_path, local_path)
        result = await scan_file_virustotal(local_path)
        try: os.remove(local_path)
        except: pass
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="HTML")


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

    # Process URLs
    if message.text:
        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message.text)
        for url in urls:
            result = await scan_url_virustotal(url)
            if "error" in result:
                await message.bot.send_message(owner_chat_id, f"⚠️ {result['error']} ({url})")
            else:
                user_db = await get_user(owner_chat_id)
                lang = user_db['language'] if user_db else 'uz'
                text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                await message.bot.send_message(owner_chat_id, text, parse_mode="HTML")

    # Process Document
    if message.document:
        doc = message.document
        if doc.file_size > 20 * 1024 * 1024:
            await message.bot.send_message(owner_chat_id, f"⚠️ Fayl juda katta: {doc.file_name}")
        else:
            try:
                status_msg = await message.bot.send_message(owner_chat_id, f"⏳ Tekshirilmoqda: {doc.file_name}...")
                file_info = await message.bot.get_file(doc.file_id)
                local_path = f"downloads/biz_{doc.file_name}"
                os.makedirs("downloads", exist_ok=True)
                await message.bot.download_file(file_info.file_path, local_path)
                
                result = await scan_file_virustotal(local_path)
                try: os.remove(local_path)
                except: pass
                
                if "error" in result:
                    await status_msg.edit_text(f"❌ {result['error']}")
                else:
                    user_db = await get_user(owner_chat_id)
                    lang = user_db['language'] if user_db else 'uz'
                    text = format_scan_report(result["stats"], result["link"], lang, AD_PLACEHOLDER_TEXT)
                    await status_msg.edit_text(text, parse_mode="HTML")
            except Exception as e:
                await message.bot.send_message(owner_chat_id, f"❌ Xatolik: {e}")
