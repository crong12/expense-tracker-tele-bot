import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Token
BOT_TOKEN = os.getenv("TELE_BOT_TOKEN")

# Google Cloud Project Config
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
REGION = os.getenv("REGION")

# Database Config
INSTANCE_NAME = os.getenv("INSTANCE_NAME")
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{INSTANCE_NAME}"
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# Gemini Model Config
MODEL_NAME = "gemini-1.5-flash-002"
TEMPERATURE = 0.2