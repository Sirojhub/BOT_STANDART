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
# On Render, RENDER_EXTERNAL_URL is automatically set to the app's public URL.
# We use this as a default if WEBAPP_URL is not manually set.
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
if RENDER_URL and not RENDER_URL.startswith("http"):
    RENDER_URL = f"https://{RENDER_URL}"

WEBAPP_URL = os.getenv("WEBAPP_URL", RENDER_URL)
ADMIN_WEBAPP_URL = os.getenv("ADMIN_WEBAPP_URL", RENDER_URL)

# Admin IDs (New)
ADMIN_MSG_ID = os.getenv("ADMIN_ID", "1052080030") # Default fallback or empty

# Advertising Configuration
AD_PLACEHOLDER_TEXT = "Reklama joyi uchun: @admin"
