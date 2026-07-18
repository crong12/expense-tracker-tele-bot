"""Behaviour-focused coverage for the real expense conversation handlers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.handler_test_bootstrap import ensure_focused_handler_dependencies


ensure_focused_handler_dependencies()
from config import (  # noqa: E402
    AWAITING_CATEGORY_RULE, AWAITING_CONFIRMATION, AWAITING_DELETE_CONFIRMATION,
    AWAITING_DELETE_REQUEST, AWAITING_EDIT, AWAITING_QUERY, AWAITING_REFINEMENT,
    WAITING_FOR_EXPENSE,
)
from handlers import expenses_handler  # noqa: E402
from tests.fakes.telegram import TelegramScenario  # noqa: E402


pytestmark = pytest.mark.unit

EXPENSE = {"currency": "GBP", "price": 12.5, "category": "Food", "description": "Lunch", "date": "2026-07-18"}


def parsed(value=EXPENSE):
    return MagicMock(return_value=value)


def configure_insert(monkeypatch, response='{}'):
    monkeypatch.setattr(expenses_handler, "get_user_preferred_currency", MagicMock(return_value="GBP"))
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=["Food"]))
    monkeypatch.setattr(expenses_handler, "get_category_rules", MagicMock(return_value=[]))
    monkeypatch.setattr(expenses_handler, "str_to_json", parsed())
    return response


def test_real_expense_handler_is_loaded_from_this_worktree():
    worktree = Path(__file__).parents[2]
    assert Path(expenses_handler.__file__).resolve() == worktree / "handlers" / "expenses_handler.py"


def test_context_cleanup_helpers_preserve_unrelated_values():
    data = {"parsed_expense": EXPENSE, "is_editing": True, "editing_expense_id": 2, "specific_or_all": "specific", "expense_id": 2, "keep": 1}
    expenses_handler._clear_expense_context(data)
    expenses_handler._clear_delete_context(data)
    assert data == {"keep": 1}


async def test_photo_failure_removes_downloaded_file(monkeypatch):
    """A parser error must not strand a receipt on disk."""
    scenario = TelegramScenario(photos=[SimpleNamespace(get_file=AsyncMock())], caption="receipt")
    file = SimpleNamespace(file_unique_id="receipt-1", download_to_drive=AsyncMock())
    scenario.message.photo[0].get_file.return_value = file
    configure_insert(monkeypatch)
    monkeypatch.setattr(expenses_handler, "process_expense_image", AsyncMock(side_effect=RuntimeError("parser unavailable")))
    remove = MagicMock()
    monkeypatch.setattr(expenses_handler.os, "remove", remove)

    with pytest.raises(RuntimeError, match="parser unavailable"):
        await expenses_handler.process_insert(scenario.update, scenario.context)

    remove.assert_called_once_with("/tmp/receipt-1.jpg")


async def test_photo_uses_highest_resolution_caption_and_removes_file(monkeypatch):
    low, high = SimpleNamespace(get_file=AsyncMock()), SimpleNamespace(get_file=AsyncMock())
    high_file = SimpleNamespace(file_unique_id="high", download_to_drive=AsyncMock())
    high.get_file.return_value = high_file
    scenario = TelegramScenario(photos=[low, high], caption="business lunch")
    configure_insert(monkeypatch)
    image = AsyncMock(return_value="{}")
    monkeypatch.setattr(expenses_handler, "process_expense_image", image)
    monkeypatch.setattr(expenses_handler.os, "remove", MagicMock())

    await expenses_handler.process_insert(scenario.update, scenario.context)

    low.get_file.assert_not_awaited()
    high_file.download_to_drive.assert_awaited_once_with(custom_path="/tmp/high.jpg")
    image.assert_awaited_once_with("/tmp/high.jpg", caption="business lunch", preferred_currency="GBP", existing_categories=["Food"], category_rules=[])


async def test_delete_confirmation_recovers_from_missing_mode_without_deleting(monkeypatch):
    scenario = TelegramScenario(callback_data="confirmation")
    delete_all = MagicMock()
    delete_specific = MagicMock()
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))
    monkeypatch.setattr(expenses_handler, "delete_all_expenses", delete_all)
    monkeypatch.setattr(expenses_handler, "delete_specific_expense", delete_specific)

    result = await expenses_handler.delete_expense_confirmation(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    delete_all.assert_not_called()
    delete_specific.assert_not_called()
    scenario.message.edit_text.assert_awaited_once_with("🚫 Expense deletion canceled.")


async def test_text_insert_passes_user_preferences_and_displays_confirmation(monkeypatch):
    scenario = TelegramScenario(text="Lunch 12.50")
    configure_insert(monkeypatch)
    process = AsyncMock(return_value='{"ignored": true}')
    monkeypatch.setattr(expenses_handler, "process_expense_text", process)

    result = await expenses_handler.process_insert(scenario.update, scenario.context)

    assert result == AWAITING_CONFIRMATION
    assert scenario.context.user_data["telegram_id"] == 101
    assert scenario.context.user_data["user_id"] == "user-1"
    assert scenario.context.user_data["parsed_expense"] == EXPENSE
    process.assert_awaited_once_with("Lunch 12.50", preferred_currency="GBP", existing_categories=["Food"], category_rules=[])
    assert "Currency:" in scenario.message.reply_text.await_args.args[0]


async def test_missing_expense_input_returns_waiting_without_parsed_data(monkeypatch):
    scenario = TelegramScenario()
    configure_insert(monkeypatch)

    result = await expenses_handler.process_insert(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    assert "parsed_expense" not in scenario.context.user_data
    assert "text message or photo" in scenario.message.reply_text.await_args.args[0]


async def test_malformed_insert_result_keeps_context_clean_and_returns_safe_state(monkeypatch):
    scenario = TelegramScenario(text="Lunch")
    configure_insert(monkeypatch)
    monkeypatch.setattr(expenses_handler, "process_expense_text", AsyncMock(return_value="not json"))
    monkeypatch.setattr(expenses_handler, "str_to_json", MagicMock(return_value="error: Failed to parse response as JSON"))

    result = await expenses_handler.process_insert(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    assert "parsed_expense" not in scenario.context.user_data
    assert "issue processing" in scenario.message.reply_text.await_args.args[0]


async def test_confirmation_inserts_normalized_expense_and_prompts_for_next(monkeypatch):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"user_id": "user-1", "parsed_expense": EXPENSE, "unrelated": "keep"})
    insert = MagicMock(return_value=77)
    monkeypatch.setattr(expenses_handler, "insert_expense", insert)
    monkeypatch.setattr(expenses_handler, "set_user_preferred_currency", MagicMock())

    result = await expenses_handler.handle_confirmation(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    insert.assert_called_once_with(user_id="user-1", **EXPENSE)
    assert scenario.context.user_data["unrelated"] == "keep"
    assert any("recorded successfully" in call.args[1] for call in scenario.bot.send_message.await_args_list)


async def test_confirmation_insert_failure_does_not_claim_success(monkeypatch):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"user_id": "user-1", "parsed_expense": EXPENSE})
    monkeypatch.setattr(expenses_handler, "insert_expense", MagicMock(return_value=None))
    monkeypatch.setattr(expenses_handler, "set_user_preferred_currency", MagicMock())

    await expenses_handler.handle_confirmation(scenario.update, scenario.context)

    assert not any("recorded successfully" in call.args[1] for call in scenario.bot.send_message.await_args_list)
    assert any("issue processing" in call.args[1] for call in scenario.bot.send_message.await_args_list)


async def test_confirmation_category_correction_sets_rule_context_and_cleans_expense(monkeypatch):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"user_id": "user-1", "parsed_expense": EXPENSE, "category_corrected": True, "keep": 1})
    monkeypatch.setattr(expenses_handler, "insert_expense", MagicMock(return_value=1))
    monkeypatch.setattr(expenses_handler, "set_user_preferred_currency", MagicMock())
    result = await expenses_handler.handle_confirmation(scenario.update, scenario.context)
    assert result == AWAITING_CATEGORY_RULE
    assert scenario.context.user_data["pending_rule_keyword"] == "Lunch"
    assert scenario.context.user_data["pending_rule_category"] == "Food"
    assert "parsed_expense" not in scenario.context.user_data
    assert scenario.context.user_data["keep"] == 1


@pytest.mark.parametrize(("expense_id", "expected"), [(80, "updated successfully"), (False, "issue processing"), (None, "issue processing")])
async def test_edit_confirmation_handles_service_result_and_cleans_edit_context(monkeypatch, expense_id, expected):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"parsed_expense": EXPENSE, "is_editing": True, "editing_expense_id": 12, "other": "stay"})
    update = MagicMock(return_value=expense_id)
    monkeypatch.setattr(expenses_handler, "update_expense", update)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))

    result = await expenses_handler.handle_confirmation(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    update.assert_called_once_with(expense_id=12, **EXPENSE)
    assert any(expected in call.args[1] for call in scenario.bot.send_message.await_args_list)
    assert "is_editing" not in scenario.context.user_data
    assert "editing_expense_id" not in scenario.context.user_data
    assert "parsed_expense" not in scenario.context.user_data
    assert scenario.context.user_data["other"] == "stay"


async def test_edit_confirmation_without_id_recovers_without_update(monkeypatch):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"parsed_expense": EXPENSE, "is_editing": True})
    update = MagicMock()
    monkeypatch.setattr(expenses_handler, "update_expense", update)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))

    result = await expenses_handler.handle_confirmation(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    update.assert_not_called()
    assert any("issue processing" in call.args[1] for call in scenario.bot.send_message.await_args_list)


async def test_correction_moves_to_refinement_and_keeps_parsed_details():
    scenario = TelegramScenario(callback_data="correction")
    scenario.context.user_data.update({"parsed_expense": EXPENSE, "unrelated": "keep"})

    result = await expenses_handler.handle_confirmation(scenario.update, scenario.context)

    assert result == AWAITING_REFINEMENT
    assert scenario.context.user_data["parsed_expense"] == EXPENSE


async def test_refinement_stores_valid_result_and_tracks_category_change(monkeypatch):
    scenario = TelegramScenario(text="make it transport")
    scenario.context.user_data["parsed_expense"] = EXPENSE
    refined = {**EXPENSE, "category": "Transport"}
    refine = AsyncMock(return_value="ignored")
    monkeypatch.setattr(expenses_handler, "refine_expense_details", refine)
    monkeypatch.setattr(expenses_handler, "str_to_json", parsed(refined))

    result = await expenses_handler.refine_details(scenario.update, scenario.context)

    assert result == AWAITING_CONFIRMATION
    refine.assert_awaited_once_with(EXPENSE, "make it transport")
    assert scenario.context.user_data["parsed_expense"] == refined
    assert scenario.context.user_data["category_corrected"] is True


async def test_malformed_refinement_preserves_original_details(monkeypatch):
    scenario = TelegramScenario(text="change it")
    scenario.context.user_data["parsed_expense"] = EXPENSE
    monkeypatch.setattr(expenses_handler, "refine_expense_details", AsyncMock(return_value="bad"))
    monkeypatch.setattr(expenses_handler, "str_to_json", MagicMock(return_value="error"))

    result = await expenses_handler.refine_details(scenario.update, scenario.context)

    assert result == AWAITING_REFINEMENT
    assert scenario.context.user_data["parsed_expense"] == EXPENSE
    assert "issue processing" in scenario.message.reply_text.await_args.args[0]


async def test_refinement_exception_preserves_original_details(monkeypatch):
    scenario = TelegramScenario(text="change it")
    scenario.context.user_data["parsed_expense"] = EXPENSE
    monkeypatch.setattr(expenses_handler, "refine_expense_details", AsyncMock(side_effect=RuntimeError("down")))

    result = await expenses_handler.refine_details(scenario.update, scenario.context)

    assert result == AWAITING_REFINEMENT
    assert scenario.context.user_data["parsed_expense"] == EXPENSE


async def test_edit_requires_reply_target():
    scenario = TelegramScenario(text="change amount")

    result = await expenses_handler.process_edit(scenario.update, scenario.context)

    assert result == AWAITING_EDIT
    assert "Please reply" in scenario.message.reply_text.await_args.args[0]


async def test_edit_with_embedded_id_prepares_confirmation(monkeypatch):
    source = "Currency: GBP\nExpense ID: 42"
    scenario = TelegramScenario(text="make it 15", reply_to_text=source)
    refine = AsyncMock(return_value="ignored")
    monkeypatch.setattr(expenses_handler, "refine_expense_details", refine)
    monkeypatch.setattr(expenses_handler, "str_to_json", parsed())

    result = await expenses_handler.process_edit(scenario.update, scenario.context)

    assert result == AWAITING_CONFIRMATION
    assert scenario.context.user_data["editing_expense_id"] == 42
    assert scenario.context.user_data["is_editing"] is True
    refine.assert_awaited_once_with(source, "make it 15")


async def test_edit_fallback_no_match_and_refinement_failures_are_safe(monkeypatch):
    source = "Currency: GBP\nno id"
    scenario = TelegramScenario(text="change", reply_to_text=source)
    matcher = MagicMock(return_value=None)
    monkeypatch.setattr(expenses_handler, "exact_expense_matching", matcher)
    result = await expenses_handler.process_edit(scenario.update, scenario.context)
    assert result == AWAITING_EDIT
    matcher.assert_called_once_with(source)

    scenario = TelegramScenario(text="change", reply_to_text=source)
    monkeypatch.setattr(expenses_handler, "exact_expense_matching", MagicMock(return_value=4))
    monkeypatch.setattr(expenses_handler, "refine_expense_details", AsyncMock(side_effect=RuntimeError("down")))
    result = await expenses_handler.process_edit(scenario.update, scenario.context)
    assert result == AWAITING_EDIT
    assert "editing_expense_id" not in scenario.context.user_data


async def test_delete_all_prompts_for_confirmation():
    scenario = TelegramScenario(text="delete all expenses")

    result = await expenses_handler.process_delete(scenario.update, scenario.context)

    assert result == AWAITING_DELETE_CONFIRMATION
    assert scenario.context.user_data["specific_or_all"] == "all"


async def test_specific_delete_falls_back_to_matching_and_stores_only_selected_id(monkeypatch):
    scenario = TelegramScenario(text="delete this", reply_to_text="details without id")
    matcher = MagicMock(return_value=55)
    monkeypatch.setattr(expenses_handler, "exact_expense_matching", matcher)

    result = await expenses_handler.process_delete(scenario.update, scenario.context)

    assert result == AWAITING_DELETE_CONFIRMATION
    matcher.assert_called_once_with("details without id")
    assert scenario.context.user_data["specific_or_all"] == "specific"
    assert scenario.context.user_data["expense_id"] == 55


@pytest.mark.parametrize(("mode", "operation", "expected"), [("all", True, "All your expenses"), ("all", False, "error occurred"), ("specific", True, "deleted successfully"), ("specific", False, "Failed to delete")])
async def test_delete_confirmation_delegates_correctly_and_cleans_context(monkeypatch, mode, operation, expected):
    scenario = TelegramScenario(callback_data="confirmation")
    scenario.context.user_data.update({"specific_or_all": mode, "expense_id": 6, "keep": 1})
    bulk, specific = MagicMock(return_value=operation), MagicMock(return_value=operation)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))
    monkeypatch.setattr(expenses_handler, "delete_all_expenses", bulk)
    monkeypatch.setattr(expenses_handler, "delete_specific_expense", specific)
    result = await expenses_handler.delete_expense_confirmation(scenario.update, scenario.context)
    assert result == WAITING_FOR_EXPENSE
    if mode == "all": bulk.assert_called_once_with("user-1")
    else: specific.assert_called_once_with("user-1", 6)
    assert "specific_or_all" not in scenario.context.user_data and "expense_id" not in scenario.context.user_data
    calls = scenario.message.reply_text.await_args_list + scenario.message.edit_text.await_args_list
    assert any(expected in call.args[0] for call in calls)


async def test_delete_cancellation_cleans_context(monkeypatch):
    scenario = TelegramScenario(callback_data="correction")
    scenario.context.user_data.update({"specific_or_all": "all", "expense_id": 6})
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="user-1"))
    await expenses_handler.delete_expense_confirmation(scenario.update, scenario.context)
    assert "specific_or_all" not in scenario.context.user_data


async def test_save_rule_delegates_and_always_cleans_pending_context(monkeypatch):
    scenario = TelegramScenario(callback_data="save_rule")
    scenario.context.user_data.update({"user_id": "user-1", "pending_rule_keyword": "cafe", "pending_rule_category": "Food", "other": 9})
    insert_rule = MagicMock(return_value=True)
    monkeypatch.setattr(expenses_handler, "insert_category_rule", insert_rule)

    result = await expenses_handler.handle_category_rule(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    insert_rule.assert_called_once_with("user-1", "cafe", "Food")
    assert "pending_rule_keyword" not in scenario.context.user_data
    assert scenario.context.user_data["other"] == 9


@pytest.mark.parametrize("data", [{"user_id": "user-1", "pending_rule_keyword": "cafe", "pending_rule_category": "Food"}, {"user_id": "user-1"}])
async def test_rule_failure_or_missing_data_does_not_call_invalid_service(monkeypatch, data):
    scenario = TelegramScenario(callback_data="save_rule")
    scenario.context.user_data.update(data)
    service = MagicMock(return_value=False)
    monkeypatch.setattr(expenses_handler, "insert_category_rule", service)
    await expenses_handler.handle_category_rule(scenario.update, scenario.context)
    if "pending_rule_keyword" in data:
        service.assert_called_once()
    else:
        service.assert_not_called()
    assert "pending_rule_keyword" not in scenario.context.user_data


async def test_skip_rule_acknowledges_and_cleans_pending_context():
    scenario = TelegramScenario(callback_data="skip_rule")
    scenario.context.user_data.update({"pending_rule_keyword": "cafe", "pending_rule_category": "Food"})

    result = await expenses_handler.handle_category_rule(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    scenario.callback_query.answer.assert_awaited_once_with()
    assert "pending_rule_keyword" not in scenario.context.user_data


async def stream_chunks(*chunks):
    for chunk in chunks:
        yield chunk


async def test_query_builds_user_scoped_prompt_streams_progress_and_saves_final_answer(monkeypatch):
    scenario = TelegramScenario(text="How much did I spend?")
    scenario.context.user_data["expense_analysis"] = "previous answer"
    processing = SimpleNamespace(message_id=88)
    scenario.bot.send_message.return_value = processing
    agent = MagicMock()
    analyst_message = SimpleNamespace(tool_calls=[{"name": "SubmitFinalAnswer", "args": {"final_answer": "You spent £12.50"}}])
    agent.astream.return_value = stream_chunks(
        ("custom", {"custom": "Looking up expenses"}),
        ("analyst", {"analyst": {"messages": [analyst_message]}}),
    )
    monkeypatch.setattr(expenses_handler, "analyser_agent", agent)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="uuid-1"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=["Food", "Travel"]))
    monkeypatch.setattr(expenses_handler, "get_current_date", MagicMock(return_value=("2026-07-18", "Saturday")))
    monkeypatch.setattr(expenses_handler, "escape", MagicMock(side_effect=lambda value: value))
    monkeypatch.setattr(expenses_handler.time, "time", MagicMock(return_value=2.0))

    result = await expenses_handler.process_query(scenario.update, scenario.context)

    assert result == AWAITING_QUERY
    prompt = agent.astream.call_args.args[0]["messages"][0][1]
    for required in ("uuid-1", "ONLY query rows", "Food", "2026-07-18", "Saturday", "How much did I spend?", "previous answer"):
        assert required in prompt
    scenario.bot.edit_message_text.assert_awaited_once_with("Looking up expenses", chat_id=202, message_id=88)
    scenario.bot.delete_message.assert_awaited_once_with(chat_id=202, message_id=88)
    assert scenario.context.user_data["expense_analysis"] == "You spent £12.50"


async def test_query_without_final_answer_sends_retry_and_cleans_progress(monkeypatch):
    scenario = TelegramScenario(text="What did I spend?")
    scenario.bot.send_message.return_value = SimpleNamespace(message_id=88)
    agent = MagicMock()
    agent.astream.return_value = stream_chunks(("custom", {"custom": "Working"}))
    monkeypatch.setattr(expenses_handler, "analyser_agent", agent)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="uuid-1"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=[]))
    monkeypatch.setattr(expenses_handler.time, "time", MagicMock(return_value=2.0))

    result = await expenses_handler.process_query(scenario.update, scenario.context)

    assert result == AWAITING_QUERY
    scenario.bot.delete_message.assert_awaited_once_with(chat_id=202, message_id=88)
    assert "couldn't process" in scenario.bot.send_message.await_args_list[-1].args[1]


async def test_query_deduplicates_and_throttles_progress(monkeypatch):
    scenario = TelegramScenario(text="analysis")
    scenario.bot.send_message.return_value = SimpleNamespace(message_id=88)
    agent = MagicMock()
    agent.astream.return_value = stream_chunks(
        ("custom", {"custom": "one"}), ("custom", {"custom": "one"}),
        ("custom", {"custom": "two"}), ("custom", {"custom": "three"}),
    )
    monkeypatch.setattr(expenses_handler, "analyser_agent", agent)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="u"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=[]))
    monkeypatch.setattr(expenses_handler.time, "time", MagicMock(side_effect=[2.0, 2.2, 2.4, 4.0]))
    await expenses_handler.process_query(scenario.update, scenario.context)
    # Duplicate "one" is suppressed and only two of four rapid progress chunks are eligible.
    assert [call.args[0] for call in scenario.bot.edit_message_text.await_args_list] == ["one", "two"]


@pytest.mark.parametrize("failure", ["edit", "delete", "final"])
async def test_query_swallows_network_errors_at_message_boundaries(monkeypatch, failure):
    scenario = TelegramScenario(text="analysis")
    processing = SimpleNamespace(message_id=88)
    analyst = SimpleNamespace(tool_calls=[{"name": "SubmitFinalAnswer", "args": {"final_answer": "answer"}}])
    agent = MagicMock()
    agent.astream.return_value = stream_chunks(("custom", {"custom": "one"}), ("analyst", {"analyst": {"messages": [analyst]}}))
    monkeypatch.setattr(expenses_handler, "analyser_agent", agent)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="u"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=[]))
    monkeypatch.setattr(expenses_handler, "escape", MagicMock(side_effect=lambda value: value))
    monkeypatch.setattr(expenses_handler.time, "time", MagicMock(return_value=2.0))
    scenario.bot.send_message.return_value = processing
    if failure == "edit": scenario.bot.edit_message_text.side_effect = expenses_handler.TimedOut()
    elif failure == "delete": scenario.bot.delete_message.side_effect = expenses_handler.NetworkError("down")
    else: scenario.bot.send_message.side_effect = [processing, expenses_handler.TimedOut()]
    result = await expenses_handler.process_query(scenario.update, scenario.context)
    assert result == AWAITING_QUERY
    assert scenario.context.user_data["expense_analysis"] == "answer"


@pytest.mark.parametrize(("error", "expected"), [(RuntimeError("429 overloaded"), "rate limits"), (RuntimeError("broken"), "error in processing")])
async def test_query_stream_errors_use_existing_error_variants(monkeypatch, error, expected):
    scenario = TelegramScenario(text="analysis")
    scenario.bot.send_message.return_value = SimpleNamespace(message_id=88)
    agent = MagicMock()

    async def broken_stream(*args, **kwargs):
        raise error
        yield None

    agent.astream.return_value = broken_stream()
    monkeypatch.setattr(expenses_handler, "analyser_agent", agent)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", MagicMock(return_value="uuid-1"))
    monkeypatch.setattr(expenses_handler, "get_categories", MagicMock(return_value=[]))

    result = await expenses_handler.process_query(scenario.update, scenario.context)

    assert result == WAITING_FOR_EXPENSE
    assert expected in scenario.bot.send_message.await_args_list[-1].args[1]
