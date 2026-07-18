import asyncio
import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from google.genai import errors as genai_errors
from tenacity import wait_none


pytestmark = pytest.mark.unit


class FakeClient:
    def __init__(self, outcomes):
        self.aio = SimpleNamespace(models=SimpleNamespace(
            generate_content=AsyncMock(side_effect=outcomes)
        ))


@contextmanager
def isolated_gemini_service():
    previous_config = sys.modules.get("config")
    previous_service = sys.modules.get("services.gemini_svc")
    config = ModuleType("config")
    config.PROJECT_ID = "test-project"
    config.MODEL_NAME = "test-gemini"
    sys.modules["config"] = config
    sys.modules.pop("services.gemini_svc", None)
    source = Path(__file__).parents[2] / "services" / "gemini_svc.py"
    spec = importlib.util.spec_from_file_location("services.gemini_svc", source)
    service = importlib.util.module_from_spec(spec)
    sys.modules["services.gemini_svc"] = service
    spec.loader.exec_module(service)
    for function in (
        service.process_expense_text,
        service.process_expense_image,
        service.refine_expense_details,
    ):
        function.retry.wait = wait_none()
    try:
        yield service
    finally:
        if previous_config is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = previous_config
        if previous_service is None:
            sys.modules.pop("services.gemini_svc", None)
        else:
            sys.modules["services.gemini_svc"] = previous_service


@pytest.fixture
def gemini_service():
    with isolated_gemini_service() as service:
        yield service


def gemini_api_error(code):
    response = SimpleNamespace(body_segments=[{"error": {"code": code}}])
    error_type = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return error_type(code, response)


@pytest.mark.asyncio
async def test_text_returns_valid_json_response_unchanged(gemini_service):
    gemini_service.client = FakeClient([SimpleNamespace(text=' {"price": 12} ')])

    result = await gemini_service.process_expense_text("coffee")

    assert result == ' {"price": 12} '


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    object(), SimpleNamespace(text=None), SimpleNamespace(text=""),
    SimpleNamespace(text="  "), SimpleNamespace(text="not json"),
    SimpleNamespace(text="[]"),
])
async def test_text_rejects_non_object_response_text(gemini_service, response):
    gemini_service.client = FakeClient([response])

    with pytest.raises(gemini_service.GeminiResponseError):
        await gemini_service.process_expense_text("coffee")


def test_response_error_is_a_value_error(gemini_service):
    assert issubclass(gemini_service.GeminiResponseError, ValueError)


def test_isolated_import_restores_exact_prior_module_registry():
    original_config = sys.modules.get("config")
    original_service = sys.modules.get("services.gemini_svc")
    prior_config = ModuleType("prior_config")
    prior_service = ModuleType("prior_service")
    sys.modules["config"] = prior_config
    sys.modules["services.gemini_svc"] = prior_service
    try:
        with isolated_gemini_service() as service:
            expected_source = Path(__file__).parents[2] / "services" / "gemini_svc.py"
            assert Path(service.__file__).resolve() == expected_source.resolve()
            assert sys.modules["config"] is not prior_config
            assert sys.modules["services.gemini_svc"] is service
        assert sys.modules["config"] is prior_config
        assert sys.modules["services.gemini_svc"] is prior_service
    finally:
        if original_config is None:
            sys.modules.pop("config", None)
        else:
            sys.modules["config"] = original_config
        if original_service is None:
            sys.modules.pop("services.gemini_svc", None)
        else:
            sys.modules["services.gemini_svc"] = original_service


def test_isolated_import_restores_prior_module_absence():
    original_config = sys.modules.get("config")
    original_service = sys.modules.get("services.gemini_svc")
    sys.modules.pop("config", None)
    sys.modules.pop("services.gemini_svc", None)
    try:
        with isolated_gemini_service():
            assert "config" in sys.modules
            assert "services.gemini_svc" in sys.modules
        assert "config" not in sys.modules
        assert "services.gemini_svc" not in sys.modules
    finally:
        if original_config is not None:
            sys.modules["config"] = original_config
        if original_service is not None:
            sys.modules["services.gemini_svc"] = original_service


@pytest.mark.asyncio
async def test_text_prompt_and_sdk_call_include_supplied_context(gemini_service, monkeypatch):
    monkeypatch.setattr(gemini_service, "get_current_date", lambda: ("2026-07-18", "Saturday"))
    fake = FakeClient([SimpleNamespace(text='{}')])
    gemini_service.client = fake

    await gemini_service.process_expense_text(
        "Lunch at cafe", "SGD", ["Food", "Travel"],
        [{"keyword": "cafe", "category": "Food"}],
    )

    call = fake.aio.models.generate_content.await_args
    assert call.kwargs["model"] == "test-gemini"
    assert call.kwargs["config"] is gemini_service.expense_config
    prompt = call.kwargs["contents"]
    for value in ("Lunch at cafe", "2026-07-18", "Saturday", "SGD", "Assume that $ is SGD", "Food", "Travel", "'cafe' -> Food", "MUST use"):
        assert value in prompt


@pytest.mark.asyncio
async def test_text_uses_generic_category_instruction_without_categories(gemini_service):
    fake = FakeClient([SimpleNamespace(text='{}')])
    gemini_service.client = fake

    await gemini_service.process_expense_text("coffee", existing_categories=[])

    prompt = fake.aio.models.generate_content.await_args.kwargs["contents"]
    assert "think about what it should be" in prompt
    assert "existing categories are" not in prompt


@pytest.mark.asyncio
async def test_text_retries_transient_gemini_error_then_returns_success(gemini_service):
    fake = FakeClient([gemini_api_error(429), SimpleNamespace(text='{}')])
    gemini_service.client = fake

    assert await gemini_service.process_expense_text("coffee") == "{}"
    assert fake.aio.models.generate_content.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("timed out"), ConnectionError("disconnected")])
@pytest.mark.parametrize("function", [
    "process_expense_text", "process_expense_image", "refine_expense_details",
])
async def test_public_functions_do_not_retry_builtin_transport_errors(
    gemini_service, monkeypatch, tmp_path, error, function,
):
    args = ("coffee",)
    if function == "process_expense_image":
        image = tmp_path / "receipt.jpg"
        image.write_bytes(b"\xff\xd8\xffx")
        monkeypatch.setattr(gemini_service.types.Part, "from_bytes", Mock(return_value="part"))
        args = (str(image),)
    elif function == "refine_expense_details":
        args = ({}, "feedback")
    fake = FakeClient([error])
    gemini_service.client = fake

    with pytest.raises(type(error)):
        await getattr(gemini_service, function)(*args)

    assert fake.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_text_reraises_final_sdk_exception_after_three_attempts(gemini_service):
    final_error = gemini_api_error(503)
    fake = FakeClient([gemini_api_error(503), gemini_api_error(503), final_error])
    gemini_service.client = fake

    with pytest.raises(genai_errors.ServerError) as caught:
        await gemini_service.process_expense_text("coffee")

    assert caught.value is final_error
    assert fake.aio.models.generate_content.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    gemini_api_error(400), gemini_api_error(600), ValueError("invalid"), TypeError("bug"), RuntimeError("bug"),
    asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(),
])
async def test_non_transient_and_process_control_errors_are_not_retried(gemini_service, error):
    fake = FakeClient([error])
    gemini_service.client = fake

    with pytest.raises(type(error)):
        await gemini_service.process_expense_text("coffee")

    assert fake.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
async def test_invalid_response_is_not_retried(gemini_service):
    fake = FakeClient([SimpleNamespace(text="invalid")])
    gemini_service.client = fake

    with pytest.raises(gemini_service.GeminiResponseError):
        await gemini_service.process_expense_text("coffee")

    assert fake.aio.models.generate_content.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("magic", "mime"), [
    (b"\xff\xd8\xffreceipt", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\nreceipt", "image/png"),
    (b"RIFFxxxxWEBPreceipt", "image/webp"),
    (b"unrecognised", "image/jpeg"),
])
async def test_image_constructs_part_from_exact_bytes_and_detected_mime(gemini_service, monkeypatch, tmp_path, magic, mime):
    image = tmp_path / "receipt.bin"
    image.write_bytes(magic)
    image_part = object()
    from_bytes = Mock(return_value=image_part)
    monkeypatch.setattr(gemini_service.types.Part, "from_bytes", from_bytes)
    fake = FakeClient([SimpleNamespace(text='{}')])
    gemini_service.client = fake

    await gemini_service.process_expense_image(str(image))

    from_bytes.assert_called_once_with(mime_type=mime, data=magic)
    assert fake.aio.models.generate_content.await_args.kwargs["contents"][0] is image_part


@pytest.mark.asyncio
async def test_image_prompt_and_sdk_call_use_caption_and_context(gemini_service, monkeypatch, tmp_path):
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"\xff\xd8\xffx")
    monkeypatch.setattr(gemini_service, "get_current_date", lambda: ("2026-07-18", "Saturday"))
    monkeypatch.setattr(gemini_service.types.Part, "from_bytes", Mock(return_value="part"))
    fake = FakeClient([SimpleNamespace(text='{}')])
    gemini_service.client = fake

    await gemini_service.process_expense_image(str(image), "Split bill", "EUR", ["Meals"], [{"keyword": "dinner", "category": "Meals"}])

    call = fake.aio.models.generate_content.await_args
    assert call.kwargs["model"] == "test-gemini"
    assert call.kwargs["config"] is gemini_service.expense_config
    assert call.kwargs["contents"][0] == "part"
    prompt = call.kwargs["contents"][1]
    for value in ("Split bill", "2026-07-18", "Saturday", "EUR", "Meals", "'dinner' -> Meals", "MUST use"):
        assert value in prompt


@pytest.mark.asyncio
async def test_image_prompt_uses_no_caption_when_caption_is_empty(gemini_service, monkeypatch, tmp_path):
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"\xff\xd8\xffx")
    monkeypatch.setattr(gemini_service.types.Part, "from_bytes", Mock(return_value="part"))
    fake = FakeClient([SimpleNamespace(text='{}')])
    gemini_service.client = fake

    await gemini_service.process_expense_image(str(image))

    assert "No caption provided" in fake.aio.models.generate_content.await_args.kwargs["contents"][1]


@pytest.mark.asyncio
async def test_missing_image_is_not_retried_or_sent_to_sdk(gemini_service):
    fake = FakeClient([])
    gemini_service.client = fake

    with pytest.raises(FileNotFoundError):
        await gemini_service.process_expense_image("does-not-exist.jpg")

    fake.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_local_image_os_error_is_not_retried(gemini_service, monkeypatch):
    open_file = Mock(side_effect=PermissionError("denied"))
    monkeypatch.setattr("builtins.open", open_file)
    fake = FakeClient([])
    gemini_service.client = fake

    with pytest.raises(PermissionError):
        await gemini_service.process_expense_image("unreadable.jpg")

    open_file.assert_called_once_with("unreadable.jpg", "rb")
    fake.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_refinement_preserves_original_details_and_feedback(gemini_service):
    fake = FakeClient([SimpleNamespace(text='{"price": 10}')])
    gemini_service.client = fake

    assert await gemini_service.refine_expense_details({"price": 5, "category": "Food"}, "Make it 10") == '{"price": 10}'
    call = fake.aio.models.generate_content.await_args
    assert call.kwargs["model"] == "test-gemini"
    assert call.kwargs["config"] is gemini_service.expense_config
    prompt = call.kwargs["contents"]
    for value in ("'price': 5", "Make it 10", "keeping other details unchanged"):
        assert value in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("function,args", [
    ("process_expense_image", ("missing.jpg",)),
    ("refine_expense_details", ({}, "feedback")),
])
async def test_public_functions_reject_malformed_responses(gemini_service, monkeypatch, tmp_path, function, args):
    if function == "process_expense_image":
        image = tmp_path / "receipt.jpg"
        image.write_bytes(b"\xff\xd8\xffx")
        monkeypatch.setattr(gemini_service.types.Part, "from_bytes", Mock(return_value="part"))
        args = (str(image),)
    fake = FakeClient([SimpleNamespace(text="[]")])
    gemini_service.client = fake

    with pytest.raises(gemini_service.GeminiResponseError):
        await getattr(gemini_service, function)(*args)

    assert fake.aio.models.generate_content.await_count == 1
