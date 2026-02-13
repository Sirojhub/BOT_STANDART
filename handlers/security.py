from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp
import hashlib
import os
import time
from config import VT_API_KEY, AD_PLACEHOLDER_TEXT
from keyboards import get_main_menu_keyboard, get_back_keyboard
from utils.formatter import format_scan_report
from database import get_cached_scan, save_scan_cache
import asyncio
import re
import logging

router = Router()
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────
VT_SCAN_TIMEOUT = 25  # seconds before going async
MAX_FILE_SIZE = 32 * 1024 * 1024  # 32MB (VT API max)

class SecurityStates(StatesGroup):
    waiting_for_link = State()
    waiting_for_file = State()


# ── Hash Utility ──────────────────────────────────────────────────────────

def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


# ── VirusTotal Core Functions ─────────────────────────────────────────────

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
                elif status in ('queued', 'in-progress'):
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(interval)
        except Exception as e:
            logger.error(f"VT poll error: {e}")
            await asyncio.sleep(interval)
    
    return None


async def check_file_hash_vt(session, file_hash: str):
    """Check if file hash already exists in VT database (instant result!)."""
    url = f"https://www.virustotal.com/api/v3/files/{file_hash}"
    headers = {"x-apikey": VT_API_KEY}
    
    try:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                stats = data['data']['attributes']['last_analysis_stats']
                link = f"https://www.virustotal.com/gui/file/{file_hash}/detection"
                logger.info(f"File found in VT by hash: {file_hash[:16]}...")
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
            
            # Step 2: Poll for results
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


async def scan_file_virustotal(file_path: str, file_hash: str = None):
    """
    Scan file via VirusTotal.
    Checks: 1) Local DB cache → 2) VT hash lookup → 3) Upload for new scan.
    """
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        return {"error": "VirusTotal API Key o'rnatilmagan."}
    
    # Compute hash if not provided
    if not file_hash:
        file_hash = compute_file_hash(file_path)
    
    # ═══ STEP 1: Check LOCAL DB cache (instant!) ═══
    cached = await get_cached_scan(file_hash)
    if cached:
        logger.info(f"⚡ Cache hit for {file_hash[:16]}...")
        return cached
    
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        
        # ═══ STEP 2: Check VT hash (fast!) ═══
        hash_result = await check_file_hash_vt(session, file_hash)
        if hash_result:
            # Save to local cache for next time
            await save_scan_cache(file_hash, hash_result["stats"], hash_result["link"])
            return hash_result
        
        # ═══ STEP 3: Upload file for new analysis (slow) ═══
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
                    # File already exists in VT
                    logger.info("VT 409: File already exists, fetching by hash")
                    async with session.get(
                        f"https://www.virustotal.com/api/v3/files/{file_hash}", 
                        headers=headers
                    ) as hash_resp:
                        if hash_resp.status == 200:
                            hash_data = await hash_resp.json()
                            stats = hash_data['data']['attributes']['last_analysis_stats']
                            link = f"https://www.virustotal.com/gui/file/{file_hash}/detection"
                            await save_scan_cache(file_hash, stats, link)
                            return {"stats": stats, "link": link}
                    return {"error": "Fayl VT bazasida bor, lekin natijani olishda xatolik."}
                
                elif resp.status != 200:
                    return {"error": f"Fayl yuklashda xatolik: {resp.status}"}
                
                analysis_id = resp_data['data']['id']
            
            # Poll for results
            result = await get_analysis_result(session, analysis_id, max_attempts=15, interval=3)
            link = f"https://www.virustotal.com/gui/file/{file_hash}/detection"
            
            if result:
                # Cache the result
                await save_scan_cache(file_hash, result['stats'], link)
                return {"stats": result['stats'], "link": link}
            else:
                return {"error": "timeout", "analysis_id": analysis_id, "file_hash": file_hash}
        except Exception as e:
            return {"error": f"Fayl tekshirishda xatolik: {e}"}


# ── Background Scan Helper ────────────────────────────────────────────────

async def background_scan_and_notify(bot, chat_id: int, status_msg_id: int, 
                                      scan_func, *args, ad_text: str = None):
    """
    Run a scan in background and edit the status message when done.
    Used when the initial scan times out after VT_SCAN_TIMEOUT seconds.
    """
    try:
        result = await scan_func(*args)
        
        if "error" in result and result["error"] != "timeout":
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=f"❌ {result['error']}"
            )
        elif "stats" in result:
            text = format_scan_report(
                result["stats"], result["link"], 
                ad_text or AD_PLACEHOLDER_TEXT
            )
            cache_note = "\n⚡ _Natija keshdan olindi_" if result.get("cached") else ""
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=text + cache_note, parse_mode="Markdown"
            )
        else:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text="❌ Tahlil yakunlanmadi. Keyinroq urinib ko'ring."
            )
    except Exception as e:
        logger.error(f"Background scan error: {e}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=f"❌ Xatolik: {e}"
            )
        except:
            pass


async def scan_with_timeout(bot, chat_id: int, status_msg, scan_func, *args):
    """
    Run scan with VT_SCAN_TIMEOUT. If it completes in time, return result.
    If timeout, launch background task and inform user.
    """
    try:
        result = await asyncio.wait_for(scan_func(*args), timeout=VT_SCAN_TIMEOUT)
        
        # Check if scan itself returned a timeout (polling exhausted)
        if isinstance(result, dict) and result.get("error") == "timeout":
            await status_msg.edit_text(
                "⏳ Navbat juda band, tahlil fonda davom etmoqda...\n"
                "Natija tayyor bo'lishi bilan xabar beramiz!"
            )
            # Re-run with longer timeout in background
            asyncio.create_task(
                background_scan_and_notify(
                    bot, chat_id, status_msg.message_id,
                    scan_func, *args
                )
            )
            return None
        
        return result
        
    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "⏳ Navbat juda band, tahlil fonda davom etmoqda...\n"
            "Natija tayyor bo'lishi bilan xabar beramiz!"
        )
        # Launch background task
        asyncio.create_task(
            background_scan_and_notify(
                bot, chat_id, status_msg.message_id,
                scan_func, *args
            )
        )
        return None


# ── Navigation Handlers ──────────────────────────────────────────────────

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
        "uz": "Tekshirish uchun har qanday faylni yuboring (max 32MB):\n📎 PDF, EXE, DOCX, APK, ZIP, JS, TXT va boshqalar",
        "ru": "Отправьте любой файл для проверки (макс 32МБ):\n📎 PDF, EXE, DOCX, APK, ZIP, JS, TXT и другие",
        "en": "Send any file to check (max 32MB):\n📎 PDF, EXE, DOCX, APK, ZIP, JS, TXT and more"
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


# ── Scan Handlers ─────────────────────────────────────────────────────────

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
    
    result = await scan_with_timeout(
        message.bot, message.chat.id, status_msg,
        scan_url_virustotal, url
    )
    
    if result is None:
        return  # Background task will handle it
    
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")


@router.message(SecurityStates.waiting_for_file, F.document)
async def process_file_check(message: types.Message, state: FSMContext):
    """Handle document files — ALL types: PDF, EXE, DOCX, APK, ZIP, JS, TXT, etc."""
    document = message.document
    
    if document.file_size > MAX_FILE_SIZE:
        await message.reply("⚠️ Fayl juda katta. Maksimum 32MB.")
        return

    try:
        await message.delete()
    except:
        pass

    file_name = document.file_name or f"file_{int(time.time())}.bin"
    status_msg = await message.answer(f"⬇️ Fayl yuklanmoqda: {file_name}...")
    
    file = await message.bot.get_file(document.file_id)
    local_path = f"downloads/{file_name}"
    os.makedirs("downloads", exist_ok=True)
    await message.bot.download_file(file.file_path, local_path)
    
    # Compute hash for caching
    file_hash = compute_file_hash(local_path)
    
    # Check cache first (instant!)
    cached = await get_cached_scan(file_hash)
    if cached:
        try: os.remove(local_path)
        except: pass
        text = format_scan_report(cached["stats"], cached["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(
            f"⚡ **Natija keshdan olindi** (tezkor!)\n\n{text}", 
            parse_mode="Markdown"
        )
        return
    
    await status_msg.edit_text(f"🔍 Tahlil qilinmoqda: {file_name}...")
    
    result = await scan_with_timeout(
        message.bot, message.chat.id, status_msg,
        scan_file_virustotal, local_path, file_hash
    )
    
    try: os.remove(local_path)
    except: pass
        
    if result is None:
        return  # Background task will handle it
    
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")


@router.message(SecurityStates.waiting_for_file, F.photo)
async def process_photo_check(message: types.Message, state: FSMContext):
    """Handle photos sent for scanning (converted to file)."""
    photo = message.photo[-1]  # Highest resolution
    
    try:
        await message.delete()
    except:
        pass

    file_name = f"photo_{int(time.time())}.jpg"
    status_msg = await message.answer(f"⬇️ Rasm yuklanmoqda: {file_name}...")
    
    file = await message.bot.get_file(photo.file_id)
    local_path = f"downloads/{file_name}"
    os.makedirs("downloads", exist_ok=True)
    await message.bot.download_file(file.file_path, local_path)
    
    file_hash = compute_file_hash(local_path)
    
    cached = await get_cached_scan(file_hash)
    if cached:
        try: os.remove(local_path)
        except: pass
        text = format_scan_report(cached["stats"], cached["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(f"⚡ **Natija keshdan olindi**\n\n{text}", parse_mode="Markdown")
        return
    
    await status_msg.edit_text(f"🔍 Tahlil qilinmoqda: {file_name}...")
    
    result = await scan_with_timeout(
        message.bot, message.chat.id, status_msg,
        scan_file_virustotal, local_path, file_hash
    )
    
    try: os.remove(local_path)
    except: pass
    
    if result is None:
        return
    
    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")


# ── 24/7 Monitoring (Private Chat) ───────────────────────────────────────

@router.message(F.text.startswith("http") | F.document | F.photo)
async def monitor_messages(message: types.Message):
    """Background listener for Premium users — scans links, ALL file types, and photos."""
    user = message.from_user
    is_premium = user.is_premium or False
    
    if not is_premium:
        return
    
    # URL Monitoring
    if message.text and message.text.startswith("http"):
        status_msg = await message.reply("🛡 24/7 Monitoring: Tekshirilmoqda...")
        result = await scan_with_timeout(
            message.bot, message.chat.id, status_msg,
            scan_url_virustotal, message.text
        )
        if result is None:
            return
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="Markdown")
    
    # Document Monitoring (ALL file types)
    elif message.document:
        if message.document.file_size > MAX_FILE_SIZE:
            return
        status_msg = await message.reply("🛡 24/7 Monitoring: Fayl tekshirilmoqda...")
        file = await message.bot.get_file(message.document.file_id)
        file_name = message.document.file_name or f"mon_{int(time.time())}.bin"
        local_path = f"downloads/{file_name}"
        os.makedirs("downloads", exist_ok=True)
        await message.bot.download_file(file.file_path, local_path)
        
        file_hash = compute_file_hash(local_path)
        
        result = await scan_with_timeout(
            message.bot, message.chat.id, status_msg,
            scan_file_virustotal, local_path, file_hash
        )
        try: os.remove(local_path)
        except: pass
        
        if result is None:
            return
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="Markdown")
    
    # Photo Monitoring
    elif message.photo:
        status_msg = await message.reply("🛡 24/7 Monitoring: Rasm tekshirilmoqda...")
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        file_name = f"mon_photo_{int(time.time())}.jpg"
        local_path = f"downloads/{file_name}"
        os.makedirs("downloads", exist_ok=True)
        await message.bot.download_file(file.file_path, local_path)
        
        file_hash = compute_file_hash(local_path)
        
        result = await scan_with_timeout(
            message.bot, message.chat.id, status_msg,
            scan_file_virustotal, local_path, file_hash
        )
        try: os.remove(local_path)
        except: pass
        
        if result is None:
            return
        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
            await status_msg.edit_text(text, parse_mode="Markdown")


# ── 24/7 Monitoring (Business Connection) ────────────────────────────────

@router.business_message(F.text | F.document | F.photo)
async def business_monitoring(message: types.Message):
    """Monitors messages from Telegram Business connection — ALL file types."""
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

    # Process Document (ALL file types)
    if message.document:
        doc = message.document
        if doc.file_size > MAX_FILE_SIZE:
            await message.bot.send_message(owner_chat_id, f"⚠️ Fayl juda katta: {doc.file_name}")
        else:
            try:
                status_msg = await message.bot.send_message(owner_chat_id, f"⏳ Tekshirilmoqda: {doc.file_name}...")
                file_info = await message.bot.get_file(doc.file_id)
                file_name = doc.file_name or f"biz_{int(time.time())}.bin"
                local_path = f"downloads/biz_{file_name}"
                os.makedirs("downloads", exist_ok=True)
                await message.bot.download_file(file_info.file_path, local_path)
                
                file_hash = compute_file_hash(local_path)
                result = await scan_file_virustotal(local_path, file_hash)
                try: os.remove(local_path)
                except: pass
                
                if "error" in result:
                    await status_msg.edit_text(f"❌ {result['error']}")
                else:
                    text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                    await status_msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await message.bot.send_message(owner_chat_id, f"❌ Xatolik: {e}")

    # Process Photos
    if message.photo:
        try:
            photo = message.photo[-1]
            status_msg = await message.bot.send_message(owner_chat_id, "⏳ Rasm tekshirilmoqda...")
            file_info = await message.bot.get_file(photo.file_id)
            file_name = f"biz_photo_{int(time.time())}.jpg"
            local_path = f"downloads/{file_name}"
            os.makedirs("downloads", exist_ok=True)
            await message.bot.download_file(file_info.file_path, local_path)
            
            file_hash = compute_file_hash(local_path)
            result = await scan_file_virustotal(local_path, file_hash)
            try: os.remove(local_path)
            except: pass
            
            if "error" in result:
                await status_msg.edit_text(f"❌ {result['error']}")
            else:
                text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await message.bot.send_message(owner_chat_id, f"❌ Xatolik: {e}")
