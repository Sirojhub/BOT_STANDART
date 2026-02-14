import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("WARNING: BOT_TOKEN is not set in environment variables.")

# VirusTotal Configuration
VT_API_KEY = os.getenv("VT_API_KEY")
if not VT_API_KEY:
    print("WARNING: VT_API_KEY is not set in environment variables.")

# WebApp Configuration
WEBAPP_URL = os.getenv("WEBAPP_URL")
ADMIN_WEBAPP_URL = os.getenv("ADMIN_WEBAPP_URL")

# Advertising Configuration
AD_PLACEHOLDER_TEXT = "Reklama joyi uchun: @admin"
