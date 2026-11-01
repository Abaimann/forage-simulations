"""Unit tests for the stock price data feed analysis utility (Task 1).

Run with:

    python -m unittest unit_test -v
    # or
    python unit_test.py
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from client import (
    StockPriceError,
    StockPriceFeed,
    StockQuote,
    ZeroDenominatorError,
    compute_stock_price,
    compute_stock_price_ratio,
    parse_stock_quote,
    parse_stock_quotes,
    read_quotes,
    safe_compute_stock_price_ratio,
)


class TestComputeStockPrice(unittest.TestCase):
    """Requirement 2: the stock price is (top_bid_price + top_ask_price) / 2."""

    def test_price_is_midpoint_of_bid_and_ask(self):
        quote = StockQuote("AAPL", 100.0, 102.0, "2024-01-01T00:00:00")
        self.assertEqual(compute_stock_price(quote), 101.0)

    def test_price_with_non_round_numbers(self):
        quote = StockQuote("MSFT", 10.25, 10.75)
        self.assertAlmostEqual(compute_stock_price(quote), 10.5)

    def test_price_with_identical_bid_and_ask(self):
        quote = StockQuote("TSLA", 250.0, 250.0)
        self.assertEqual(compute_stock_price(quote), 250.0)

    def test_price_with_zero_bid_and_ask(self):
        quote = StockQuote("ZERO", 0.0, 0.0)
        self.assertEqual(compute_stock_price(quote), 0.0)

    def test_price_with_negative_bid_and_ask(self):
        quote = StockQuote("NEG", -10.0, -6.0)
        self.assertAlmostEqual(compute_stock_price(quote), -8.0)

    def test_price_property_matches_function(self):
        quote = StockQuote("GOOG", 150.0, 170.0)
        self.assertEqual(quote.stock_price, compute_stock_price(quote))
        self.assertEqual(quote.stock_price, 160.0)

    def test_price_avoids_floating_point_noise(self):
        quote = StockQuote("NOISE", 0.1, 0.2)
        self.assertEqual(compute_stock_price(quote), 0.15)

    def test_price_rejects_non_quote_input(self):
        bad_input: Any = {"stock": "AAPL", "top_bid_price": 1.0, "top_ask_price": 2.0}
        with self.assertRaises(StockPriceError):
            compute_stock_price(bad_input)

    def test_spread_is_ask_minus_bid(self):
        quote = StockQuote("AAPL", 100.0, 102.0)
        self.assertEqual(quote.spread, 2.0)


class TestComputeStockPriceRatio(unittest.TestCase):
    """Requirement 3: ratio of two stock prices, avoiding divide-by-zero."""

    def test_ratio_of_two_prices(self):
        self.assertAlmostEqual(compute_stock_price_ratio(100.0, 50.0), 2.0)

    def test_ratio_less_than_one(self):
        self.assertAlmostEqual(compute_stock_price_ratio(50.0, 100.0), 0.5)

    def test_ratio_of_equal_prices_is_one(self):
        self.assertEqual(compute_stock_price_ratio(42.0, 42.0), 1.0)

    def test_ratio_raises_domain_error_for_zero_denominator(self):
        with self.assertRaises(ZeroDenominatorError):
            compute_stock_price_ratio(100.0, 0.0)

    def test_ratio_error_is_not_a_zero_division_error(self):
        # The point of requirement 3: no raw ZeroDivisionError escapes.
        with self.assertRaises(ZeroDenominatorError) as ctx:
            compute_stock_price_ratio(100.0, 0.0)
        self.assertNotIsInstance(ctx.exception, ZeroDivisionError)
        self.assertIsInstance(ctx.exception, ValueError)

    def test_ratio_with_zero_numerator(self):
        self.assertEqual(compute_stock_price_ratio(0.0, 10.0), 0.0)

    def test_safe_ratio_returns_default_for_zero_denominator(self):
        self.assertEqual(safe_compute_stock_price_ratio(100.0, 0.0, default=0.0), 0.0)
        self.assertIsNone(safe_compute_stock_price_ratio(100.0, 0.0))

    def test_safe_ratio_normal_case(self):
        result = safe_compute_stock_price_ratio(3.0, 2.0)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(cast(float, result), 1.5)

    def test_ratio_of_negative_prices(self):
        self.assertAlmostEqual(compute_stock_price_ratio(-10.0, -5.0), 2.0)

    def test_ratio_of_two_computed_prices(self):
        aapl = StockQuote("AAPL", 100.0, 102.0)
        msft = StockQuote("MSFT", 50.0, 60.0)
        ratio = compute_stock_price_ratio(
            compute_stock_price(aapl), compute_stock_price(msft)
        )
        self.assertAlmostEqual(ratio, 101.0 / 55.0)

    def test_ratio_precision_is_rounded(self):
        self.assertEqual(compute_stock_price_ratio(1.0, 3.0), 0.3333333333)


class TestParseStockQuote(unittest.TestCase):
    """Requirement 1: parse stock, top_bid_price, top_ask_price, timestamp."""

    def test_parse_full_record(self):
        quote = parse_stock_quote(
            {
                "stock": "AAPL",
                "top_bid_price": 100.0,
                "top_ask_price": 102.0,
                "timestamp": "2024-01-01T09:30:00",
            }
        )
        self.assertEqual(quote.stock, "AAPL")
        self.assertEqual(quote.top_bid_price, 100.0)
        self.assertEqual(quote.top_ask_price, 102.0)
        self.assertEqual(quote.timestamp, "2024-01-01T09:30:00")

    def test_parse_string_prices(self):
        quote = parse_stock_quote(
            {"stock": "AAPL", "top_bid_price": "100.5", "top_ask_price": "101.5"}
        )
        self.assertEqual(quote.top_bid_price, 100.5)
        self.assertEqual(quote.top_ask_price, 101.5)

    def test_parse_integer_prices(self):
        quote = parse_stock_quote(
            {"stock": "AAPL", "top_bid_price": 100, "top_ask_price": 102}
        )
        self.assertIsInstance(quote.top_bid_price, float)
        self.assertEqual(quote.stock_price, 101.0)

    def test_parse_price_with_currency_symbol(self):
        quote = parse_stock_quote(
            {"stock": "AAPL", "top_bid_price": "$100.00", "top_ask_price": "$102.00"}
        )
        self.assertEqual(quote.top_bid_price, 100.0)

    def test_parse_accepts_field_aliases(self):
        quote = parse_stock_quote(
            {"symbol": "AAPL", "bid_price": 100.0, "ask_price": 102.0, "time": "2024-01-01"}
        )
        self.assertEqual(quote.stock, "AAPL")
        self.assertEqual(quote.stock_price, 101.0)

    def test_parse_missing_stock_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote({"top_bid_price": 100.0, "top_ask_price": 102.0})

    def test_parse_missing_bid_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote({"stock": "AAPL", "top_ask_price": 102.0})

    def test_parse_missing_ask_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote({"stock": "AAPL", "top_bid_price": 100.0})

    def test_parse_non_numeric_price_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote(
                {"stock": "AAPL", "top_bid_price": "abc", "top_ask_price": 102.0}
            )

    def test_parse_empty_price_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote(
                {"stock": "AAPL", "top_bid_price": "", "top_ask_price": 102.0}
            )

    def test_parse_none_price_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote(
                {"stock": "AAPL", "top_bid_price": None, "top_ask_price": 102.0}
            )

    def test_parse_boolean_price_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote(
                {"stock": "AAPL", "top_bid_price": True, "top_ask_price": 102.0}
            )

    def test_parse_nan_price_raises(self):
        with self.assertRaises(StockPriceError):
            parse_stock_quote(
                {"stock": "AAPL", "top_bid_price": float("nan"), "top_ask_price": 102.0}
            )

    def test_parse_non_mapping_raises(self):
        bad_record: Any = "not-a-record"
        with self.assertRaises(StockPriceError):
            parse_stock_quote(bad_record)

    def test_parse_timestamp_optional(self):
        quote = parse_stock_quote(
            {"stock": "AAPL", "top_bid_price": 1.0, "top_ask_price": 2.0}
        )
        self.assertIsNone(quote.timestamp)
        self.assertIsNone(quote.parsed_timestamp)

    def test_parse_timestamp_iso(self):
        quote = parse_stock_quote(
            {
                "stock": "AAPL",
                "top_bid_price": 1.0,
                "top_ask_price": 2.0,
                "timestamp": "2024-01-01T09:30:00",
            }
        )
        parsed = quote.parsed_timestamp
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.year, 2024)
        self.assertEqual(parsed.month, 1)
        self.assertEqual(parsed.day, 1)

    def test_parse_timestamp_unparseable_returns_none(self):
        quote = parse_stock_quote(
            {
                "stock": "AAPL",
                "top_bid_price": 1.0,
                "top_ask_price": 2.0,
                "timestamp": "not-a-date",
            }
        )
        self.assertIsNone(quote.parsed_timestamp)

    def test_parse_quotes_list(self):
        quotes = parse_stock_quotes(
            [
                {"stock": "AAPL", "top_bid_price": 100.0, "top_ask_price": 102.0},
                {"stock": "MSFT", "top_bid_price": 50.0, "top_ask_price": 60.0},
            ]
        )
        self.assertEqual(len(quotes), 2)
        self.assertEqual([q.stock for q in quotes], ["AAPL", "MSFT"])

    def test_parse_quotes_reports_failing_index(self):
        with self.assertRaises(StockPriceError) as ctx:
            parse_stock_quotes(
                [
                    {"stock": "AAPL", "top_bid_price": 100.0, "top_ask_price": 102.0},
                    {"stock": "MSFT", "top_bid_price": "oops", "top_ask_price": 60.0},
                ]
            )
        self.assertIn("index 1", str(ctx.exception))

    def test_parse_quotes_empty_list(self):
        self.assertEqual(parse_stock_quotes([]), [])


class TestStockPriceFeed(unittest.TestCase):
    """Feed-level helpers: lookup, ratios and file reading."""

    def setUp(self):
        self.feed = StockPriceFeed.from_records(
            [
                {
                    "stock": "AAPL",
                    "top_bid_price": 100.0,
                    "top_ask_price": 102.0,
                    "timestamp": "2024-01-01T09:30:00",
                },
                {
                    "stock": "MSFT",
                    "top_bid_price": 50.0,
                    "top_ask_price": 60.0,
                    "timestamp": "2024-01-01T09:31:00",
                },
                {
                    "stock": "AAPL",
                    "top_bid_price": 110.0,
                    "top_ask_price": 114.0,
                    "timestamp": "2024-01-01T09:32:00",
                },
            ]
        )

    def test_feed_length(self):
        self.assertEqual(len(self.feed), 3)

    def test_symbols_are_unique_in_order(self):
        self.assertEqual(self.feed.symbols, ["AAPL", "MSFT"])

    def test_price_for_uses_latest_quote(self):
        self.assertEqual(self.feed.price_for("AAPL"), 112.0)

    def test_price_for_is_case_insensitive(self):
        self.assertEqual(self.feed.price_for("aapl"), 112.0)

    def test_price_for_unknown_symbol_raises(self):
        with self.assertRaises(KeyError):
            self.feed.price_for("NFLX")

    def test_quotes_for_filters_by_symbol(self):
        self.assertEqual(len(self.feed.quotes_for("AAPL")), 2)

    def test_price_ratio_between_symbols(self):
        ratio = self.feed.price_ratio("AAPL", "MSFT")
        self.assertIsNotNone(ratio)
        self.assertAlmostEqual(cast(float, ratio), 112.0 / 55.0)

    def test_price_ratio_with_zero_denominator_price_returns_none(self):
        feed = StockPriceFeed.from_records(
            [
                {"stock": "AAPL", "top_bid_price": 0.0, "top_ask_price": 0.0},
                {"stock": "MSFT", "top_bid_price": 50.0, "top_ask_price": 60.0},
            ]
        )
        # MSFT / AAPL divides by a zero price -> undefined, no ZeroDivisionError.
        self.assertIsNone(feed.price_ratio("MSFT", "AAPL"))

    def test_price_ratio_with_zero_numerator_price_is_zero(self):
        feed = StockPriceFeed.from_records(
            [
                {"stock": "AAPL", "top_bid_price": 0.0, "top_ask_price": 0.0},
                {"stock": "MSFT", "top_bid_price": 50.0, "top_ask_price": 60.0},
            ]
        )
        self.assertEqual(feed.price_ratio("AAPL", "MSFT"), 0.0)

    def test_prices_mapping(self):
        self.assertEqual(self.feed.prices(), {"AAPL": 112.0, "MSFT": 55.0})

    def test_summary_rows(self):
        rows = self.feed.summary()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], "AAPL")
        self.assertEqual(rows[0][3], 101.0)

    def test_read_quotes_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            path.write_text(
                "stock,top_bid_price,top_ask_price,timestamp\n"
                "AAPL,100.0,102.0,2024-01-01T09:30:00\n"
                "MSFT,50.0,60.0,2024-01-01T09:31:00\n",
                encoding="utf-8",
            )
            quotes = read_quotes(path)
            self.assertEqual(len(quotes), 2)
            self.assertEqual(quotes[0].stock, "AAPL")
            self.assertEqual(quotes[0].stock_price, 101.0)

    def test_read_quotes_from_json_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "stock": "AAPL",
                            "top_bid_price": 100.0,
                            "top_ask_price": 102.0,
                            "timestamp": "2024-01-01T09:30:00",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            quotes = read_quotes(path)
            self.assertEqual(len(quotes), 1)
            self.assertEqual(quotes[0].stock_price, 101.0)

    def test_read_quotes_from_json_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.jsonl"
            path.write_text(
                '{"stock": "AAPL", "top_bid_price": 100.0, "top_ask_price": 102.0}\n'
                '{"stock": "MSFT", "top_bid_price": 50.0, "top_ask_price": 60.0}\n',
                encoding="utf-8",
            )
            quotes = read_quotes(path)
            self.assertEqual(len(quotes), 2)

    def test_read_quotes_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_quotes(Path("does_not_exist_12345.csv"))

    def test_read_quotes_unsupported_extension_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.txt"
            path.write_text("nope", encoding="utf-8")
            with self.assertRaises(StockPriceError):
                read_quotes(path)


class TestCli(unittest.TestCase):
    """Smoke tests for the command line entry point."""

    def test_main_lists_prices(self):
        import client

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            path.write_text(
                "stock,top_bid_price,top_ask_price,timestamp\n"
                "AAPL,100.0,102.0,2024-01-01T09:30:00\n"
                "MSFT,50.0,60.0,2024-01-01T09:31:00\n",
                encoding="utf-8",
            )
            self.assertEqual(client.main(["--file", str(path), "--list"]), 0)

    def test_main_ratio(self):
        import client

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            path.write_text(
                "stock,top_bid_price,top_ask_price,timestamp\n"
                "AAPL,100.0,102.0,2024-01-01T09:30:00\n"
                "MSFT,50.0,60.0,2024-01-01T09:31:00\n",
                encoding="utf-8",
            )
            self.assertEqual(client.main(["--file", str(path), "--ratio", "AAPL:MSFT"]), 0)

    def test_main_without_file_returns_error_code(self):
        import client

        self.assertEqual(client.main([]), 2)

    def test_main_unknown_symbol_returns_error_code(self):
        import client

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "quotes.csv"
            path.write_text(
                "stock,top_bid_price,top_ask_price,timestamp\n"
                "AAPL,100.0,102.0,2024-01-01T09:30:00\n",
                encoding="utf-8",
            )
            self.assertEqual(client.main(["--file", str(path), "--ratio", "AAPL:NOPE"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
