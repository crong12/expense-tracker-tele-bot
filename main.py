import asyncio
import json
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

import config
from config import (AWAITING_CATEGORY_RULE, AWAITING_CONFIRMATION, AWAITING_DELETE_CONFIRMATION,
                    AWAITING_DELETE_REQUEST, AWAITING_EDIT, AWAITING_EXPORT_CONFIRMATION,
                    AWAITING_QUERY, AWAITING_REFINEMENT, Settings, WAITING_FOR_EXPENSE)

MAX_PROCESSED_UPDATES = 1000
INACTIVITY_THRESHOLD = 600
is_user_whitelisted = None


def _runtime(settings, persistence=True):
    config.install_settings(settings)
    from handlers import (button_click, delete_expense_confirmation, export_expenses,
                          handle_category_rule, handle_confirmation, process_delete, process_edit,
                          process_insert, process_query, quit_bot, refine_details,
                          reject_unexpected_messages, start)
    from services.whitelist_svc import is_user_whitelisted
    result = locals()
    if persistence:
        from database import PERSISTENCE_URL
        from ptbcontrib.postgres_persistence import PostgresPersistence
        result["persistence"] = PostgresPersistence(url=PERSISTENCE_URL, on_flush=True)
    return result


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, (TimedOut, NetworkError)):
        logging.warning("Telegram transient error: %s", context.error)
    else:
        logging.exception("Unhandled error while processing update: %s", context.error)


def create_app(settings: Settings | None = None, telegram_application=None) -> FastAPI:
    supplied_settings = settings
    bot_app = telegram_application
    runtime = None
    processed_updates = OrderedDict()

    def configure(application):
        nonlocal bot_app, runtime, supplied_settings
        if supplied_settings is None:
            supplied_settings = config.get_settings()
        if runtime is None:
            runtime = _runtime(supplied_settings, persistence=bot_app is None)
        if bot_app is None:
            request = HTTPXRequest(connect_timeout=20, read_timeout=30, write_timeout=30, pool_timeout=5)
            bot_app = Application.builder().token(supplied_settings.bot_token).persistence(runtime["persistence"]).request(request).build()
            application.state.telegram_application = bot_app
        if not getattr(bot_app, "_expense_handlers_registered", False):
            conversation = ConversationHandler(
                entry_points=[CommandHandler("start", runtime["start"]), CallbackQueryHandler(runtime["button_click"])],
                states={
                    WAITING_FOR_EXPENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, runtime["process_insert"]), MessageHandler(filters.PHOTO & ~filters.COMMAND, runtime["process_insert"]), CallbackQueryHandler(runtime["button_click"])],
                    AWAITING_CONFIRMATION: [CallbackQueryHandler(runtime["handle_confirmation"])],
                    AWAITING_REFINEMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, runtime["refine_details"])],
                    AWAITING_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, runtime["process_edit"]), CallbackQueryHandler(runtime["button_click"])],
                    AWAITING_DELETE_REQUEST: [MessageHandler(filters.TEXT & ~filters.COMMAND, runtime["process_delete"])],
                    AWAITING_DELETE_CONFIRMATION: [CallbackQueryHandler(runtime["delete_expense_confirmation"])],
                    AWAITING_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, runtime["process_query"]), CallbackQueryHandler(runtime["button_click"])],
                    AWAITING_EXPORT_CONFIRMATION: [CallbackQueryHandler(runtime["export_expenses"])],
                    AWAITING_CATEGORY_RULE: [CallbackQueryHandler(runtime["handle_category_rule"])],
                }, fallbacks=[CommandHandler("start", runtime["start"]), CommandHandler("quit", runtime["quit_bot"])], name="expense_conversation", persistent=True)
            bot_app.add_handler(conversation)
            bot_app.add_handler(MessageHandler(filters.TEXT, runtime["reject_unexpected_messages"]))
            bot_app.add_handler(CommandHandler("start", runtime["start"]))
            bot_app.add_handler(CommandHandler("quit", runtime["quit_bot"]))
            bot_app.add_error_handler(error_handler)
            setattr(bot_app, "_expense_handlers_registered", True)
        return bot_app

    @asynccontextmanager
    async def lifespan(application):
        active = configure(application)
        await active.initialize()
        await active.start()
        async def periodic_flush():
            while True:
                try:
                    await asyncio.sleep(60)
                    if active.persistence and application.state.last_update_time and time.time() - application.state.last_update_time < INACTIVITY_THRESHOLD:
                        await active.persistence.flush()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logging.error("Error during periodic flush: %s", exc)
        task = asyncio.create_task(periodic_flush())
        application.state.flush_task = task
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            flush_error = None
            try:
                if active.persistence:
                    await active.persistence.flush()
            except Exception as exc:
                flush_error = exc
            finally:
                await active.stop()
            if flush_error:
                raise flush_error

    application = FastAPI(lifespan=lifespan)
    application.state.telegram_application = bot_app
    application.state.processed_updates = processed_updates
    application.state.last_update_time = None
    if bot_app is not None:
        configure(application)

    @application.get("/")
    async def root(): return {"status": "Bot is running!"}

    async def process_update(update):
        try:
            await configure(application).process_update(update)
        except Exception as exc:
            logging.error("Error processing update %s: %s", update.update_id, exc)

    @application.post("/")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Invalid Telegram update") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("update_id"), int):
            raise HTTPException(400, "Invalid Telegram update")
        try:
            active = configure(application)
            update = Update.de_json(payload, active.bot)
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(400, "Invalid Telegram update") from exc
        except Exception as exc:
            raise HTTPException(500, "Unable to process update") from exc
        if not update or update.update_id is None:
            raise HTTPException(400, "Invalid Telegram update")
        if update.update_id in processed_updates:
            return {"status": "ok"}
        if update.effective_user:
            username = update.effective_user.username
            if not username:
                await active.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, you need to set a Telegram username to use this bot. Please set a username in your Telegram settings and try again.")
                processed_updates[update.update_id] = None
                return {"status": "ok"}
            try:
                whitelist_check = is_user_whitelisted or runtime["is_user_whitelisted"]
                allowed = await asyncio.to_thread(whitelist_check, username)
            except Exception as exc:
                raise HTTPException(500, "Unable to process update") from exc
            if not allowed:
                await active.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, this bot is currently private and available only to whitelisted users. Please contact the bot owner (@chrxmium) if you need access.")
                processed_updates[update.update_id] = None
                return {"status": "ok"}
        processed_updates[update.update_id] = None
        if len(processed_updates) > MAX_PROCESSED_UPDATES:
            processed_updates.popitem(last=False)
        application.state.last_update_time = time.time()
        background_tasks.add_task(process_update, update)
        return {"status": "ok"}
    return application


app = create_app()
