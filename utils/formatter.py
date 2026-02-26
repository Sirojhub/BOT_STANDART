import re
from config import AD_PLACEHOLDER_TEXT

def normalize_url(text: str) -> str | None:
    """
    Normalizes a given string into a valid URL for VirusTotal scanning.
    - Handles Telegram @usernames
    - Prepends http:// to raw domains/IPs
    - Returns None if it's completely invalid text
    """
    text = text.strip()
    
    # Handle Telegram username
    if text.startswith('@'):
        return f"https://t.me/{text[1:]}"
        
    # Valid existing links
    if re.match(r'^https?://', text, re.IGNORECASE):
        return text
        
    # Raw domains (e.g. google.com) or IP addresses (e.g. 192.168.1.1)
    if re.search(r'\.[a-z]{2,}|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', text, re.IGNORECASE):
        # We assume http for VT to scan it if no protocol was provided
        return f"http://{text}"
        
    return None

def format_scan_report(stats: dict, link: str, language: str = 'uz', ad_text: str = AD_PLACEHOLDER_TEXT) -> str:
    """
    Formats the VirusTotal scan results into a professional multi-language template.
    """
    harmless = int(stats.get('harmless', 0))
    malicious = int(stats.get('malicious', 0))
    suspicious = int(stats.get('suspicious', 0))
    undetected = int(stats.get('undetected', 0))
    
    # Status Icons/Titles (Refined by Cyber-Security Law Expert)
    status_map = {
        "uz": {
            "mal": "🚨 XAVF ANIQLANDI", 
            "susp": "⚠️ SHUBHALI OB'EKT", 
            "safe": "✅ INTEGRITY TASDIQLANDI (Toza)", 
            "title": "🛡 Tizim Integrity Hisoboti", 
            "file": "📎 Tahlil ob'ekti", 
            "res": "📊 Audit xulosasi", 
            "h": "🟢 Xavfsiz", 
            "m": "🔴 Zararli", 
            "s": "🟠 Shubheli", 
            "u": "⚪️ Noma'lum", 
            "det": "🔗 To'liq texnik hisobot", 
            "dis": "⚖️ Huquqiy eslatma: Ushbu tahlil global xavfsizlik protokollari asosida shakllantirilgan bo'lib, axborot daxlsizligini ta'minlash va operatsion xavfni minimallashtirish uchun xizmat qiladi."
        },
        "ru": {
            "mal": "🚨 ОБНАРУЖЕНА УГРОЗА", 
            "susp": "⚠️ ПОДОЗРИТЕЛЬНЫЙ ОБЪЕКТ", 
            "safe": "✅ ЦЕЛОСТНОСТЬ ПОДТВЕРЖДЕНА (Чисто)", 
            "title": "🛡 Отчет о целостности системы", 
            "file": "📎 Объект анализа", 
            "res": "📊 Аудит-заключение", 
            "h": "🟢 Безопасно", 
            "m": "🔴 Вредоносно", 
            "s": "🟠 Подозрительно", 
            "u": "⚪️ Не определено", 
            "det": "🔗 Полный технический отчет", 
            "dis": "⚖️ Юридическое уведомление: Данный экспертный анализ сформирован на основе глобальных протоколов безопасности и служит для обеспечения конфиденциальности и минимизации технологических рисков."
        },
        "en": {
            "mal": "🚨 THREAT DETECTED", 
            "susp": "⚠️ SUSPICIOUS OBJECT", 
            "safe": "✅ INTEGRITY VERIFIED (Clean)", 
            "title": "🛡 System Integrity Report", 
            "file": "📎 Analysis Object", 
            "res": "📊 Audit Conclusion", 
            "h": "🟢 Safe", 
            "m": "🔴 Malicious", 
            "s": "🟠 Suspicious", 
            "u": "⚪️ Undetected", 
            "det": "🔗 Full technical report", 
            "dis": "⚖️ Legal Notice: This expert analysis is generated based on global security protocols and serves to ensure data integrity and mitigate technical operational risks."
        }
    }
    
    t = status_map.get(language, status_map["en"])
    
    # Determine Status based on Thresholds
    if malicious >= 3:
        status_header = t["mal"]
    elif malicious >= 1 or suspicious >= 2:
        status_header = t["susp"]
    else:
        status_header = t["safe"]

    return (
        f"<b>{t['title']}</b>\n\n"
        f"<b>{t['file']}:</b> <a href='{link}'>Link</a>\n"
        f"<b>{t['res']}:</b> {status_header}\n\n"
        f"{t['h']}: <b>{harmless}</b>\n"
        f"{t['m']}: <b>{malicious}</b>\n"
        f"{t['s']}: <b>{suspicious}</b>\n"
        f"{t['u']}: <b>{undetected}</b>\n\n"
        f"<a href='{link}'>{t['det']}</a>\n\n"
        f"<i>{t['dis']}</i>\n\n"
        f"{ad_text}"
    )
