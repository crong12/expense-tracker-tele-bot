import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
# local version of postgres persistence until ptbcontrib PR is merged
# from ptbcontrib.postgres_persistence import PostgresPersistence
from postgres_persistence import PostgresPersistence
from handlers import start, process_insert, process_edit, button_click, \
    reject_unexpected_messages, refine_details, handle_confirmation, quit_bot,\
    process_delete, delete_expense_confirmation, process_query, export_expenses
from services import is_user_whitelisted
from config import BOT_TOKEN, LANGSMITH_API_KEY, WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, \
    AWAITING_REFINEMENT, AWAITING_EDIT, AWAITING_DELETE_REQUEST, AWAITING_DELETE_CONFIRMATION, \
    AWAITING_QUERY, AWAITING_EXPORT_CONFIRMATION
from database import PERSISTENCE_URL

# enable langsmith tracing
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_PROJECT"] = "expense-bot-deployed"
os.environ["LANGSMITH_API_KEY"] = LANGSMITH_API_KEY

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Create the bot application with PostgreSQL persistence
persistence = PostgresPersistence(
    url=PERSISTENCE_URL
)
bot_app = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

# Track processed update IDs to prevent duplicate processing from Telegram retries
processed_updates = set()
MAX_PROCESSED_UPDATES = 1000  # Keep last 1000 to prevent memory issues

# Define conversation handler with persistence enabled
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_click)],
    states={
        WAITING_FOR_EXPENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_insert),
                              MessageHandler(filters.PHOTO & ~filters.COMMAND, process_insert),
                              CallbackQueryHandler(button_click)],
        AWAITING_CONFIRMATION: [CallbackQueryHandler(handle_confirmation)],
        AWAITING_REFINEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, refine_details)],
        AWAITING_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit),
                        CallbackQueryHandler(button_click)],
        AWAITING_DELETE_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete)],
        AWAITING_DELETE_CONFIRMATION: [CallbackQueryHandler(delete_expense_confirmation)],
        AWAITING_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_query),
                         CallbackQueryHandler(button_click)],
        AWAITING_EXPORT_CONFIRMATION: [CallbackQueryHandler(export_expenses)]
    },
    fallbacks=[CommandHandler("start", start), CommandHandler("quit", quit_bot)],
    name="expense_conversation",  # Unique name for this conversation
    persistent=True,  # Enable persistence for this conversation
)

bot_app.add_handler(conv_handler)
bot_app.add_handler(MessageHandler(filters.TEXT, reject_unexpected_messages))
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("quit", quit_bot))

# Define the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize and start the bot
    try:
        await bot_app.initialize()
        await bot_app.start()
        logging.info("Bot has started successfully with persistence enabled.")

        # Log persistence status
        if bot_app.persistence:
            logging.info("PostgreSQL persistence is active")
        else:
            logging.warning("No persistence configured!")

    except Exception as e: # pylint: disable=broad-except
        logging.error("Error starting bot: %s", str(e))
        raise

    yield

    # Shutdown: Stop the bot
    try:
        await bot_app.stop()
        logging.info("Bot has shut down.")
    except Exception as e: # pylint: disable=broad-except
        logging.error("Error stopping bot: %s", str(e))

# Initialize FastAPI app with the lifespan context manager
app = FastAPI(lifespan=lifespan)

# Webhook health check endpoint
@app.get("/")
async def root():
    return {"status": "Bot is running!"}


async def process_telegram_update(update: Update):
    """Process telegram update in background"""
    try:
        await bot_app.process_update(update)
        logging.info("Successfully processed update %d", update.update_id)
    except Exception as e:
        logging.error("Error processing update %d: %s", update.update_id, str(e))


# Webhook endpoint for Telegram updates
@app.post("/")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Handles webhook updates from Telegram"""
    try:
        update_dict = await request.json()
        logging.info("Received update: %s", update_dict)

        update = Update.de_json(update_dict, bot_app.bot)

        # Check for duplicate updates to prevent reprocessing from Telegram retries
        update_id = update.update_id
        if update_id in processed_updates:
            logging.warning("Duplicate update %d detected, skipping", update_id)
            return {"status": "ok"}

        # Track this update
        processed_updates.add(update_id)
        # Keep set size manageable
        if len(processed_updates) > MAX_PROCESSED_UPDATES:
            # Remove oldest item to prevent unbounded growth
            processed_updates.pop()

        # Defense in depth: Check whitelist before processing any update
        if update and update.effective_user:
            username = update.effective_user.username

            # Check if user has no username set
            if not username:
                await bot_app.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Sorry, you need to set a Telegram username to use this bot. "
                         "Please set a username in your Telegram settings and try again."
                )
                return {"status": "ok"}

            # Check if user is whitelisted
            if not is_user_whitelisted(username):
                logging.warning(
                    "Unauthorized access attempt by user: @%s (ID: %s)",
                    username,
                    update.effective_user.id
                )
                # Send rejection message
                await bot_app.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Sorry, this bot is currently private and available only to whitelisted users. "
                         "Please contact the bot owner (@chrxmium) if you need access."
                )
                # Return ok to Telegram but don't process the update further
                return {"status": "ok"}

        # Add to background tasks and return immediately to prevent Telegram timeout retries
        background_tasks.add_task(process_telegram_update, update)
        return {"status": "ok"}

    except (Exception) as e: # pylint: disable=broad-except
        logging.error("Error processing update: %s", str(e))
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
