import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


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
def test_injected_application_receives_handlers_in_registration_order():
    main = _main()

    telegram = TelegramApplicationFake()
    main.create_app(telegram_application=telegram)

    assert [type(handler).__name__ for handler in telegram.handlers] == [
        "ConversationHandler", "MessageHandler", "CommandHandler", "CommandHandler"]
    conversation = telegram.handlers[0]
    assert conversation.name == "expense_conversation" and conversation.persistent is True
    assert len(conversation.entry_points) == 2 and len(conversation.fallbacks) == 2
    assert len(telegram.errors) == 1


@pytest.mark.smoke
async def test_webhook_processes_one_valid_update_and_suppresses_duplicates(monkeypatch):
    main = _main()

    telegram = TelegramApplicationFake()
    application = main.create_app(telegram_application=telegram)
    update = SimpleNamespace(update_id=22, effective_user=None)
    monkeypatch.setattr(main.Update, "de_json", lambda *_: update)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        assert (await client.post("/", json={"update_id": 22})).status_code == 200
        assert (await client.post("/", json={"update_id": 22})).status_code == 200
    telegram.process_update.assert_awaited_once_with(update)


@pytest.mark.smoke
async def test_webhook_rejects_malformed_input_without_detail_leak(monkeypatch):
    main = _main()

    application = main.create_app(telegram_application=TelegramApplicationFake())
    monkeypatch.setattr(main.Update, "de_json", lambda *_: (_ for _ in ()).throw(ValueError("secret")))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/", content=b"{}")
    assert response.status_code == 400 and "secret" not in response.text
