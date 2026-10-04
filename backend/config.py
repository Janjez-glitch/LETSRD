"""
Configuration file for the AI Language Translation Bot
Store your API keys and settings here
"""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI API Key - Get from https://platform.openai.com/api-keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def get_google_api_key() -> str:
    """Read the Gemini key at call time, keeping GOOGLE_API_KEY as an alias."""
    return os.getenv("GEMINI_API_KEY", "").strip() or os.getenv(
        "GOOGLE_API_KEY", ""
    ).strip()


GOOGLE_API_KEY = get_google_api_key()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()


# Telegram Bot Token - Get from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "your-telegram-bot-token-here")

# Model configuration
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_TOKENS = 2000

# Feature flags
ENABLE_TEXT_TO_SPEECH = True
ENABLE_DIALECT_DETECTION = True
ENABLE_TONE_ADJUSTMENT = True

# Text-to-speech provider (pyttsx3 is free offline)
TTS_PROVIDER = "pyttsx3"  # options: "pyttsx3" (free), "google-tts" (free, online)

# Supported languages for reference
SUPPORTED_LANGUAGES = {
    "English": "en", "Spanish": "es", "French": "fr", "German": "de",
    "Italian": "it", "Portuguese": "pt", "Russian": "ru", "Japanese": "ja",
    "Chinese": "zh", "Korean": "ko", "Arabic": "ar", "Hindi": "hi",
    "Dutch": "nl", "Turkish": "tr", "Polish": "pl", "Swedish": "sv",
    "Norwegian": "no", "Danish": "da", "Finnish": "fi", "Greek": "el",
    "Thai": "th", "Vietnamese": "vi", "Indonesian": "id", "Malay": "ms",
    "Philippine": "tl", "Hebrew": "he", "Afrikaans": "af", "Bengali": "bn",
}
