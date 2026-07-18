"""Small behavior-shaped Telegram objects for isolated handler tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock


class TelegramScenario:
    """Build the Telegram objects a handler receives without an application."""

    def __init__(
        self,
        *,
        text=None,
        callback_data=None,
        username="expense_user",
        user_id=101,
        chat_id=202,
        reply_to_text=None,
        photos=None,
        caption=None,
        message_id=1,
    ):
        self.message = SimpleNamespace(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_to_message=(SimpleNamespace(text=reply_to_text) if reply_to_text is not None else None),
            reply_text=AsyncMock(),
            edit_text=AsyncMock(),
            photo=photos or [],
            caption=caption,
        )
        self.callback_query = SimpleNamespace(
            data=callback_data,
            message=self.message,
            answer=AsyncMock(),
        )
        self.bot = SimpleNamespace(
            send_message=AsyncMock(),
            send_document=AsyncMock(),
            edit_message_text=AsyncMock(),
            delete_message=AsyncMock(),
        )
        self.context = SimpleNamespace(bot=self.bot, user_data={})
        self.update = SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id, username=username),
            effective_chat=SimpleNamespace(id=chat_id),
            message=self.message,
            callback_query=self.callback_query,
        )
