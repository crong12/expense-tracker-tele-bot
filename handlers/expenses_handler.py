import re
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from handlers.misc_handlers import start
from services.gemini_svc import process_expense_text, refine_expense_details
from services.expenses_svc import insert_expense, update_expense, get_or_create_user, exact_expense_matching
from utils import str_to_json
from config import WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT, AWAITING_EDIT

# yes/no inline keyboard for user confirmation
keyboard = [
    [InlineKeyboardButton("✅ Yes", callback_data="confirmation"),
     InlineKeyboardButton("❌ No", callback_data="correction")]
]
reply_markup = InlineKeyboardMarkup(keyboard)


async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles expense text processing"""
    user_input = update.message.text

    # handle case whereby user wants to go back to main menu instead of inputting another expense
    if user_input == "/start":
        return await start(update, context)

    response = await process_expense_text(user_input)
    json_response = str_to_json(response)
    context.user_data['parsed_expense'] = json_response

    await update.message.reply_text(
        f"📌 <b>Here are the details I got from your text:</b>\n"
        f"📈 <b>Currency:</b> {json_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_response['price']}\n"
        f"📂 <b>Category:</b> {json_response['category']}\n"
        f"📝 <b>Description:</b> {json_response['description']}\n"
        f"📅 <b>Date:</b> {json_response['date']}\n\n"
        f"Is this correct?",
        reply_markup=reply_markup,
        parse_mode="HTML"
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
            
            # check if user is editing expense
            expense_id_for_edit = context.user_data.get("editing_expense_id")
            
            # update expense
            if expense_id_for_edit:
                expense_id = update_expense(
                    expense_id=expense_id_for_edit,
                    price=parsed_expense['price'],
                    category=parsed_expense['category'],
                    description=parsed_expense['description'],
                    date=parsed_expense['date'],
                    currency=parsed_expense['currency']
                )
                
                if expense_id:
                    await context.bot.send_message(chat_id,
                                                "<b>✅ Your expense has been updated successfully!</b>\n"
                                                f"📈 <b>Currency:</b> {parsed_expense['currency']}\n"
                                                f"💰 <b>Amount:</b> {parsed_expense['price']}\n"
                                                f"📂 <b>Category:</b> {parsed_expense['category']}\n"
                                                f"📝 <b>Description:</b> {parsed_expense['description']}\n"
                                                f"📅 <b>Date:</b> {parsed_expense['date']}\n\n"
                                                f"<b>Expense ID:</b> {expense_id}\n",
                                                parse_mode = 'HTML')
                    await context.bot.send_message(chat_id, "Would you like to add a new expense? Type it below or send /start to go back to the main menu.")
            
            else:
                # insert expense into the database
                expense_id = insert_expense(
                    user_id=user_id,
                    price=parsed_expense['price'],
                    category=parsed_expense['category'],
                    description=parsed_expense['description'],
                    date=parsed_expense['date'],
                    currency=parsed_expense['currency']
                )
                await context.bot.send_message(chat_id,
                                            "<b>✅ Your expense has been recorded successfully!</b>\n"
                                            f"📈 <b>Currency:</b> {parsed_expense['currency']}\n"
                                            f"💰 <b>Amount:</b> {parsed_expense['price']}\n"
                                            f"📂 <b>Category:</b> {parsed_expense['category']}\n"
                                            f"📝 <b>Description:</b> {parsed_expense['description']}\n"
                                            f"📅 <b>Date:</b> {parsed_expense['date']}\n\n"
                                            f"<b>Expense ID:</b> {expense_id}\n",
                                            parse_mode = 'HTML')
                await context.bot.send_message(chat_id, "Would you like to add another expense? Type it below or send /start to go back to the main menu.")

        else:
            await context.bot.send_message(chat_id,"⚠️ There was an issue processing your request. Please try again.")

        logging.info("Transitioning to WAITING_FOR_EXPENSE")
        return WAITING_FOR_EXPENSE

    else:
        await context.bot.send_message(chat_id,"Sorry I got it wrong! What should the correct details be? Let me know, or type /quit to stop the recording.")
        return AWAITING_REFINEMENT


async def refine_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle user-provided corrections and refines the details"""
    user_feedback = update.message.text

    # # handle case whereby user wants to go back to main menu instead of inputting another expense
    # if user_feedback == "/start":
    #     return await start(update, context)
    # elif user_feedback == '/quit':
    #     await update.message.reply_text("❌ Expense refinement has been canceled. Let's go back to the main menu.")
    #     return await start(update, context)

    original_details = context.user_data.get('parsed_expense', '')

    refined_response = await refine_expense_details(original_details, user_feedback)
    json_refined_response = str_to_json(refined_response)

    context.user_data['parsed_expense'] = json_refined_response

    await update.message.reply_text(
        f"📌 <b>Here are the refined details:</b>\n"
        f"📈 <b>Currency:</b> {json_refined_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_refined_response['price']}\n"
        f"📂 <b>Category:</b> {json_refined_response['category']}\n"
        f"📝 <b>Description:</b> {json_refined_response['description']}\n"
        f"📅 <b>Date:</b> {json_refined_response['date']}\n\n"
        f"Did I get it right this time?",
        reply_markup=reply_markup,
        parse_mode = 'HTML'
    )

    return AWAITING_CONFIRMATION

async def process_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles user response for editing an expense."""

    user_feedback = update.message.text

    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Please reply to a bot message that contains expense details.")
        return AWAITING_EDIT

    # extract expense details from the replied-to message
    original_text = update.message.reply_to_message.text

    await update.message.reply_text("⏱️ Trying to find the expense in the database...")
    # try to extract expense ID for easier matching 
    match = re.search(r"Expense ID:\s*(\d+)", original_text)

    if match:
        expense_id = int(match.group(1)) 
    else:
        expense_id = exact_expense_matching(original_text)      # extract expense ID using exact details in database

    if not expense_id:
        await update.message.reply_text("⚠️ Sorry, I couldn't find the expense in the database. Please try again.")
        return AWAITING_EDIT

    refined_response = await refine_expense_details(original_text, user_feedback)
    json_refined_response = str_to_json(refined_response)

    context.user_data["editing_expense_id"] = expense_id
    context.user_data['parsed_expense'] = json_refined_response

    await update.message.reply_text(
        f"🎯 <b>Here are the edited details:</b>\n"
        f"📈 <b>Currency:</b> {json_refined_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_refined_response['price']}\n"
        f"📂 <b>Category:</b> {json_refined_response['category']}\n"
        f"📝 <b>Description:</b> {json_refined_response['description']}\n"
        f"📅 <b>Date:</b> {json_refined_response['date']}\n\n"
        f"Are you satisfied with the edit?",
        reply_markup=reply_markup,
        parse_mode = 'HTML'
    )

    return AWAITING_CONFIRMATION
