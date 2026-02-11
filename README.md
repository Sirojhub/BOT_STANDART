# GVARD Cybersecurity Bot

A Telegram bot designed for cybersecurity tasks, featuring a Cyberpunk-themed onboarding flow, VirusTotal integration for link and file scanning, and a premium subscription model.

## Features

- **Cyberpunk Onboarding**: Immersive "Matrix/Cyberpunk" style web app for user agreement.
- **Multi-language Support**: English, Russian, Uzbek.
- **Link Scanning**: Scan URLs using VirusTotal API.
- **File Scanning**: Scan files (up to 20MB) using VirusTotal API.
- **User Management**: SQLite database to track users and their offer acceptance status.
- **Premium Features**: Placeholder for 24/7 monitoring and exclusive tools.

## Prerequisites

- Python 3.8+
- Telegram Bot Token (from @BotFather)
- VirusTotal API Key

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd bot_standart
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configuration:**
    Create a `.env` file in the root directory with the following variables:
    ```env
    BOT_TOKEN=your_telegram_bot_token
    VT_API_KEY=your_virustotal_api_key
    WEBAPP_URL=https://your-webapp-url.com/offer.html
    ```
    *Note: `WEBAPP_URL` must point to the hosted `offer.html` file.*

4.  **Run the bot:**
    ```bash
    python main.py
    ```

## Project Structure

- `main.py`: Entry point of the bot.
- `config.py`: Configuration loader.
- `database.py`: Database interactions (SQLite).
- `keyboards.py`: Telegram keyboard layouts.
- `handlers/`:
    - `onboarding.py`: Registration flow and web app data handling.
    - `security.py`: Scanning logic and main menu navigation.
- `offer.html`: The web app frontend file.

## Usage

- Start the bot with `/start`.
- Select your language.
- Open the "Offer" web app to agree to terms.
- Share your phone number to complete registration.
- Use the main menu to check links or files.
