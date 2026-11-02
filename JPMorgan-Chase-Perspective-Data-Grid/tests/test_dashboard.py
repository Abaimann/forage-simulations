"""Tests for the browser dashboard module."""

from __future__ import annotations

import json

import pytest

from jpm_perspective_grid.infrastructure.dashboard import (
    DASHBOARD_HTML,
    DashboardError,
    build_perspective_server,
    create_dashboard_app,
    dashboard_payload,
)

pytest.importorskip("perspective", reason="perspective-python not installed")
pytest.importorskip("tornado", reason="tornado not installed")

import tornado.testing  # noqa: E402


class TestDashboardHtml:
    def test_contains_the_viewer_tag(self):
        assert "<perspective-viewer" in DASHBOARD_HTML

    def test_references_the_quotes_table(self):
        assert 'table="quotes"' in DASHBOARD_HTML

    def test_connects_to_the_websocket_endpoint(self):
        assert "/websocket" in DASHBOARD_HTML

    def test_filters_on_the_alert_column(self):
        assert "trigger_alert" in DASHBOARD_HTML


class TestPerspectiveServer:
    def test_server_exposes_the_quotes_table(self):
        server = build_perspective_server()
        client = server.new_local_client()
        table = client.open_table("quotes")
        assert table is not None


class TestDashboardApp:
    def test_app_creation_succeeds(self):
        app = create_dashboard_app()
        assert app is not None

    def test_index_and_websocket_routes_are_registered(self):
        app = create_dashboard_app()
        rules = app.wildcard_router.rules
        patterns = [rule.matcher.regex.pattern for rule in rules]
        assert any(pattern.startswith("/websocket") for pattern in patterns)
        assert any(pattern.startswith("/$") or pattern == "/" for pattern in patterns)


class TestDashboardHttp(tornado.testing.AsyncHTTPTestCase):
    """End-to-end HTTP check of the dashboard entry point."""

    def get_app(self):
        return create_dashboard_app()

    def test_index_route_serves_the_html(self):
        response = self.fetch("/")
        assert response.code == 200
        assert b"perspective-viewer" in response.body

    def test_index_route_sets_the_html_content_type(self):
        response = self.fetch("/")
        assert response.headers["Content-Type"].startswith("text/html")

    def test_unknown_route_returns_404(self):
        response = self.fetch("/does-not-exist")
        assert response.code == 404


class TestDashboardPayload:
    def test_payload_is_json(self):
        payload = dashboard_payload([{"stock": "AAPL", "price": 1.0}])
        assert json.loads(payload)[0]["stock"] == "AAPL"

    def test_empty_payload(self):
        assert json.loads(dashboard_payload([])) == []


class TestDashboardError:
    def test_error_is_a_runtime_error(self):
        assert issubclass(DashboardError, RuntimeError)
