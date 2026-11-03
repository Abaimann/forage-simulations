"""Unit tests for the timestamp normalization utilities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from iiot_telemetry.application.timestamp import (
    ensure_utc_now,
    floor_to_second,
    iso8601,
    normalize_timestamp,
    parse_timestamp,
    seconds_between,
    shift,
    to_utc,
)
from iiot_telemetry.domain.exceptions import NormalizationError


class TestToUtc:
    """Behaviour of the :func:`to_utc` helper."""

    def test_naive_datetime_is_assumed_utc(self) -> None:
        result = to_utc(datetime(2024, 5, 1, 8, 0, 0))
        assert result.tzinfo is timezone.utc
        assert result.hour == 8

    def test_aware_datetime_is_converted(self) -> None:
        from datetime import timedelta

        source = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        result = to_utc(source)
        assert result.hour == 6
        assert result.tzinfo is timezone.utc


class TestParseTimestamp:
    """Behaviour of the multi-format timestamp parser."""

    def test_parses_iso_with_z_suffix(self) -> None:
        result = parse_timestamp("2024-05-01T08:00:00Z")
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_iso_with_offset(self) -> None:
        result = parse_timestamp("2024-05-01T10:00:00+02:00")
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_iso_with_fractional_seconds(self) -> None:
        result = parse_timestamp("2024-05-01T08:00:00.500000+00:00")
        assert result.microsecond == 500000

    def test_parses_naive_iso_as_utc(self) -> None:
        result = parse_timestamp("2024-05-01T08:00:00")
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_space_separated_datetime(self) -> None:
        result = parse_timestamp("2024-05-01 08:00:00")
        assert result.hour == 8

    def test_parses_date_only(self) -> None:
        result = parse_timestamp("2024-05-01")
        assert (result.year, result.month, result.day) == (2024, 5, 1)

    def test_parses_slash_separated_datetime(self) -> None:
        result = parse_timestamp("2024/05/01 08:00:00")
        assert result.hour == 8

    def test_parses_day_first_slash_format(self) -> None:
        result = parse_timestamp("01/05/2024 08:00:00")
        assert (result.day, result.month) == (1, 5)

    def test_ambiguous_slash_date_defaults_to_day_first(self) -> None:
        result = parse_timestamp("05/01/2024 08:00:00")
        assert (result.day, result.month) == (5, 1)

    def test_ambiguous_slash_date_can_be_read_month_first(self) -> None:
        result = parse_timestamp("05/01/2024 08:00:00", day_first=False)
        assert (result.month, result.day) == (5, 1)

    def test_unambiguous_day_greater_than_twelve_is_day_first(self) -> None:
        result = parse_timestamp("25/12/2024 08:00:00")
        assert (result.day, result.month) == (25, 12)

    def test_unambiguous_second_component_greater_than_twelve_is_month_first(self) -> None:
        result = parse_timestamp("12/25/2024 08:00:00")
        assert (result.month, result.day) == (12, 25)

    def test_year_first_slash_format(self) -> None:
        result = parse_timestamp("2024/05/01 08:00:00")
        assert (result.year, result.month, result.day) == (2024, 5, 1)

    def test_numeric_date_with_fractional_seconds(self) -> None:
        result = parse_timestamp("01/05/2024 08:00:00.250")
        assert result.microsecond == 250000

    def test_numeric_date_without_year_uses_2000(self) -> None:
        result = parse_timestamp("01/05 08:00:00")
        assert result.year == 2000

    def test_invalid_numeric_date_falls_through(self) -> None:
        with pytest.raises(NormalizationError):
            parse_timestamp("45/45/2024")

    def test_two_component_date_with_day_greater_than_twelve(self) -> None:
        result = parse_timestamp("25/05 08:00:00")
        assert (result.day, result.month, result.year) == (25, 5, 2000)

    def test_two_component_date_with_month_greater_than_twelve(self) -> None:
        result = parse_timestamp("05/25 08:00:00")
        assert (result.month, result.day, result.year) == (5, 25, 2000)

    def test_two_component_date_can_be_read_month_first(self) -> None:
        result = parse_timestamp("05/25 08:00:00", day_first=False)
        assert (result.month, result.day) == (5, 25)

    def test_two_component_date_day_first_default(self) -> None:
        # Both components are <= 12, so the day_first policy decides.
        result = parse_timestamp("05/06 08:00:00")
        assert (result.day, result.month) == (5, 6)

    def test_two_component_date_month_first_policy(self) -> None:
        result = parse_timestamp("05/06 08:00:00", day_first=False)
        assert (result.month, result.day) == (5, 6)

    def test_two_digit_year_is_expanded(self) -> None:
        result = parse_timestamp("01/05/24 08:00:00")
        assert result.year == 2024
        assert (result.day, result.month) == (1, 5)

    def test_two_digit_year_with_day_greater_than_twelve(self) -> None:
        result = parse_timestamp("25/05/24 08:00:00")
        assert result.year == 2024
        assert (result.day, result.month) == (25, 5)

    def test_two_digit_year_with_month_greater_than_twelve(self) -> None:
        result = parse_timestamp("05/25/24 08:00:00")
        assert (result.month, result.day) == (5, 25)

    def test_two_digit_year_can_be_read_month_first(self) -> None:
        result = parse_timestamp("05/25/24 08:00:00", day_first=False)
        assert (result.month, result.day) == (5, 25)

    def test_ambiguous_two_digit_year_month_first(self) -> None:
        result = parse_timestamp("05/06/24 08:00:00", day_first=False)
        assert (result.month, result.day) == (5, 6)
        assert result.year == 2024

    def test_invalid_hour_is_rejected(self) -> None:
        # The regex accepts the shape, but the hour itself is out of range.
        with pytest.raises(NormalizationError):
            parse_timestamp("01/05/2024 25:00:00")

    def test_parses_day_first_dash_format(self) -> None:
        result = parse_timestamp("01-05-2024 08:00:00")
        assert (result.day, result.month) == (1, 5)

    def test_parses_epoch_seconds(self) -> None:
        result = parse_timestamp(1714550400)
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_epoch_milliseconds(self) -> None:
        result = parse_timestamp(1714550400000)
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_epoch_microseconds(self) -> None:
        result = parse_timestamp(1714550400000000)
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_epoch_nanoseconds(self) -> None:
        result = parse_timestamp(1714550400000000000)
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_numeric_string_as_epoch(self) -> None:
        result = parse_timestamp("1714550400")
        assert result == datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_parses_datetime_instance(self) -> None:
        source = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert parse_timestamp(source) == source

    def test_datetime_instance_is_converted_to_utc(self) -> None:
        from datetime import timedelta

        source = datetime(2024, 5, 1, 10, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert parse_timestamp(source).hour == 8

    def test_lowercase_z_suffix_is_supported(self) -> None:
        result = parse_timestamp("2024-05-01T08:00:00z")
        assert result.hour == 8

    @pytest.mark.parametrize(
        "raw",
        ["", "   ", "not-a-date", "2024-13-45", "unknown", "12:99:99"],
    )
    def test_invalid_strings_raise(self, raw: str) -> None:
        with pytest.raises(NormalizationError):
            parse_timestamp(raw)

    def test_boolean_raises(self) -> None:
        with pytest.raises(NormalizationError):
            parse_timestamp(True)

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(NormalizationError):
            parse_timestamp(["2024-05-01"])

    def test_out_of_range_epoch_raises(self) -> None:
        with pytest.raises(NormalizationError):
            parse_timestamp(1e30)

    def test_normalize_timestamp_is_an_alias(self) -> None:
        assert normalize_timestamp("2024-05-01T08:00:00Z") == datetime(
            2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc
        )


class TestHelpers:
    """Small helper utilities of the timestamp module."""

    def test_iso8601_renders_utc(self) -> None:
        assert iso8601(datetime(2024, 5, 1, 8, 0, 0)) == "2024-05-01T08:00:00+00:00"

    def test_seconds_between_returns_delta(self) -> None:
        start = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=90)
        assert seconds_between(start, end) == 90.0

    def test_seconds_between_can_be_negative(self) -> None:
        start = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert seconds_between(end := start + timedelta(seconds=10), start) == -10.0

    def test_floor_to_second_truncates_microseconds(self) -> None:
        value = datetime(2024, 5, 1, 8, 0, 0, 123456, tzinfo=timezone.utc)
        assert floor_to_second(value).microsecond == 0

    def test_ensure_utc_now_is_timezone_aware(self) -> None:
        assert ensure_utc_now().tzinfo is timezone.utc

    def test_shift_moves_forward(self) -> None:
        start = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert shift(start, 60).minute == 1
