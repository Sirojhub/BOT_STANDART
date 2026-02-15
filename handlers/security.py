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
    await message.answer("ℹ️ GVARD Mobile Protection App is coming soon! / Tez kunda! / Скоро!")

@router.message(F.text.in_({"✨ 24/7 Monitoring", "✨ 24/7 Мониторинг"}))
async def nav_monitoring(message: types.Message):
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
    
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")

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
        
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")


# ── 24/7 Monitoring (Private Chat) ───────────────────────────────────

@router.message(F.text.startswith("http") | F.document)
async def monitor_messages(message: types.Message):
    """Background listener for Premium users."""
    # ── Group File Limit (20MB) ──
    if message.chat.type != ChatType.PRIVATE:
        if message.document and message.document.file_size > 20 * 1024 * 1024:
            await message.reply("⚠️ Fayl hajmi 20MB dan oshmasligi kerak (Guruh cheklovi).")
            return

    user = message.from_user
    is_premium = user.is_premium or False
    
    if not is_premium:
        return
    
    if message.text and message.text.startswith("http"):
        status_msg = await message.reply("🛡 24/7 Monitoring: Tekshirilmoqda...")
        result = await scan_url_virustotal(message.text)
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="Markdown")
    
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
            text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="Markdown")


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
                text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                await message.bot.send_message(owner_chat_id, text, parse_mode="Markdown")

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
                    text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                    await status_msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await message.bot.send_message(owner_chat_id, f"❌ Xatolik: {e}")
