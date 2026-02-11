from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import aiohttp
import os
from config import VT_API_KEY, AD_PLACEHOLDER_TEXT
from keyboards import get_main_menu_keyboard, get_back_keyboard
import asyncio

router = Router()

class SecurityStates(StatesGroup):
    waiting_for_link = State()
    waiting_for_file = State()

def format_scan_report(stats: dict, link: str, ad_text: str) -> str:
    return (
        f"🔍 **Tahlil Natijalari (VirusTotal)**\n\n"
        f"✅ Xavfsiz: {stats.get('harmless', 0)}\n"
        f"⚠️ Shubheli: {stats.get('suspicious', 0)}\n"
        f"❌ Zararli: {stats.get('malicious', 0)}\n"
        f"❓ Aniqlanmagan: {stats.get('undetected', 0)}\n\n"
        f"🔗 Batafsil: {link}\n\n"
        f"⚠️ *Eslatma: Ushbu ma'lumot faqat tanishish uchun. Yakuniy xulosa foydalanuvchi zimmasida.*\n\n"
        f"📢 {ad_text}"
    )

async def get_analysis_result(session, analysis_id):
    """Polls VirusTotal for analysis completion."""
    url = f"https://www.virustotal.com/api/v3/analyses/{analysis_id}"
    headers = {"x-apikey": VT_API_KEY}
    
    for _ in range(5):  # Poll up to 5 times
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            attributes = data['data']['attributes']
            if attributes['status'] == 'completed':
                return attributes
        await asyncio.sleep(2)
    return None

async def scan_url_virustotal(url: str):
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        return {"error": "VirusTotal API Key missing."}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        try:
            # Step 1: Submit URL
            async with session.post("https://www.virustotal.com/api/v3/urls", data={"url": url}, headers=headers) as resp:
                if resp.status != 200:
                    return {"error": f"Error submitting URL: {resp.status}"}
                data = await resp.json()
                analysis_id = data['data']['id']
            
            # Step 2: Poll for results
            result = await get_analysis_result(session, analysis_id)
            link = f"https://www.virustotal.com/gui/url/{analysis_id.split('-')[1]}/detection"
            
            if result:
                return {"stats": result['stats'], "link": link}
            else:
                # Return partial info if timed out
                return {"stats": {"harmless": "?", "suspicious": "?", "malicious": "?", "undetected": "?"}, "link": link}
                
        except Exception as e:
            return {"error": f"Error scanning URL: {e}"}

async def scan_file_virustotal(file_path: str):
    if not VT_API_KEY or "YOUR_" in VT_API_KEY:
        return {"error": "VirusTotal API Key missing."}
        
    async with aiohttp.ClientSession() as session:
        headers = {"x-apikey": VT_API_KEY}
        try:
            # Step 1: Upload File
            data = aiohttp.FormData()
            data.add_field('file', open(file_path, 'rb'), filename=os.path.basename(file_path))
            
            async with session.post("https://www.virustotal.com/api/v3/files", data=data, headers=headers) as resp:
                if resp.status != 200:
                    return {"error": f"Error uploading file: {resp.status}"}
                resp_data = await resp.json()
                analysis_id = resp_data['data']['id']
            
            # Step 2: Poll for results
            result = await get_analysis_result(session, analysis_id)
            # File link construction might differ, but using analysis ID usually redirects
            link = f"https://www.virustotal.com/gui/file-analysis/{analysis_id}/detection"
            
            if result:
                return {"stats": result['stats'], "link": link}
            else:
                return {"stats": {"harmless": "?", "suspicious": "?", "malicious": "?", "undetected": "?"}, "link": link}
        except Exception as e:
            return {"error": f"Error scanning file: {e}"}

# --- Navigation Handlers ---

@router.message(F.text.in_({"🔗 Havolani tekshirish", "🔗 Проверка ссылки", "🔗 Link Check"}))
async def nav_link_check(message: types.Message, state: FSMContext):
    # Determine language from button text
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
    # Just a placeholder message for now
    await message.answer("ℹ️ GVARD Mobile Protection App is coming soon! / Tez kunda! / Скоро!")

@router.message(F.text.in_({"✨ 24/7 Monitoring", "✨ 24/7 Мониторинг"}))
async def nav_monitoring(message: types.Message):
    await message.answer("✅ 24/7 Monitoring is active for your Premium account.")

@router.message(F.text.in_({"⬅️ Ortga", "⬅️ Назад", "⬅️ Back"}))
async def nav_back(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    lang = user_data.get("language", "en")
    
    # Check premium again for correct menu
    is_premium = message.from_user.is_premium or False
    
    responses = {
        "uz": "Bosh menyu:",
        "ru": "Главное меню:",
        "en": "Main Menu:"
    }
    
    await message.answer(responses.get(lang, "en"), reply_markup=get_main_menu_keyboard(lang, is_premium))
    await state.clear()


# --- Functionality Handlers ---

@router.message(SecurityStates.waiting_for_link, F.text)
async def process_link_check(message: types.Message, state: FSMContext):
    url = message.text
    # Basic validation
    if not url.startswith("http"):
        await message.reply("⚠️ Invalid URL. Please start with http:// or https://")
        return

    # Cleanup user message
    try:
        await message.delete()
    except:
        pass

    status_msg = await message.answer(f"🔍 Scanning URL: {url} ...")
    result = await scan_url_virustotal(url)
    
    if "error" in result:
        await status_msg.edit_text(result["error"])
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")

@router.message(SecurityStates.waiting_for_file, F.document)
async def process_file_check(message: types.Message, state: FSMContext):
    document = message.document
    
    # Check file size (limit to 20MB for bot safety)
    if document.file_size > 20 * 1024 * 1024:
        await message.reply("⚠️ File is too large. Max size is 20MB.")
        return

    # Cleanup user message
    try:
        await message.delete()
    except:
        pass

    status_msg = await message.answer("⬇️ Downloading file...")
    
    # Download file
    file_id = document.file_id
    file = await message.bot.get_file(file_id)
    file_path = file.file_path
    
    local_path = f"downloads/{document.file_name}"
    os.makedirs("downloads", exist_ok=True)
    
    await message.bot.download_file(file_path, local_path)
    
    await status_msg.edit_text("🔍 Tahlil qilinmoqda (VirusTotal)...")
    result = await scan_file_virustotal(local_path)
    
    # Cleanup local file
    try:
        os.remove(local_path)
    except:
        pass
        
    if "error" in result:
        await status_msg.edit_text(result["error"])
    else:
        text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
        await status_msg.edit_text(text, parse_mode="Markdown")



# --- 24/7 Monitoring Handler (Private) ---
@router.message(F.text.startswith("http") | F.document)
async def monitor_messages(message: types.Message):
    """
    Background listener for Premium users (Private Chat). 
    """
    user = message.from_user
    is_premium = user.is_premium or False
    
    if is_premium:
        #Reuse existing logic or call business logic if refined
        # For now keeping as is but ensuring no conflict with business handler
        if message.text and message.text.startswith("http"):
            status_msg = await message.reply("🛡 24/7 Monitoring: Tekshirilmoqda...")
            result = await scan_url_virustotal(message.text)
            if "error" in result:
                 await status_msg.edit_text(f"❌ Xatolik: {result['error']}")
            else:
                 text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                 await status_msg.edit_text(text, parse_mode="Markdown")
        elif message.document:
             # Same as before...
            if message.document.file_size > 20 * 1024 * 1024: return
            status_msg = await message.reply("🛡 24/7 Monitoring: Fayl tekshirilmoqda...")
            file_id = message.document.file_id
            file = await message.bot.get_file(file_id)
            local_path = f"downloads/{message.document.file_name}"
            os.makedirs("downloads", exist_ok=True)
            await message.bot.download_file(file.file_path, local_path)
            result = await scan_file_virustotal(local_path)
            try: os.remove(local_path) 
            except: pass
            if "error" in result: await status_msg.edit_text(result["error"])
            else:
                 text = format_scan_report(result["stats"], result["link"], AD_PLACEHOLDER_TEXT)
                 await status_msg.edit_text(text, parse_mode="Markdown")

# --- 24/7 Monitoring Handler (Business) ---
from utils.formatter import format_scan_report
import re

# ... (Previous imports and functions) ...

# Ensure imports are correct for types, Router, etc. if not already there, 
# but we are replacing the end of the file. 

# --- 24/7 Monitoring Handler (Business) ---
@router.business_message(F.text | F.document)
async def business_monitoring(message: types.Message):
    """
    Monitors all incoming messages from Telegram Business connection.
    Bypasses FSM, scans ALL links/files, sends result to owner's private chat.
    """
    # 1. Get Business Owner ID immediately
    try:
        data = await message.bot.get_business_connection(message.business_connection_id)
        owner_chat_id = data.user_chat_id
    except Exception as e:
        print(f"Error getting business connection: {e}")
        return

    # 2. Extract and Process Targets
    
    # Process URLs
    if message.text:
        # Regex for http/https URLs
        urls = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', message.text)
        for url in urls:
             result = await scan_url_virustotal(url)
             if result:
                 # Format and send
                 # Determine link for report: result['link'] is VT link, url is scanned link
                 # Formatter takes result stats and VT link. 
                 vt_link = result.get('link', '#')
                 if "error" in result:
                     text = f"⚠️ Xatolik: {result['error']} ({url})"
                     await message.bot.send_message(owner_chat_id, text)
                 else:
                     text = format_scan_report(result.get("stats", {}), vt_link, AD_PLACEHOLDER_TEXT)
                     # Prepend scanned object name/url to be clear? 
                     # The formatter has "Natija" and "Link". 
                     # Let's rely on standard formatter.
                     await message.bot.send_message(owner_chat_id, text, parse_mode="Markdown")

    # Process Document
    if message.document:
        doc = message.document
        if doc.file_size > 20 * 1024 * 1024:
             await message.bot.send_message(owner_chat_id, f"⚠️ Fayl juda katta: {doc.file_name}")
        else:
             try:
                 status_msg = await message.bot.send_message(owner_chat_id, f"⏳ Fayl tekshirilmoqda: {doc.file_name}...")
                 file_info = await message.bot.get_file(doc.file_id)
                 local_path = f"downloads/biz_{doc.file_name}"
                 os.makedirs("downloads", exist_ok=True)
                 await message.bot.download_file(file_info.file_path, local_path)
                 
                 result = await scan_file_virustotal(local_path)
                 try: os.remove(local_path)
                 except: pass
                 
                 if "error" in result:
                     await status_msg.edit_text(f"❌ Xatolik: {result['error']}")
                 else:
                     text = format_scan_report(result.get("stats", {}), result.get('link', '#'), AD_PLACEHOLDER_TEXT)
                     await status_msg.edit_text(text, parse_mode="Markdown")
             except Exception as e:
                 await message.bot.send_message(owner_chat_id, f"❌ Ichki xatolik: {e}")
