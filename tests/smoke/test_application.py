import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _settings(config):
    return config.Settings("123:ABC", "r1", "r2", "u", "p", "db", "localhost", "5432", "o", "l", "project")


class TelegramApplicationFake:
    def __init__(self):
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.persistence = None
        self.handlers = []
        self.errors = []
        self.process_update = AsyncMock()
        self.initialize = AsyncMock()
        self.start = AsyncMock()
        self.stop = AsyncMock()

    def add_handler(self, handler):
        self.handlers.append(handler)

    def add_error_handler(self, handler):
        self.errors.append(handler)


class PersistenceFake:
    def __init__(self):
        self.flush = AsyncMock()


def _main():
    for name in ("main", "handlers", "config", "database", "services", "services.gemini_svc", "services.sql_agent_svc"):
        sys.modules.pop(name, None)
    return importlib.import_module("main")


@pytest.mark.smoke
def test_factory_is_import_safe_and_registers_webhook_routes(monkeypatch):
    names = ("main", "handlers", "config", "database", "services", "services.gemini_svc", "services.sql_agent_svc")
    original = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    try:
        main = importlib.import_module("main")

        application = main.create_app()
        routes = [(route.path, method) for route in application.routes for method in route.methods or ()]

        assert routes.count(("/", "GET")) == 1
        assert routes.count(("/", "POST")) == 1
    finally:
        for name, module in original.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


@pytest.mark.smoke
def test_explicit_settings_and_fake_never_call_production_loader(monkeypatch):
    main = _main()
    monkeypatch.setattr(main.config, "load_settings", lambda: pytest.fail("production settings requested"))
    telegram = TelegramApplicationFake()
    application = main.create_app(_settings(main.config), telegram)
    assert application.state.telegram_application is telegram


@pytest.mark.smoke
def test_injected_application_receives_handlers_in_registration_order():
    main = _main()

    telegram = TelegramApplicationFake()
    main.create_app(telegram_application=telegram)

    assert [type(handler).__name__ for handler in telegram.handlers] == [
        "ConversationHandler", "MessageHandler", "CommandHandler", "CommandHandler"]
    conversation = telegram.handlers[0]
    assert conversation.name == "expense_conversation" and conversation.persistent is True
    assert [handler.callback.__name__ for handler in conversation.entry_points] == ["start", "button_click"]
    assert [handler.callback.__name__ for handler in conversation.fallbacks] == ["start", "quit_bot"]
    assert [[handler.callback.__name__ for handler in conversation.states[state]] for state in range(9)] == [
        ["process_insert", "process_insert", "button_click"], ["handle_confirmation"],
        ["refine_details"], ["process_edit", "button_click"], ["process_delete"],
        ["delete_expense_confirmation"], ["process_query", "button_click"],
        ["export_expenses"], ["handle_category_rule"]]
    assert len(telegram.errors) == 1


@pytest.mark.smoke
async def test_webhook_processes_one_valid_update_and_suppresses_duplicates(monkeypatch):
    main = _main()

    telegram = TelegramApplicationFake()
    application = main.create_app(telegram_application=telegram)
    monkeypatch.setattr(main, "is_user_whitelisted", lambda _: True)
    payload = {"update_id": 22, "message": {"message_id": 1, "date": 0,
        "chat": {"id": 9, "type": "private"},
        "from": {"id": 7, "is_bot": False, "first_name": "Test", "username": "allowed"},
        "text": "/start"}}
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        assert (await client.post("/", json=payload)).status_code == 200
        assert (await client.post("/", json=payload)).status_code == 200
    assert telegram.process_update.await_count == 1
    assert telegram.process_update.await_args.args[0].update_id == 22


@pytest.mark.smoke
async def test_webhook_rejects_malformed_input_without_detail_leak(monkeypatch):
    main = _main()

    application = main.create_app(telegram_application=TelegramApplicationFake())
    monkeypatch.setattr(main.Update, "de_json", lambda *_: (_ for _ in ()).throw(ValueError("secret")))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/", content=b"{}")
    assert response.status_code == 400 and "secret" not in response.text


@pytest.mark.smoke
@pytest.mark.parametrize(("username", "allowed", "expected_messages"), [
    (None, True, 1), ("blocked", False, 1), ("allowed", True, 0),
])
async def test_webhook_enforces_username_and_whitelist_before_processing(monkeypatch, username, allowed, expected_messages):
    main = _main()
    telegram = TelegramApplicationFake()
    application = main.create_app(telegram_application=telegram)
    update = SimpleNamespace(update_id=31, effective_user=SimpleNamespace(username=username, id=7), effective_chat=SimpleNamespace(id=9))
    monkeypatch.setattr(main.Update, "de_json", lambda *_: update)
    monkeypatch.setattr(main, "is_user_whitelisted", lambda _: allowed)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/", json={"update_id": 31})
    assert response.status_code == 200
    assert telegram.bot.send_message.await_count == expected_messages
    assert telegram.process_update.await_count == (1 if allowed and username else 0)


@pytest.mark.smoke
async def test_webhook_returns_500_for_unexpected_ingest_failure(monkeypatch):
    main = _main()
    application = main.create_app(telegram_application=TelegramApplicationFake())
    update = SimpleNamespace(update_id=40, effective_user=SimpleNamespace(username="allowed", id=7), effective_chat=SimpleNamespace(id=9))
    monkeypatch.setattr(main.Update, "de_json", lambda *_: update)
    monkeypatch.setattr(main, "is_user_whitelisted", lambda _: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/", json={"update_id": 40})
    assert response.status_code == 500 and "db unavailable" not in response.text


@pytest.mark.smoke
async def test_failed_authorization_does_not_poison_duplicate_retry(monkeypatch):
    main = _main()
    telegram = TelegramApplicationFake()
    application = main.create_app(telegram_application=telegram)
    update = SimpleNamespace(update_id=41, effective_user=SimpleNamespace(username="allowed", id=7), effective_chat=SimpleNamespace(id=9))
    monkeypatch.setattr(main.Update, "de_json", lambda *_: update)
    outcomes = iter((RuntimeError("temporary"), True))
    def whitelist(_):
        outcome = next(outcomes)
        if isinstance(outcome, Exception): raise outcome
        return outcome
    monkeypatch.setattr(main, "is_user_whitelisted", whitelist)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        assert (await client.post("/", json={"update_id": 41})).status_code == 500
        assert (await client.post("/", json={"update_id": 41})).status_code == 200
    telegram.process_update.assert_awaited_once()


@pytest.mark.smoke
async def test_runtime_decode_failure_is_500_not_client_error(monkeypatch):
    main = _main()
    application = main.create_app(telegram_application=TelegramApplicationFake())
    monkeypatch.setattr(main.Update, "de_json", lambda *_: (_ for _ in ()).throw(RuntimeError("token secret")))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/", json={"update_id": 42})
    assert response.status_code == 500 and "token secret" not in response.text


@pytest.mark.smoke
async def test_lifespan_starts_stops_flushes_and_cancels_periodic_task():
    main = _main()
    telegram = TelegramApplicationFake()
    telegram.persistence = PersistenceFake()
    application = main.create_app(telegram_application=telegram)
    async with application.router.lifespan_context(application):
        task = application.state.flush_task
        assert telegram.initialize.await_count == 1 and telegram.start.await_count == 1
        assert not task.done()
    assert task.done() and telegram.persistence.flush.await_count == 1 and telegram.stop.await_count == 1


@pytest.mark.smoke
async def test_final_flush_failure_still_stops_and_leaves_no_task():
    main = _main()
    telegram = TelegramApplicationFake()
    telegram.persistence = PersistenceFake()
    telegram.persistence.flush.side_effect = RuntimeError("flush failed")
    application = main.create_app(telegram_application=telegram)
    with pytest.raises(RuntimeError, match="flush failed"):
        async with application.router.lifespan_context(application):
            task = application.state.flush_task
    assert task.done() and telegram.stop.await_count == 1


@pytest.mark.smoke
async def test_expense_component_journey_normalizes_and_writes_once(monkeypatch):
    _main()
    from handlers import expenses_handler, misc_handlers
    from tests.fakes.telegram import TelegramScenario

    scenario = TelegramScenario(text="lunch 12.5")
    user_id = "user-1"
    monkeypatch.setattr(misc_handlers, "get_or_create_user", lambda _: user_id)
    monkeypatch.setattr(expenses_handler, "get_or_create_user", lambda _: user_id)
    monkeypatch.setattr(expenses_handler, "get_user_preferred_currency", lambda _: "GBP")
    monkeypatch.setattr(expenses_handler, "get_categories", lambda _: [])
    monkeypatch.setattr(expenses_handler, "get_category_rules", lambda _: [])
    monkeypatch.setattr(expenses_handler, "process_expense_text", AsyncMock(return_value='{"currency":"GBP","price":12.5,"category":"Dining","description":"Lunch","date":"2026-07-18"}'))
    insert = MagicMock(return_value=88)
    monkeypatch.setattr(expenses_handler, "insert_expense", insert)
    monkeypatch.setattr(expenses_handler, "set_user_preferred_currency", MagicMock())

    assert await misc_handlers.start(scenario.update, scenario.context) is None
    scenario.callback_query.data = "insert_expense"
    assert await misc_handlers.button_click(scenario.update, scenario.context) == 0
    assert await expenses_handler.process_insert(scenario.update, scenario.context) == 1
    scenario.callback_query.data = "confirmation"
    assert await expenses_handler.handle_confirmation(scenario.update, scenario.context) == 0
    insert.assert_called_once_with(user_id=user_id, price=12.5, category="Dining", description="Lunch", date="2026-07-18", currency="GBP")
