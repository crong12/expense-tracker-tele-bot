"""
Standalone script for announcing new features to all users

Note: somehow unable to import secretmanager from google.cloud, so I've resorted 
to using the required secret variables from .env instead.
"""

import asyncio
import os
import uuid
from dotenv import load_dotenv
from telegram.ext import Application
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from google.cloud.sql.connector import Connector
from sqlalchemy import create_engine, Column, UUID, BigInteger


SCREENSHOT = "images/edit_expense_screenshot.png"

MESSAGE_TEXT = """
<b>🚀 New Feature! 🚀</b>

I can now edit your past expenses! 

<b>Step 1:</b> In the main menu, select <b>🔧 Edit Expense</b>
<b>Step 2:</b> Simply reply to my message containing your expense details and let me know what you'd like to change 😊

❗️Let @chrxmium know if you face any issues or have any feedback to make me better.
"""

load_dotenv()
BOT_TOKEN = os.getenv("TELE_BOT_TOKEN")
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
REGION = os.getenv("REGION")
INSTANCE_NAME = os.getenv("INSTANCE_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{INSTANCE_NAME}"

connector = Connector()

def get_connection():
    return connector.connect(
        INSTANCE_CONNECTION_NAME,
        "pg8000",
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME
    )

# create connection pool
pool = create_engine(
    "postgresql+pg8000://",
    creator=get_connection,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=pool)

# define tables (as ORM classes)
Base = declarative_base()

class Users(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id = Column(BigInteger, unique=True, nullable=False)

async def broadcast():

    session = SessionLocal()
    users = session.query(Users.telegram_id).all()
    user_ids = [user[0] for user in users]
    session.close()
    app = Application.builder().token(BOT_TOKEN).build()

    async with app:

        for user_id in user_ids:
            try:
                with open(SCREENSHOT, "rb") as image:
                    await app.bot.send_photo(
                        chat_id=user_id,
                        photo=image,
                        caption=MESSAGE_TEXT,
                        parse_mode="HTML"
                    )
                print(f"✅ Announcement sent to {user_id}")
            except Exception as e:
                print(f"⚠️ Failed to send to {user_id}: {e}")

if __name__ == "__main__":
    asyncio.run(broadcast())
