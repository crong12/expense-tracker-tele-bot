import calendar
from dataclasses import dataclass
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CALENDAR_PREFIX = "xcal"
INERT_CALLBACK = f"{CALENDAR_PREFIX}:i"
WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")


class CalendarCallbackError(ValueError):
    """Raised when calendar callback data is invalid or out of range."""


@dataclass(frozen=True)
class CalendarAction:
    kind: str
    value: date


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year, month_zero_based = divmod(month_index, 12)
    return date(year, month_zero_based + 1, 1)


def _button(text: str, callback_data: str = INERT_CALLBACK) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=callback_data)


def build_calendar(view_month: date, min_date: date, max_date: date) -> InlineKeyboardMarkup:
    if min_date > max_date:
        raise ValueError("min_date must not be after max_date")
    view_month = _month_start(view_month)
    if view_month > _month_start(max_date):
        raise ValueError("view_month must not be after max_date's month")

    rows = [[_button(view_month.strftime("%B %Y"))], [_button(day) for day in WEEKDAYS]]
    month_calendar = calendar.Calendar(firstweekday=calendar.MONDAY)
    for week in month_calendar.monthdatescalendar(view_month.year, view_month.month):
        row = []
        for value in week:
            if value.month != view_month.month:
                row.append(_button(" "))
            elif min_date <= value <= max_date:
                row.append(_button(str(value.day), f"{CALENDAR_PREFIX}:d:{value.isoformat()}"))
            else:
                row.append(_button(str(value.day)))
        rows.append(row)

    previous_month = _shift_month(view_month, -1)
    next_month = _shift_month(view_month, 1)
    previous = (
        _button("‹", f"{CALENDAR_PREFIX}:n:{previous_month.isoformat()}")
        if previous_month >= _month_start(min_date)
        else _button(" ")
    )
    next_button = (
        _button("›", f"{CALENDAR_PREFIX}:n:{next_month.isoformat()}")
        if next_month <= _month_start(max_date)
        else _button(" ")
    )
    rows.append([previous, _button(" "), next_button])
    return InlineKeyboardMarkup(rows)


def parse_calendar_callback(data: str, min_date: date, max_date: date) -> CalendarAction:
    try:
        prefix, action, raw_date = data.split(":", 2)
        value = date.fromisoformat(raw_date)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CalendarCallbackError("Invalid calendar action") from exc
    if prefix != CALENDAR_PREFIX or action not in {"n", "d"}:
        raise CalendarCallbackError("Invalid calendar action")
    if action == "n":
        if value.day != 1:
            raise CalendarCallbackError("Navigation date must be a month start")
        if not _month_start(min_date) <= value <= _month_start(max_date):
            raise CalendarCallbackError("Month is outside the allowed range")
        return CalendarAction("navigate", value)
    if not min_date <= value <= max_date:
        raise CalendarCallbackError("Date is outside the allowed range")
    return CalendarAction("select", value)
