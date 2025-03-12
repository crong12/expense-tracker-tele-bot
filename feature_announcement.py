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
from sqlalchemy import create_engine, Column, UUID, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from google.cloud.sql.connector import Connector


DEMO = "images/demo_gif_compressed.gif"

MESSAGE_TEXT = """
<b>🚀 Update Alert! 🚀</b>

<b>New feature:</b>

<b> 🤖 LLM-powered Expense Analytics </b>

Want to know more about your spending habits? Just ask me! Powered by <b>GPT-4o-mini</b>, you can now get detailed insights on your expenses and even useful advice on improving your spending habits.

<u>Step 1:</u> In the main menu, select <b>🔍 Analyse Expenses</b>
<u>Step 2:</u> Ask away!

Of course, the more I know about your expenses, the better this feature works. So don't hesitate to track your expenses diligently so you can benefit from this feature! ☺️

❗️Let @chrxmium know if you face any issues or have any feedback to make me better.
"""

load_dotenv()
BOT_TOKEN = os.getenv("TELE_BOT_TOKEN", "").strip().strip('"').strip("'")
#TEST_BOT_TOKEN = os.getenv("TEST_BOT_TOKEN", "").strip().strip('"').strip("'")       # for testing purposes
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

# from md2tgmd import escape
# text = """Okay! Here's a concise summary of your expenses for this month:

# *   **Groceries:** £89.88
# *   **Food:** £54.13
# *   **Utilities:** £36.17
# *   **Entertainment:** £30.00
# *   **Personal:** £18.00
# *   **Medicine:** £10.00
# *   **Miscellaneous:** £9.72

# Your biggest expense this month was groceries. It would be interesting to see how this compares to last month!

# Do you have any other questions? Let me know and I'll do my best to answer them!"""
# text = escape(text)

async def broadcast():

    session = SessionLocal()
    users = session.query(Users.telegram_id).all()
    user_ids = [user[0] for user in users]
    session.close()

    app = Application.builder().token(BOT_TOKEN).build()

    async with app:
        for user_id in user_ids:
            try:
                with open(DEMO, "rb") as file:
                    await app.bot.send_animation(
                        chat_id=user_id,
                        animation=file,
                        caption=MESSAGE_TEXT,
                        parse_mode="HTML"
                    )
                # await app.bot.send_message(
                #     chat_id=user_id,
                #     text=text,
                #     parse_mode='MarkdownV2'
                # )
                print(f"✅ Announcement sent to {user_id}")
            except Exception as e:
                print(f"⚠️ Failed to send to {user_id}: {e}")

if __name__ == "__main__":
    asyncio.run(broadcast())
