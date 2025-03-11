import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
from handlers import start, process_insert, process_edit, button_click, \
    reject_unexpected_messages, refine_details, handle_confirmation, quit_bot,\
    process_delete, delete_expense_confirmation, process_query
from config import BOT_TOKEN, LANGSMITH_API_KEY, WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, \
    AWAITING_REFINEMENT, AWAITING_EDIT, AWAITING_DELETE_REQUEST, AWAITING_DELETE_CONFIRMATION, \
    AWAITING_QUERY

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

# Create the bot application
bot_app = Application.builder().token(BOT_TOKEN).build()

# Define conversation handler
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
                         CallbackQueryHandler(button_click)]
    },
    fallbacks=[CommandHandler("start", start), CommandHandler("quit", quit_bot)],
)

bot_app.add_handler(conv_handler)
bot_app.add_handler(MessageHandler(filters.TEXT, reject_unexpected_messages))
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("quit", quit_bot))

# Define the lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize and start the bot
    await bot_app.initialize()
    await bot_app.start()
    logging.info("Bot has started successfully.")
    yield
    # Shutdown: Stop the bot
    await bot_app.stop()
    logging.info("Bot has shut down.")

# Initialize FastAPI app with the lifespan context manager
app = FastAPI(lifespan=lifespan)

# Webhook health check endpoint
@app.get("/")
async def root():
    return {"status": "Bot is running!"}

# Webhook endpoint for Telegram updates
@app.post("/")
async def webhook(request: Request):
    """Handles webhook updates from Telegram"""
    try:
        update_dict = await request.json()
        logging.info(f"Received update: {update_dict}")

        update = Update.de_json(update_dict, bot_app.bot)

        # Process the update asynchronously
        await bot_app.process_update(update)

        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error processing update: {str(e)}")
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
