from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from services import get_or_create_user
from config import WAITING_FOR_EXPENSE, AWAITING_EDIT, AWAITING_DELETE_REQUEST, AWAITING_QUERY, AWAITING_EXPORT_CONFIRMATION

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """bot initialisation; create start menu for user input"""
    telegram_id = update.effective_user.id # extract user telegram ID
    tele_handle = update.effective_user.username

    # Check if user has a username set
    if not tele_handle:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Sorry, you need to set a Telegram username to use this bot. "
                 "Please set a username in your Telegram settings and try again."
        )
        return ConversationHandler.END

    get_or_create_user(telegram_id)

    start_keyboard = [
        [InlineKeyboardButton("📌 Insert Expense", callback_data="insert_expense")],
        [InlineKeyboardButton("🔧 Edit Expense", callback_data="edit_expense")],
        [InlineKeyboardButton("📊 Export Expenses", callback_data="export_expenses")],
        [InlineKeyboardButton("🗑️ Delete Expenses", callback_data="delete_expenses")],
        [InlineKeyboardButton("🔍 Analyse Expenses", callback_data="analyse_expenses")],
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

async def reject_unexpected_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rejects messages when no active conversation is happening."""
    await update.message.reply_text("Unknown command. Please type /start to access the main menu.")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle button response from start menu"""
    query = update.callback_query
    await query.answer()

    if query.data == "insert_expense":
        await query.message.reply_text("Sure, what did you spend on? Send me a text message or picture of a receipt please!")
        return WAITING_FOR_EXPENSE

    if query.data == "edit_expense":
        await query.message.reply_text("Which expense would you like to edit? Reply to the message I sent with those expense details and what you would like to change in it 😊")
        return AWAITING_EDIT

    if query.data == "export_expenses":
        export_keyboard = [
            [InlineKeyboardButton("Just this month's", callback_data="this_month"),
             InlineKeyboardButton("All expenses", callback_data="all_expenses")]
        ]
        reply_markup = InlineKeyboardMarkup(export_keyboard)
        await query.message.reply_text("Would you like this month's expenses or all your expenses so far?",
                                       reply_markup=reply_markup)
        return AWAITING_EXPORT_CONFIRMATION

    if query.data == "delete_expenses":
        await query.message.reply_text("Which expense would you like to delete? Reply to a message I sent with those expense details and I'll get rid of it for you. Alternatively, send 'all' to delete all past expenses.")
        return AWAITING_DELETE_REQUEST

    if query.data == "analyse_expenses":
        await query.message.reply_text("Sure, ask me anything about your expenses!")
        return AWAITING_QUERY

    if query.data == "quit":
        await query.message.reply_text("Goodbye! Type /start if you need me again.")
        return ConversationHandler.END
