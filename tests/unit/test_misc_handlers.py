from pathlib import Path
from unittest.mock import MagicMock

import pytest
from telegram.ext import ConversationHandler

from tests.handler_test_bootstrap import ensure_focused_handler_dependencies


ensure_focused_handler_dependencies()
from config import (
    AWAITING_DELETE_REQUEST,
    AWAITING_EDIT,
    AWAITING_EXPORT_CONFIRMATION,
    AWAITING_QUERY,
    WAITING_FOR_EXPENSE,
)
from tests.fakes.telegram import TelegramScenario
from handlers import misc_handlers


pytestmark = pytest.mark.unit


def callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_handler_and_fake_modules_are_loaded_from_this_worktree():
    worktree = Path(__file__).parents[2]

    assert Path(misc_handlers.__file__).resolve() == worktree / "handlers" / "misc_handlers.py"
    assert Path(__import__("tests.fakes.telegram", fromlist=["x"]).__file__).resolve() == (
        worktree / "tests" / "fakes" / "telegram.py"
    )


async def test_start_without_username_requires_username_and_skips_user_creation(monkeypatch):
    scenario = TelegramScenario(username=None)
    get_or_create_user = MagicMock()
    monkeypatch.setattr(misc_handlers, "get_or_create_user", get_or_create_user)

    result = await misc_handlers.start(scenario.update, scenario.context)

    assert result == ConversationHandler.END
    scenario.bot.send_message.assert_awaited_once_with(
        chat_id=202,
        text=(
            "Sorry, you need to set a Telegram username to use this bot. "
            "Please set a username in your Telegram settings and try again."
        ),
    )
    get_or_create_user.assert_not_called()


async def test_start_with_username_creates_user_and_sends_menu(monkeypatch):
    scenario = TelegramScenario(username="alice", user_id=303, chat_id=404)
    get_or_create_user = MagicMock()
    monkeypatch.setattr(misc_handlers, "get_or_create_user", get_or_create_user)

    await misc_handlers.start(scenario.update, scenario.context)

    get_or_create_user.assert_called_once_with(303)
    scenario.bot.send_message.assert_awaited_once()
    sent = scenario.bot.send_message.await_args.kwargs
    assert sent["chat_id"] == 404
    assert sent["text"] == "Hello alice! What would you like to do?"
    assert callback_data(sent["reply_markup"]) == [
        "insert_expense",
        "edit_expense",
        "export_expenses",
        "delete_expenses",
        "analyse_expenses",
        "quit",
    ]
    assert [button.text for row in sent["reply_markup"].inline_keyboard for button in row] == [
        "📌 Insert Expense",
        "🔧 Edit Expense",
        "📊 Export Expenses",
        "🗑️ Delete Expenses",
        "🔍 Analyse Expenses",
        "❌ Quit",
    ]


async def test_quit_bot_sends_goodbye_and_ends_conversation():
    scenario = TelegramScenario()

    result = await misc_handlers.quit_bot(scenario.update, scenario.context)

    assert result == ConversationHandler.END
    scenario.message.reply_text.assert_awaited_once_with("Goodbye! Type /start if you need me again.")


async def test_reject_unexpected_messages_sends_unknown_command_reply():
    scenario = TelegramScenario()

    await misc_handlers.reject_unexpected_messages(scenario.update, scenario.context)

    scenario.message.reply_text.assert_awaited_once_with(
        "Unknown command. Please type /start to access the main menu."
    )


@pytest.mark.parametrize(
    ("data", "expected_reply", "expected_state"),
    [
        ("insert_expense", "Sure, what did you spend on? Send me a text message or picture of a receipt please!", WAITING_FOR_EXPENSE),
        ("edit_expense", "Which expense would you like to edit? Reply to the message I sent with those expense details and what you would like to change in it 😊", AWAITING_EDIT),
        ("delete_expenses", "Which expense would you like to delete? Reply to a message I sent with those expense details and I'll get rid of it for you. Alternatively, send 'all' to delete all past expenses.", AWAITING_DELETE_REQUEST),
        ("analyse_expenses", "Sure, ask me anything about your expenses!", AWAITING_QUERY),
        ("quit", "Goodbye! Type /start if you need me again.", ConversationHandler.END),
    ],
)
async def test_known_button_clicks_acknowledge_reply_and_return_state(data, expected_reply, expected_state):
    scenario = TelegramScenario(callback_data=data)

    result = await misc_handlers.button_click(scenario.update, scenario.context)

    assert result == expected_state
    scenario.callback_query.answer.assert_awaited_once_with()
    scenario.message.reply_text.assert_awaited_once_with(expected_reply)


async def test_export_button_click_offers_export_options_and_returns_state():
    scenario = TelegramScenario(callback_data="export_expenses")

    result = await misc_handlers.button_click(scenario.update, scenario.context)

    assert result == AWAITING_EXPORT_CONFIRMATION
    scenario.callback_query.answer.assert_awaited_once_with()
    scenario.message.reply_text.assert_awaited_once()
    reply = scenario.message.reply_text.await_args
    assert reply.args == ("Which expenses would you like to export?",)
    assert callback_data(reply.kwargs["reply_markup"]) == ["this_month", "custom_range", "all_expenses"]


async def test_unknown_button_click_alerts_and_ends_conversation():
    scenario = TelegramScenario(callback_data="stale_menu_option")

    result = await misc_handlers.button_click(scenario.update, scenario.context)

    assert result == ConversationHandler.END
    scenario.callback_query.answer.assert_awaited_once_with(
        "That menu option is no longer valid.", show_alert=True
    )
    scenario.message.reply_text.assert_not_awaited()
