from config import AD_PLACEHOLDER_TEXT

def format_scan_report(stats: dict, link: str, language: str = 'uz', ad_text: str = AD_PLACEHOLDER_TEXT) -> str:
    """
    Formats the VirusTotal scan results into a professional multi-language template.
    """
    harmless = int(stats.get('harmless', 0))
    malicious = int(stats.get('malicious', 0))
    suspicious = int(stats.get('suspicious', 0))
    undetected = int(stats.get('undetected', 0))
    
    # Status Icons/Titles
    status_map = {
        "uz": {"mal": "🚨 XAVFLI", "susp": "⚠️ SHUBHALI", "safe": "✅ XAVFSIZ", "title": "🔒 Xavfsizlik tekshiruvi natijasi", "file": "📎 Fayl/Havola", "res": "📊 Natija", "h": "🟢 Xavfsiz", "m": "🔴 Zararli", "s": "🟠 Shubheli", "u": "⚪️ Aniqlanmagan", "det": "🔗 Batafsil hisobot", "dis": "⚖️ Mas'uliyatni rad etish: Natijalar 100% kafolat bermaydi."},
        "ru": {"mal": "🚨 ОПАСНО", "susp": "⚠️ ПОДОЗРИТЕЛЬНО", "safe": "✅ БЕЗОПАСНО", "title": "🔒 Результат проверки безопасности", "file": "📎 Файл/Ссылка", "res": "📊 Результат", "h": "🟢 Безопасно", "m": "🔴 Вредоносно", "s": "🟠 Подозрительно", "u": "⚪️ Не определено", "det": "🔗 Детальный отчет", "dis": "⚖️ Отказ от ответственности: Результаты не гарантируют 100% точность."},
        "en": {"mal": "🚨 DANGEROUS", "susp": "⚠️ SUSPICIOUS", "safe": "✅ SAFE", "title": "🔒 Security Scan Result", "file": "📎 File/Link", "res": "📊 Result", "h": "🟢 Safe", "m": "🔴 Malicious", "s": "🟠 Suspicious", "u": "⚪️ Undetected", "det": "🔗 Detailed report", "dis": "⚖️ Disclaimer: Results are based on VT and do not guarantee 100% safety."}
    }
    
    t = status_map.get(language, status_map["en"])
    
    # Determine Status
    if malicious > 0: status_header = t["mal"]
    elif suspicious > 0: status_header = t["susp"]
    else: status_header = t["safe"]

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
