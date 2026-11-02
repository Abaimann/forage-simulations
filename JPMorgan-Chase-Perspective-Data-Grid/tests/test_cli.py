"""Tests for the command line interface."""

from __future__ import annotations

import json
import threading
import time

import pytest

from jpm_perspective_grid.cli import main
from jpm_perspective_grid.infrastructure.feed import TickFeedServer


class TestCli:
    def test_demo_runs_and_reports(self, capsys):
        assert main(["demo", "--ticks", "50", "--seed", "5"]) == 0
        captured = capsys.readouterr()
        assert "processed 50 ticks" in captured.out

    def test_demo_json_output(self, capsys):
        assert main(["demo", "--ticks", "20", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["throughput"]["ticks"] == 20
        assert payload["stats"]["ticks_ingested"] == 20

    def test_demo_json_output_is_parsable_even_with_alerts(self, capsys):
        assert main(["demo", "--ticks", "500", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["stats"]["ticks_ingested"] == 500

    def test_demo_respects_the_window_and_sigma(self, capsys):
        assert main(["demo", "--ticks", "30", "--window", "5", "--sigma", "1.0"]) == 0
        assert "processed 30 ticks" in capsys.readouterr().out

    def test_bench_runs(self, capsys):
        assert main(["bench", "--ticks", "100"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ticks"] == 100
        assert payload["ticks_per_second"] > 0

    def test_unknown_command_is_rejected(self):
        with pytest.raises(SystemExit):
            main(["does-not-exist"])

    def test_missing_command_is_rejected(self):
        with pytest.raises(SystemExit):
            main([])

    def test_help_is_available(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
        assert "demo" in capsys.readouterr().out


class TestCliServeAndClient:
    def test_serve_publishes_ticks_to_a_client(self, capsys):
        server = TickFeedServer(host="127.0.0.1", port=0)
        server.start()
        port = server.port
        try:
            result: dict[str, int] = {}

            def run_client() -> None:
                result["code"] = main(
                    ["client", "--host", "127.0.0.1", "--port", str(port), "--ticks", "25"]
                )

            thread = threading.Thread(target=run_client)
            thread.start()
            # Give the client time to subscribe before publishing.
            deadline = time.monotonic() + 3.0
            while server.client_count == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            from jpm_perspective_grid.core.models import Tick

            for index in range(40):
                server.broadcast(Tick("AAPL", 100.0 + index, 99.0 + index, index))
            thread.join(timeout=10.0)
            assert result.get("code") == 0
            assert "consumed 25 ticks" in capsys.readouterr().out
        finally:
            server.stop()

    def test_serve_starts_and_stops(self, capsys):
        assert main(["serve", "--port", "0", "--duration", "0.2", "--rate", "500"]) == 0
        output = capsys.readouterr().out
        assert "tick feed server listening on" in output
        assert "tick feed server stopped" in output

    def test_live_runs_the_whole_pipeline(self, capsys):
        assert main(["live", "--duration", "1", "--rate", "300"]) == 0
        output = capsys.readouterr().out
        assert "live grid running on" in output
        assert "ticks_ingested" in output

    def test_live_json_output(self, capsys):
        assert main(["live", "--duration", "1", "--rate", "200", "--json"]) == 0
        lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
        assert lines
        assert json.loads(lines[0])["kind"] in {"symbol", "pair"}

    def test_client_against_a_dead_port_fails_cleanly(self, capsys):
        assert main(["client", "--host", "127.0.0.1", "--port", "1", "--ticks", "1"]) == 2
        assert "error" in capsys.readouterr().err

