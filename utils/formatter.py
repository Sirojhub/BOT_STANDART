from config import AD_PLACEHOLDER_TEXT

def format_scan_report(stats: dict, link: str, ad_text: str = AD_PLACEHOLDER_TEXT) -> str:
    """
    Formats the VirusTotal scan results into a professional Uzbek template.
    """
    harmless = int(stats.get('harmless', 0))
    malicious = int(stats.get('malicious', 0))
    suspicious = int(stats.get('suspicious', 0))
    undetected = int(stats.get('undetected', 0))
    
    # Determine Status
    if malicious > 0:
        status_header = "🚨 XAVFLI (Malicious)"
    elif suspicious > 0:
        status_header = "⚠️ SHUBHALI (Suspicious)"
    else:
        status_header = "✅ XAVFSIZ (Safe)"

    return (
        f"🔒 **Xavfsizlik tekshiruvi natijasi**\n\n"
        f"📎 **Fayl/Havola**: [Havola]({link})\n"
        f"📊 **Natija**: {status_header}\n\n"
        f"🟢 Xavfsiz: {harmless}\n"
        f"🔴 Zararli: {malicious}\n"
        f"🟠 Shubheli: {suspicious}\n"
        f"⚪️ Aniqlanmagan: {undetected}\n\n"
        f"🔗 [Batafsil hisobot]({link})\n\n"
        f"⚖️ *Mas'uliyatni rad etish: Ushbu bot VirusTotal ma'lumotlariga asoslanadi. "
        f"Natijalar 100% kafolat bermaydi. Har doim ehtiyot bo'ling.*\n\n"
        f"{ad_text}"
    )
