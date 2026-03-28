import re
import os
import time
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TimedOut, NetworkError
from md2tgmd import escape
from services.gemini_svc import process_expense_text, process_expense_image, refine_expense_details
from services.expenses_svc import insert_expense, update_expense, get_or_create_user, \
    exact_expense_matching, delete_all_expenses, delete_specific_expense, get_categories, \
    get_user_preferred_currency, set_user_preferred_currency, get_category_rules, insert_category_rule
from services.sql_agent_svc import analyser_agent
from utils import str_to_json, get_current_date
from config import WAITING_FOR_EXPENSE, AWAITING_CONFIRMATION, AWAITING_REFINEMENT, \
    AWAITING_EDIT, AWAITING_DELETE_REQUEST, AWAITING_DELETE_CONFIRMATION, AWAITING_QUERY, \
    AWAITING_CATEGORY_RULE


# yes/no inline keyboard for user confirmation
keyboard = [
    [InlineKeyboardButton("✅ Yes", callback_data="confirmation"),
     InlineKeyboardButton("❌ No", callback_data="correction")]
]
reply_markup = InlineKeyboardMarkup(keyboard)

# yes/no inline keyboard for category rule prompt
rule_keyboard = [
    [InlineKeyboardButton("✅ Yes", callback_data="save_rule"),
     InlineKeyboardButton("❌ No", callback_data="skip_rule")]
]
rule_reply_markup = InlineKeyboardMarkup(rule_keyboard)


async def process_insert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles expense text processing"""
    message = update.message

    # Get user's preferred currency and existing categories
    telegram_id = update.effective_user.id
    context.user_data['telegram_id'] = telegram_id
    preferred_currency = get_user_preferred_currency(telegram_id)
    user_id = get_or_create_user(telegram_id)
    context.user_data['user_id'] = user_id
    existing_categories = get_categories(user_id)
    category_rules = get_category_rules(user_id)

    if message.text:
        user_input = message.text
        logging.info('calling gemini...')
        response = await process_expense_text(user_input, preferred_currency=preferred_currency, existing_categories=existing_categories, category_rules=category_rules)
        logging.info('response generated')

    elif message.photo:
        image = message.photo[-1]
        image_file = await image.get_file()
        image_path = f"/tmp/{image_file.file_unique_id}.jpg"
        await image_file.download_to_drive(custom_path=image_path)
        if message.caption:
            img_caption = message.caption
            response = await process_expense_image(image_path, caption=img_caption, preferred_currency=preferred_currency, existing_categories=existing_categories, category_rules=category_rules)
        else:
            response = await process_expense_image(image_path, preferred_currency=preferred_currency, existing_categories=existing_categories, category_rules=category_rules)
        os.remove(image_path)   # remove image after parsing completed
    else:
        await message.reply_text("⚠️ I'm sorry, I don't know what that is. Please send either a text message or photo!")
        return WAITING_FOR_EXPENSE

    json_response = str_to_json(response)
    context.user_data['parsed_expense'] = json_response

    await update.message.reply_text(
        f"📌 <b>Here are the details I got from your text:</b>\n"
        f"📈 <b>Currency:</b> {json_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_response['price']:.2f}\n"
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
        telegram_id = update.effective_user.id
        # in handle_confirmation, use cached user_id if available, otherwise create new user
        user_id = context.user_data.get('user_id', None)
        if not user_id:
            user_id = get_or_create_user(telegram_id)

        if isinstance(parsed_expense, dict):  # ensure valid dictionary

            # check if user is editing expense
            is_editing_expense = context.user_data.get("is_editing", False)

            # update expense
            if is_editing_expense:
                expense_id_for_edit = context.user_data.get("editing_expense_id")
                expense_id = update_expense(
                    expense_id=expense_id_for_edit,
                    price=parsed_expense['price'],
                    category=parsed_expense['category'],
                    description=parsed_expense['description'],
                    date=parsed_expense['date'],
                    currency=parsed_expense['currency']
                )
                context.user_data['is_editing'] = False
                await context.bot.send_message(chat_id,
                                            "<b>✅ Your expense has been updated successfully!</b>\n"
                                            f"📈 <b>Currency:</b> {parsed_expense['currency']}\n"
                                            f"💰 <b>Amount:</b> {parsed_expense['price']:.2f}\n"
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
                # update preferred currency to match the confirmed expense
                set_user_preferred_currency(telegram_id, parsed_expense['currency'])
                await context.bot.send_message(chat_id,
                                            "<b>✅ Your expense has been recorded successfully!</b>\n"
                                            f"📈 <b>Currency:</b> {parsed_expense['currency']}\n"
                                            f"💰 <b>Amount:</b> {parsed_expense['price']:.2f}\n"
                                            f"📂 <b>Category:</b> {parsed_expense['category']}\n"
                                            f"📝 <b>Description:</b> {parsed_expense['description']}\n"
                                            f"📅 <b>Date:</b> {parsed_expense['date']}\n\n"
                                            f"<b>Expense ID:</b> {expense_id}\n",
                                            parse_mode = 'HTML')

                # if category was corrected, ask user if they want to save as a rule
                if context.user_data.get('category_corrected', False):
                    description = parsed_expense['description']
                    category = parsed_expense['category']
                    context.user_data['category_corrected'] = False
                    context.user_data['pending_rule_keyword'] = description
                    context.user_data['pending_rule_category'] = category
                    await context.bot.send_message(
                        chat_id,
                        f"🔖 I noticed you changed the category to <b>{category}</b>. "
                        f"Would you like me to always categorize <b>{description}</b> as <b>{category}</b>?",
                        reply_markup=rule_reply_markup,
                        parse_mode='HTML'
                    )
                    return AWAITING_CATEGORY_RULE

                await context.bot.send_message(chat_id, "Would you like to add another expense? Type it below or send /start to go back to the main menu.")

        else:
            await context.bot.send_message(chat_id,"⚠️ There was an issue processing your request. Please try again.")

        logging.info("Transitioning to WAITING_FOR_EXPENSE")
        return WAITING_FOR_EXPENSE

    # if not confirmation, do below
    await context.bot.send_message(chat_id,"Sorry I got it wrong! What should the correct details be? Let me know, or type /quit to stop the recording.")
    return AWAITING_REFINEMENT


async def refine_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """handle user-provided corrections and refines the details"""
    user_feedback = update.message.text

    original_details = context.user_data.get('parsed_expense', '')
    original_currency = original_details.get('currency', '') if isinstance(original_details, dict) else ''
    original_category = original_details.get('category', '') if isinstance(original_details, dict) else ''

    refined_response = await refine_expense_details(original_details, user_feedback)
    json_refined_response = str_to_json(refined_response)

    # Check if currency was changed during refinement
    refined_currency = json_refined_response.get('currency', '')
    if original_currency and refined_currency and original_currency != refined_currency:
        # User explicitly changed the currency - update their preference
        telegram_id = update.effective_user.id
        set_user_preferred_currency(telegram_id, refined_currency)
        logging.info("Updated preferred currency for user %s to %s", telegram_id, refined_currency)

    # Track if category was corrected by the user
    refined_category = json_refined_response.get('category', '')
    if original_category and refined_category and original_category != refined_category:
        context.user_data['category_corrected'] = True

    context.user_data['parsed_expense'] = json_refined_response

    await update.message.reply_text(
        f"📌 <b>Here are the refined details:</b>\n"
        f"📈 <b>Currency:</b> {json_refined_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_refined_response['price']:.2f}\n"
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

    # Extract original currency from the message text
    original_currency_match = re.search(r"Currency:\s*(\w+)", original_text)
    original_currency = original_currency_match.group(1) if original_currency_match else ''

    refined_response = await refine_expense_details(original_text, user_feedback)
    json_refined_response = str_to_json(refined_response)

    # Check if currency was changed during editing
    refined_currency = json_refined_response.get('currency', '')
    if original_currency and refined_currency and original_currency != refined_currency:
        # User explicitly changed the currency - update their preference
        telegram_id = update.effective_user.id
        set_user_preferred_currency(telegram_id, refined_currency)
        logging.info("Updated preferred currency for user %s to %s", telegram_id, refined_currency)

    context.user_data["editing_expense_id"] = expense_id
    context.user_data["is_editing"] = True
    context.user_data['parsed_expense'] = json_refined_response

    await update.message.reply_text(
        f"🎯 <b>Here are the edited details:</b>\n"
        f"📈 <b>Currency:</b> {json_refined_response['currency']}\n"
        f"💰 <b>Amount:</b> {json_refined_response['price']:.2f}\n"
        f"📂 <b>Category:</b> {json_refined_response['category']}\n"
        f"📝 <b>Description:</b> {json_refined_response['description']}\n"
        f"📅 <b>Date:</b> {json_refined_response['date']}\n\n"
        f"Are you satisfied with the edit?",
        reply_markup=reply_markup,
        parse_mode = 'HTML'
    )

    return AWAITING_CONFIRMATION


async def process_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles user response for deleting an expense (or all of them)."""

    user_delete_request = update.message.text

    if 'all' in user_delete_request.lower():
        # user confirmation step
        await update.message.reply_text(
            "⚠️ Are you sure you want to delete ALL your expenses? This action is irreversible!",
            reply_markup=reply_markup
            )
        context.user_data["specific_or_all"] = 'all'
        return AWAITING_DELETE_CONFIRMATION

    # if user does not want to delete all expenses, make sure they reply to a specific message
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Please reply to a bot message that contains expense details.")
        return AWAITING_DELETE_REQUEST

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
        return AWAITING_DELETE_REQUEST

    await update.message.reply_text(
        "⚠️ Are you sure you want to delete this expense?\n"
        f"{original_text}",
        reply_markup=reply_markup
        )

    context.user_data["specific_or_all"] = 'specific'
    context.user_data["expense_id"] = expense_id    # store expense ID in context so that it can be extracted again later

    return AWAITING_DELETE_CONFIRMATION


async def delete_expense_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles confirmation response from the user regarding expense deletion."""
    query = update.callback_query
    await query.answer()

    # extract uuid associated with user
    telegram_id = query.message.chat_id
    user_id = get_or_create_user(telegram_id)

    if query.data == "confirmation" and context.user_data["specific_or_all"] == 'all':
        operation = delete_all_expenses(user_id)
        if operation:
            await query.message.reply_text("✅ All your expenses have been deleted successfully.")
        else:
            await query.message.reply_text("⚠️ An error occurred while deleting your expenses. Please try again.")

    elif query.data == "confirmation" and context.user_data["specific_or_all"] == 'specific':
        expense_id = context.user_data["expense_id"]    # extract expense ID from context
        operation = delete_specific_expense(user_id, expense_id)
        if operation:
            await query.message.edit_text(f"✅ Expense ID {expense_id} has been deleted successfully.")
        else:
            await query.message.edit_text("⚠️ Failed to delete the expense. Please try again.")

    else:  # If the user cancels
        await query.message.edit_text("🚫 Expense deletion canceled.")

    return WAITING_FOR_EXPENSE


async def process_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles user query about expenses"""

    telegram_id = update.effective_user.id
    user_id = get_or_create_user(telegram_id)  # retrieve UUID associated with user
    categories = get_categories(user_id)
    chat_id = update.message.chat_id

    user_query = update.message.text
    previous_answer = context.user_data.get('expense_analysis', "")
    today, day = get_current_date()
    prompt = f"""
    The user's query is: {user_query}.
    
    The user's UUID is {user_id}. ONLY query rows that belong to the user.
    
    Previous answer you provided: {previous_answer}.
    Today's date is {today}. Today is {day}. Infer the date requested by the user based on today's date and previous answer.
    
    If the previous answer is outdated or does not help with getting what the user is requesting for, disregard it.
    
    The list of categories in the user's database is: {categories}.

    
    """

    # Send initial message
    processing_msg = await context.bot.send_message(
        chat_id, "🔍 Processing your expense query... This may take a minute or two. Feel free to walk away from this chat while I'm working!"
    )

    final_answer = None # Variable to store the final answer when found
    last_sent_ts = 0.0
    last_text = None

    try:
        # Set up the stream handler
        async for chunk in analyser_agent.astream(
            {"messages": [("user", prompt)]},
            stream_mode=["updates", "custom"]
            ):

            if isinstance(chunk, tuple) and chunk[0] == 'custom':
                # extract custom progress report message to be sent to user
                message_to_send = chunk[1].get('custom', 'Processing...')

                now = time.time()
                if (message_to_send != last_text) and (now - last_sent_ts > 1.5):
                    try:
                        await context.bot.edit_message_text(
                            message_to_send,
                            chat_id=chat_id,
                            message_id=processing_msg.message_id
                        )
                        last_text = message_to_send
                        last_sent_ts = now
                    except (TimedOut, NetworkError):
                        # Ignore transient network issues and continue streaming
                        pass

            if isinstance(chunk, tuple) and 'analyst' in chunk[1]:
                # extract final answer from analyst node when SubmitFinalAnswer is called
                last_msg = chunk[1]['analyst']['messages'][-1]
                if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls and last_msg.tool_calls[0]["name"] == "SubmitFinalAnswer":
                    final_answer = last_msg.tool_calls[0]["args"]["final_answer"]

        # loop has ended, delete progress report message
        try:
            await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=processing_msg.message_id
                )
        except (TimedOut, NetworkError):
            pass

        # check for final answer
        if final_answer:
            # convert final answer to MarkdownV2 and send to user
            formatted_ans = escape(final_answer)
            try:
                await context.bot.send_message(
                                chat_id,
                                f"{formatted_ans}\n\nAsk me anything else or type /start to return to the main menu\\.",
                                parse_mode='MarkdownV2'
                )
            except (TimedOut, NetworkError):
                pass
            # Store answer for potential follow-up questions
            context.user_data['expense_analysis'] = final_answer
            return AWAITING_QUERY
        else:
            # if we didn't get a proper final result
            try:
                await context.bot.send_message(
                    chat_id,
                    "Sorry, I couldn't process your query properly. Please try again or type /start to return to the main menu."
                )
            except (TimedOut, NetworkError):
                pass
            return AWAITING_QUERY

    except Exception as e: # pylint: disable=broad-except
        # probably no longer an issue now that we're using gpt-4o-mini
        if '429' in str(e):
            try:
                await context.bot.send_message(
                    chat_id,
                    "Sorry, I am unable to answer your query at this moment due to rate limits 😓... Please try again later."
                )
            except (TimedOut, NetworkError):
                pass
        else:
            try:
                await context.bot.send_message(
                    chat_id,
                    f"Sorry, there was an error in processing your query: {str(e)}. Please try again later."
                )
            except (TimedOut, NetworkError):
                pass

    return WAITING_FOR_EXPENSE


async def handle_category_rule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user response to the category rule prompt"""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "save_rule":
        keyword = context.user_data.get('pending_rule_keyword', '')
        category = context.user_data.get('pending_rule_category', '')
        user_id = context.user_data.get('user_id')

        if keyword and category and user_id:
            success = insert_category_rule(user_id, keyword, category)
            if success:
                await context.bot.send_message(
                    chat_id,
                    f"✅ Got it! I'll always categorize <b>{keyword}</b> as <b>{category}</b> from now on.",
                    parse_mode='HTML'
                )
            else:
                await context.bot.send_message(chat_id, "⚠️ Sorry, I couldn't save that preference. Please try again later.")
        else:
            await context.bot.send_message(chat_id, "⚠️ Something went wrong. Please try again later.")
    else:
        await context.bot.send_message(chat_id, "👍 No problem!")

    # clean up
    context.user_data.pop('pending_rule_keyword', None)
    context.user_data.pop('pending_rule_category', None)

    await context.bot.send_message(chat_id, "Would you like to add another expense? Type it below or send /start to go back to the main menu.")
    return WAITING_FOR_EXPENSE
