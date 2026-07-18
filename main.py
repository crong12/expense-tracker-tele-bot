import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)
from telegram.request import HTTPXRequest
from ptbcontrib.postgres_persistence import PostgresPersistence

from config import (AWAITING_CATEGORY_RULE, AWAITING_CONFIRMATION, AWAITING_DELETE_CONFIRMATION,
                    AWAITING_DELETE_REQUEST, AWAITING_EDIT, AWAITING_EXPORT_CONFIRMATION,
                    AWAITING_QUERY, AWAITING_REFINEMENT, BOT_TOKEN, Settings,
                    WAITING_FOR_EXPENSE, load_settings)
from handlers import (button_click, delete_expense_confirmation, export_expenses, handle_category_rule,
                      handle_confirmation, process_delete, process_edit, process_insert, process_query,
                      quit_bot, refine_details, reject_unexpected_messages, start)
from services import is_user_whitelisted
from database import PERSISTENCE_URL

MAX_PROCESSED_UPDATES = 1000
INACTIVITY_THRESHOLD = 600


def _telegram_application(settings):
    persistence = PostgresPersistence(url=PERSISTENCE_URL, on_flush=True)
    request = HTTPXRequest(connect_timeout=20.0, read_timeout=30.0, write_timeout=30.0, pool_timeout=5.0)
    return Application.builder().token(settings.bot_token).persistence(persistence).request(request).build()


def _conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_click)],
        states={
            WAITING_FOR_EXPENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_insert), MessageHandler(filters.PHOTO & ~filters.COMMAND, process_insert), CallbackQueryHandler(button_click)],
            AWAITING_CONFIRMATION: [CallbackQueryHandler(handle_confirmation)],
            AWAITING_REFINEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, refine_details)],
            AWAITING_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_edit), CallbackQueryHandler(button_click)],
            AWAITING_DELETE_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete)],
            AWAITING_DELETE_CONFIRMATION: [CallbackQueryHandler(delete_expense_confirmation)],
            AWAITING_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_query), CallbackQueryHandler(button_click)],
            AWAITING_EXPORT_CONFIRMATION: [CallbackQueryHandler(export_expenses)],
            AWAITING_CATEGORY_RULE: [CallbackQueryHandler(handle_category_rule)],
        }, fallbacks=[CommandHandler("start", start), CommandHandler("quit", quit_bot)],
        name="expense_conversation", persistent=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        logging.warning("Telegram transient error: %s", context.error)
        return
    logging.exception("Unhandled error while processing update: %s", context.error)


def create_app(settings: Settings | None = None, telegram_application=None) -> FastAPI:
    settings = settings or load_settings()
    bot_app = telegram_application
    processed_updates = OrderedDict()

    def configure_telegram(application):
        nonlocal bot_app
        if bot_app is None:
            bot_app = _telegram_application(settings)
            application.state.telegram_application = bot_app
        if not getattr(bot_app, "_expense_handlers_registered", False):
            bot_app.add_handler(_conversation_handler())
            bot_app.add_handler(MessageHandler(filters.TEXT, reject_unexpected_messages))
            bot_app.add_handler(CommandHandler("start", start))
            bot_app.add_handler(CommandHandler("quit", quit_bot))
            bot_app.add_error_handler(error_handler)
            setattr(bot_app, "_expense_handlers_registered", True)
        return bot_app

    @asynccontextmanager
    async def lifespan(application):
        active_bot = configure_telegram(application)
        application.state.flush_task = None
        await active_bot.initialize()
        await active_bot.start()
        async def periodic_flush():
            while True:
                try:
                    await asyncio.sleep(60)
                    if active_bot.persistence and application.state.last_update_time and time.time() - application.state.last_update_time < INACTIVITY_THRESHOLD:
                        await active_bot.persistence.flush()
                except asyncio.CancelledError:
                    break
                except Exception as exc:  # pragma: no cover - logging boundary
                    logging.error("Error during periodic flush: %s", exc)
        application.state.flush_task = asyncio.create_task(periodic_flush())
        try:
            yield
        finally:
            application.state.flush_task.cancel()
            try:
                await application.state.flush_task
            except asyncio.CancelledError:
                pass
            if active_bot.persistence:
                await active_bot.persistence.flush()
            await active_bot.stop()

    application = FastAPI(lifespan=lifespan)
    application.state.telegram_application = bot_app
    application.state.processed_updates = processed_updates
    application.state.last_update_time = None
    if bot_app is not None:
        configure_telegram(application)

    @application.get("/")
    async def root():
        return {"status": "Bot is running!"}

    async def process_telegram_update(update):
        try:
            await configure_telegram(application).process_update(update)
        except Exception as exc:  # background errors must not revoke an acknowledged webhook
            logging.error("Error processing update %s: %s", update.update_id, exc)

    @application.post("/")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            update_dict = await request.json()
            active_bot = configure_telegram(application)
            update = Update.de_json(update_dict, active_bot.bot)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid Telegram update") from exc
        if not update or update.update_id is None:
            raise HTTPException(status_code=400, detail="Invalid Telegram update")
        if update.update_id in processed_updates:
            return {"status": "ok"}
        processed_updates[update.update_id] = None
        if len(processed_updates) > MAX_PROCESSED_UPDATES:
            processed_updates.popitem(last=False)
        application.state.last_update_time = time.time()
        if update.effective_user:
            username = update.effective_user.username
            if not username:
                await active_bot.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, you need to set a Telegram username to use this bot. Please set a username in your Telegram settings and try again.")
                return {"status": "ok"}
            try:
                allowed = await asyncio.to_thread(is_user_whitelisted, username)
            except Exception as exc:
                raise HTTPException(status_code=500, detail="Unable to process update") from exc
            if not allowed:
                await active_bot.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this bot is currently private and available only to whitelisted users. Please contact the bot owner (@chrxmium) if you need access.")
                return {"status": "ok"}
        background_tasks.add_task(process_telegram_update, update)
        return {"status": "ok"}
    return application


app = create_app()
