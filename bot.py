import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler
from gemini_integration import process_expense_text, refine_expense_details
from utils import str_to_json, get_or_create_user, insert_expense

load_dotenv()
BOT_TOKEN = os.getenv("TELE_BOT_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# yes/no inline keyboard for user confirmation
keyboard = [
    [InlineKeyboardButton("✅ Yes", callback_data="confirmation"),
     InlineKeyboardButton("❌ No", callback_data="correction")]
]
reply_markup = InlineKeyboardMarkup(keyboard)

# set conversation states
WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT = range(3)


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
    

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle button response from start menu"""
    query = update.callback_query
    await query.answer()  # Acknowledge the button click

    if query.data == "insert_expense":
        await query.message.reply_text("Sure, what did you spend on?")
        return WAITING_FOR_EXPENSE
    
    elif query.data == "export_expenses":
        await query.message.reply_text("Feature in progress; not yet available 😔")
    
    elif query.data == "quit":
        await query.message.reply_text("Goodbye! Type /start if you need me again.")
        return ConversationHandler.END 
    
    
async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle initial expense text processing"""
    user_input = update.message.text
    response = await process_expense_text(user_input)  # call LLM for expense parsing
    json_response = str_to_json(response)
    context.user_data['parsed_expense'] = json_response  # store initial response
    
    await update.message.reply_text(
        f"📌 *Here are the details I got from your text:*\n"
        f"📈 *Currency:* {json_response['currency']}\n"
        f"💰 *Amount:* {json_response['price']}\n"
        f"📂 *Category:* {json_response['category']}\n"
        f"📝 *Description:* {json_response['description']}\n"
        f"📅 *Date:* {json_response['date']}\n\n"
        f"Is this correct?",
        reply_markup=reply_markup
    )
    
    return AWAITING_CONFIRMATION

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle user response from inline keyboard"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    
    if query.data == "confirmation":
        await context.bot.send_message(chat_id,"✅ Great! Let me record your expense...")
        parsed_expense = context.user_data.get('parsed_expense', '')
        
        if isinstance(parsed_expense, dict):  # ensure valid dictionary
            telegram_id = update.effective_user.id
            user_id = get_or_create_user(telegram_id)  # retrieve UUID associated with user
            
            # Insert expense into the database
            insert_expense(
                user_id=user_id,
                price=parsed_expense['price'],
                category=parsed_expense['category'],
                description=parsed_expense['description'],
                date=parsed_expense['date'],
                currency=parsed_expense['currency']
            )
            await context.bot.send_message(chat_id,"✅ Your expense has been recorded successfully!")
            await context.bot.send_message(chat_id, "Would you like to add another expense? Type it below or send /start to go back to the main menu.")
            return WAITING_FOR_EXPENSE  
        else:
            await context.bot.send_message(chat_id,"⚠️ There was an issue processing your expense. Please try again.")
        
        return WAITING_FOR_EXPENSE
      

    else:
        await context.bot.send_message(chat_id,"Sorry I got it wrong! What should the correct details be?")
        return AWAITING_REFINEMENT
    

async def refine_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle user-provided corrections and refines the details"""
    user_feedback = update.message.text
    original_details = context.user_data.get('parsed_expense', '')

    refined_response = await refine_expense_details(original_details, user_feedback)
    json_refined_response = str_to_json(refined_response)

    context.user_data['parsed_expense'] = json_refined_response 

    await update.message.reply_text(
        f"📌 *Here are the refined details:*\n"
        f"📈 *Currency:* {json_refined_response['currency']}\n"
        f"💰 *Amount:* {json_refined_response['price']}\n"
        f"📂 *Category:* {json_refined_response['category']}\n"
        f"📝 *Description:* {json_refined_response['description']}\n"
        f"📅 *Date:* {json_refined_response['date']}\n\n"
        f"Did I get it right this time?",
        reply_markup=reply_markup
    )
    
    return AWAITING_CONFIRMATION


async def reject_unexpected_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject messages if conversation is not active"""
    await update.message.reply_text("Please type /start to begin.")



if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Define conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(button_click)],
        states={
            WAITING_FOR_EXPENSE: [MessageHandler(filters.TEXT, process_text)],
            AWAITING_CONFIRMATION: [CallbackQueryHandler(handle_confirmation)],
            AWAITING_REFINEMENT: [MessageHandler(filters.TEXT, refine_details)],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT, reject_unexpected_messages))
    app.add_handler(CommandHandler("quit", quit))
    app.run_polling()