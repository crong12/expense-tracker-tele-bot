import os
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from config import AWAITING_EXPORT_CONFIRMATION
from handlers.export_calendar import (
    CalendarCallbackError,
    build_calendar,
    parse_calendar_callback,
)
from services.expenses_svc import export_expenses_to_csv, get_or_create_user


EXPORT_START_DATE_KEY = "export_start_date"


async def _send_export(update, context, time_range, start_date=None, end_date=None):
    telegram_id = update.effective_user.id
    tele_handle = update.effective_user.username
    user_id = get_or_create_user(telegram_id)
    try:
        file_path = export_expenses_to_csv(
            user_id,
            tele_handle,
            time_range=time_range,
            start_date=start_date,
            end_date=end_date,
        )
    finally:
        context.user_data.pop(EXPORT_START_DATE_KEY, None)

    if not file_path:
        await update.callback_query.message.reply_text("No expenses found to export 😔")
        return ConversationHandler.END

    if time_range == "custom_range":
        caption = (
            f"Sure, here's your expenses from {start_date:%d %b %Y} "
            f"to {end_date:%d %b %Y} 📊"
        )
    elif time_range == "this_month":
        caption = "Sure, here's a list of your expenses for this month 📊"
    else:
        caption = "Sure, here's a list of all your expenses so far 📊"
    try:
        with open(file_path, "rb") as document:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=document,
                filename=os.path.basename(file_path),
                caption=caption,
            )
    finally:
        os.remove(file_path)
    return ConversationHandler.END


async def export_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle direct and custom-range CSV exports."""
    query = update.callback_query
    data = query.data

    if data in {"this_month", "all_expenses"}:
        await query.answer()
        context.user_data.pop(EXPORT_START_DATE_KEY, None)
        return await _send_export(update, context, data)

    today = date.today()
    if data == "custom_range":
        await query.answer()
        context.user_data.pop(EXPORT_START_DATE_KEY, None)
        calendar = build_calendar(today.replace(day=1), date.min, today)
        await query.message.reply_text("Select the start date:", reply_markup=calendar)
        return AWAITING_EXPORT_CONFIRMATION

    if isinstance(data, str) and data.startswith("xcal:"):
        stored_start = context.user_data.get(EXPORT_START_DATE_KEY)
        try:
            minimum = date.fromisoformat(stored_start) if stored_start else date.min
            action = parse_calendar_callback(data, minimum, today)
        except (CalendarCallbackError, TypeError, ValueError):
            context.user_data.pop(EXPORT_START_DATE_KEY, None)
            await query.answer(
                "That calendar selection is no longer valid.", show_alert=True
            )
            return AWAITING_EXPORT_CONFIRMATION

        await query.answer()
        prompt = "Select the end date:" if stored_start else "Select the start date:"
        if action.kind == "navigate":
            calendar = build_calendar(action.value, minimum, today)
            await query.message.edit_text(prompt, reply_markup=calendar)
            return AWAITING_EXPORT_CONFIRMATION

        if not stored_start:
            context.user_data[EXPORT_START_DATE_KEY] = action.value.isoformat()
            calendar = build_calendar(action.value.replace(day=1), action.value, today)
            await query.message.edit_text("Select the end date:", reply_markup=calendar)
            return AWAITING_EXPORT_CONFIRMATION

        return await _send_export(
            update,
            context,
            "custom_range",
            date.fromisoformat(stored_start),
            action.value,
        )

    await query.answer("That export option is no longer valid.", show_alert=True)
    return AWAITING_EXPORT_CONFIRMATION
