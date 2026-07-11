import unittest
from datetime import date

from handlers.export_calendar import (
    CalendarCallbackError,
    build_calendar,
    parse_calendar_callback,
)


class ExportCalendarTests(unittest.TestCase):
    def test_february_2024_is_monday_first_and_contains_29_days(self):
        markup = build_calendar(date(2024, 2, 1), date(2020, 1, 1), date(2024, 2, 29))
        rows = markup.inline_keyboard
        self.assertEqual([button.text for button in rows[1]], ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"])
        selectable = [button.text for row in rows for button in row if button.callback_data.startswith("xcal:d:")]
        self.assertEqual(selectable, [str(day) for day in range(1, 30)])

    def test_navigation_crosses_year_boundary_and_hides_future_month(self):
        december = build_calendar(date(2025, 12, 1), date(2020, 1, 1), date(2026, 1, 15))
        nav = december.inline_keyboard[-1]
        self.assertEqual(nav[0].callback_data, "xcal:n:2025-11-01")
        self.assertEqual(nav[-1].callback_data, "xcal:n:2026-01-01")

        january = build_calendar(date(2026, 1, 1), date(2020, 1, 1), date(2026, 1, 15))
        self.assertEqual(january.inline_keyboard[-1][-1].callback_data, "xcal:i")

    def test_navigation_hides_previous_month_at_minimum(self):
        minimum = date(2026, 1, 10)
        maximum = date(2026, 7, 11)
        january = build_calendar(date(2026, 1, 1), minimum, maximum)
        self.assertEqual(january.inline_keyboard[-1][0].callback_data, "xcal:i")

    def test_parser_rejects_navigation_before_minimum_month(self):
        minimum = date(2026, 1, 10)
        maximum = date(2026, 7, 11)
        with self.assertRaises(CalendarCallbackError):
            parse_calendar_callback("xcal:n:2025-12-01", minimum, maximum)

    def test_days_outside_range_are_inert(self):
        markup = build_calendar(date(2026, 1, 1), date(2026, 1, 10), date(2026, 1, 15))
        callbacks = {
            button.text: button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.text.isdigit()
        }
        self.assertEqual(callbacks["9"], "xcal:i")
        self.assertEqual(callbacks["10"], "xcal:d:2026-01-10")
        self.assertEqual(callbacks["15"], "xcal:d:2026-01-15")
        self.assertEqual(callbacks["16"], "xcal:i")

    def test_parser_accepts_valid_navigation_and_selection(self):
        minimum = date(2024, 1, 1)
        maximum = date(2026, 7, 11)
        self.assertEqual(
            parse_calendar_callback("xcal:n:2025-12-01", minimum, maximum).kind,
            "navigate",
        )
        selected = parse_calendar_callback("xcal:d:2026-07-11", minimum, maximum)
        self.assertEqual((selected.kind, selected.value), ("select", maximum))

    def test_parser_rejects_navigation_date_that_is_not_month_start(self):
        with self.assertRaises(CalendarCallbackError):
            parse_calendar_callback("xcal:n:2026-01-15", date(2026, 1, 1), date(2026, 7, 11))

    def test_parser_rejects_malformed_and_out_of_range_callbacks(self):
        minimum = date(2026, 1, 10)
        maximum = date(2026, 7, 11)
        for payload in ("xcal:i", "xcal:d:nope", "xcal:d:2026-01-09", "xcal:d:2026-07-12", "other:d:2026-01-10"):
            with self.subTest(payload=payload), self.assertRaises(CalendarCallbackError):
                parse_calendar_callback(payload, minimum, maximum)


if __name__ == "__main__":
    unittest.main()
