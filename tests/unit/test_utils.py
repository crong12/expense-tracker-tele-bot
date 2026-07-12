from datetime import datetime

import pytest

import utils


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("groceries", "Groceries"),
        ("DINING OUT", "Dining Out"),
        ("  mixed   spacing  ", "Mixed Spacing"),
        ("", ""),
    ],
)
def test_to_title_case_normalizes_words(value, expected):
    assert utils.to_title_case(value) == expected


def test_get_current_date_uses_the_module_clock(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def today(cls):
            return cls(2026, 7, 12, 23, 59, 59)

    monkeypatch.setattr(utils, "datetime", FrozenDateTime)

    assert utils.get_current_date() == ("2026-07-12", "Sunday")
