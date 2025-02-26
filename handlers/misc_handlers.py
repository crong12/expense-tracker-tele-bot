from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from services.expenses_svc import get_or_create_user

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """bot initialisation; create start menu for user input"""
    telegram_id = update.effective_user.id # extract user telegram ID
    tele_handle = update.effective_user.username
    get_or_create_user(telegram_id)

    start_keyboard = [
        [InlineKeyboardButton("📌 Insert Expense", callback_data="insert_expense")],
        [InlineKeyboardButton("📊 Export Expenses", callback_data="export_expenses")],
        [InlineKeyboardButton("❌ Quit", callback_data="quit")]
    ]
    start_markup = InlineKeyboardMarkup(start_keyboard)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Hello {tele_handle}! What would you like to do?",
        reply_markup=start_markup
    )

async def quit_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /quit command and ends the conversation."""
    await update.message.reply_text("Goodbye! Type /start if you need me again.")
    return ConversationHandler.END
