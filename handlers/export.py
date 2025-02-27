import os
from telegram import Update
from telegram.ext import ContextTypes
from services.expenses_svc import export_expenses_to_csv, get_or_create_user

async def export_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handles export command and sends CSV file to user"""
    query = update.callback_query
    await query.answer()

    telegram_id = update.effective_user.id
    tele_handle = update.effective_user.username
    user_id = get_or_create_user(telegram_id)  # retrieve user's UUID

    file_path = export_expenses_to_csv(user_id, tele_handle)

    if file_path:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(file_path, "rb"),
            filename=os.path.basename(file_path),
            caption="Sure, here's a list of your expenses 📊"
        )
        os.remove(file_path)  # delete file after sending to protect user's privacy
    else:
        await query.message.reply_text("No expenses found to export 😔")
