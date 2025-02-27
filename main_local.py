import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from handlers import start, process_text, export_expenses, refine_details, handle_confirmation, quit_bot
from config import BOT_TOKEN

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Define conversation states
WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT = range(3)

async def reject_unexpected_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rejects messages when no active conversation is happening."""
    await update.message.reply_text("Please type /start to begin.")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle button response from start menu"""
    query = update.callback_query
    await query.answer()

    if query.data == "insert_expense":
        await query.message.reply_text("Sure, what did you spend on?")
        return WAITING_FOR_EXPENSE

    elif query.data == "export_expenses":
        await export_expenses(update, context)

    elif query.data == "quit":
        await query.message.reply_text("Goodbye! Type /start if you need me again.")
        return ConversationHandler.END


if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()

    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_click)],
        states={
            WAITING_FOR_EXPENSE: [MessageHandler(filters.TEXT, process_text), CallbackQueryHandler(button_click)],
            AWAITING_CONFIRMATION: [CallbackQueryHandler(handle_confirmation)],
            AWAITING_REFINEMENT: [MessageHandler(filters.TEXT, refine_details)],
        },
        fallbacks=[CommandHandler("quit", quit_bot)]
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT, reject_unexpected_messages))
    app.add_handler(CommandHandler("quit", quit_bot))
    app.run_polling()
