"""Unit tests for the domain models and their validation rules."""

from __future__ import annotations

import json
import math

import pytest

from jpm_perspective_grid.core.errors import TickValidationError
from jpm_perspective_grid.core.models import (
    KIND_PAIR,
    KIND_SYMBOL,
    Band,
    GridRow,
    Quote,
    Tick,
    epoch_ms_to_iso,
    normalize_symbol,
)


class TestNormalizeSymbol:
    def test_trims_and_upper_cases(self):
        assert normalize_symbol("  aapl ") == "AAPL"

    def test_rejects_blank(self):
        with pytest.raises(TickValidationError):
            normalize_symbol("   ")

    def test_rejects_none(self):
        with pytest.raises(TickValidationError):
            normalize_symbol(None)

    def test_rejects_non_string(self):
        with pytest.raises(TickValidationError):
            normalize_symbol(42)

    def test_error_mentions_field(self):
        with pytest.raises(TickValidationError) as excinfo:
            normalize_symbol("")
        assert excinfo.value.field == "stock"


class TestTickValidation:
    def test_valid_tick_is_accepted(self, make_tick):
        tick = make_tick()
        assert tick.stock == "AAPL"
        assert tick.top_ask_price == 100.0
        assert tick.top_bid_price == 99.0
        assert tick.timestamp == 1_700_000_000_000

    def test_stock_is_normalised(self):
        tick = Tick(" msft ", 10.0, 9.0, 1)
        assert tick.stock == "MSFT"

    @pytest.mark.parametrize("price", [0.0, -1.0, -0.01])
    def test_non_positive_ask_is_rejected(self, price):
        with pytest.raises(TickValidationError):
            Tick("AAPL", price, 0.5, 1)

    @pytest.mark.parametrize("price", [0.0, -5.0])
    def test_non_positive_bid_is_rejected(self, price):
        with pytest.raises(TickValidationError):
            Tick("AAPL", 100.0, price, 1)

    def test_crossed_market_is_rejected(self):
        with pytest.raises(TickValidationError) as excinfo:
            Tick("AAPL", 99.0, 100.0, 1)
        assert "crossed" in str(excinfo.value)

    def test_equal_bid_and_ask_is_allowed(self):
        tick = Tick("AAPL", 100.0, 100.0, 1)
        assert tick.spread == 0.0

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_prices_are_rejected(self, value):
        with pytest.raises(TickValidationError):
            Tick("AAPL", value, 1.0, 1)

    def test_negative_timestamp_is_rejected(self):
        with pytest.raises(TickValidationError):
            Tick("AAPL", 100.0, 99.0, -1)

    def test_boolean_price_is_rejected(self):
        with pytest.raises(TickValidationError):
            Tick("AAPL", True, 99.0, 1)

    def test_string_price_is_rejected(self):
        with pytest.raises(TickValidationError):
            Tick("AAPL", "100.0", 99.0, 1)

    def test_float_timestamp_is_truncated_to_int(self):
        tick = Tick("AAPL", 100.0, 99.0, 1.9)
        assert tick.timestamp == 1


class TestTickDerivedProperties:
    def test_mid_price(self, make_tick):
        assert make_tick(ask=101.0, bid=99.0).mid_price == 100.0

    def test_spread(self, make_tick):
        assert make_tick(ask=101.0, bid=99.0).spread == 2.0

    def test_spread_bps(self, make_tick):
        tick = make_tick(ask=101.0, bid=99.0)
        assert tick.spread_bps == pytest.approx(200.0)

    def test_spread_bps_is_zero_for_degenerate_book(self, make_tick):
        tick = make_tick(ask=100.0, bid=100.0)
        assert tick.spread_bps == 0.0


class TestTickSerialization:
    def test_from_dict_round_trip(self, raw_tick_payload):
        payload = raw_tick_payload()
        tick = Tick.from_dict(payload)
        assert tick.to_dict() == payload

    def test_from_dict_reports_missing_field(self, raw_tick_payload):
        payload = raw_tick_payload()
        del payload["timestamp"]
        with pytest.raises(TickValidationError) as excinfo:
            Tick.from_dict(payload)
        assert excinfo.value.field == "timestamp"

    def test_from_dict_rejects_non_mapping(self):
        with pytest.raises(TickValidationError):
            Tick.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]

    def test_from_json_parses_valid_document(self, raw_tick_payload):
        payload = raw_tick_payload()
        tick = Tick.from_json(json.dumps(payload))
        assert tick.stock == "AAPL"

    def test_from_json_rejects_garbage(self):
        with pytest.raises(TickValidationError):
            Tick.from_json("{not json")

    def test_from_json_rejects_non_object(self):
        with pytest.raises(TickValidationError):
            Tick.from_json("[1, 2, 3]")

    def test_to_json_is_compact(self, make_tick):
        rendered = make_tick().to_json()
        assert " " not in rendered
        assert json.loads(rendered)["stock"] == "AAPL"


class TestQuote:
    def test_from_tick(self, make_tick):
        quote = Quote.from_tick(make_tick(ask=101.0, bid=99.0))
        assert quote.mid_price == 100.0
        assert quote.spread == 2.0
        assert quote.stock == "AAPL"


class TestBand:
    def test_contains_is_inclusive(self):
        band = Band(1.0, 2.0, 1.5, 0.1, 10)
        assert band.contains(1.0)
        assert band.contains(2.0)
        assert band.contains(1.5)

    def test_breaches_is_strict(self):
        band = Band(1.0, 2.0, 1.5, 0.1, 10)
        assert not band.breaches(1.0)
        assert not band.breaches(2.0)
        assert band.breaches(0.999)
        assert band.breaches(2.001)

    def test_half_width(self):
        band = Band(1.0, 2.0, 1.5, 0.1, 10)
        assert band.half_width == pytest.approx(0.5)


class TestGridRow:
    def test_to_dict_shape(self):
        row = GridRow(
            stock="AAPL",
            kind=KIND_SYMBOL,
            price=100.0,
            ratio=1.0,
            upper_bound=1.01,
            lower_bound=0.99,
            trigger_alert=True,
            timestamp=1_700_000_000_000,
        )
        payload = row.to_dict()
        assert set(payload) == {
            "stock",
            "kind",
            "price",
            "ratio",
            "upper_bound",
            "lower_bound",
            "trigger_alert",
            "timestamp",
        }
        assert payload["trigger_alert"] is True
        assert payload["timestamp"] == "2023-11-14T22:13:20Z"

    def test_pair_kind_constant(self):
        assert KIND_PAIR == "pair"
        assert KIND_SYMBOL == "symbol"

    def test_to_json_round_trip(self):
        row = GridRow(
            stock="AAPL/MSFT",
            kind=KIND_PAIR,
            price=100.0,
            ratio=0.5,
            upper_bound=0.51,
            lower_bound=0.49,
            trigger_alert=False,
            timestamp=1,
        )
        assert json.loads(row.to_json())["stock"] == "AAPL/MSFT"


class TestEpochConversion:
    def test_iso_format(self):
        assert epoch_ms_to_iso(0) == "1970-01-01T00:00:00Z"

    def test_is_utc(self):
        rendered = epoch_ms_to_iso(1_700_000_000_000)
        assert rendered.endswith("Z")
        assert "T" in rendered

    def test_round_trip_is_sane(self):
        assert epoch_ms_to_iso(1_700_000_000_000).startswith("2023-11-14T22:13:20")
        assert math.isclose(1_700_000_000_000 / 1000.0, 1_700_000_000.0)
