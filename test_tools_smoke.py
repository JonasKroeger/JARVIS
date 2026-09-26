#!/usr/bin/env python3
"""Tiny smoke tests for JARVIS tools (no Ollama required)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

import jarvis


class ToolSmokeTests(unittest.TestCase):
    def test_time(self) -> None:
        data = json.loads(jarvis.tool_get_current_time({}))
        self.assertIn("iso_local", data)

    def test_open_url_rejects_non_http(self) -> None:
        data = json.loads(jarvis.tool_open_url({"url": "file:///etc/passwd"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("error", data)

    def test_open_url_ok(self) -> None:
        with patch("jarvis.webbrowser.open", return_value=True) as m:
            data = json.loads(jarvis.tool_open_url({"url": "https://example.com"}))
        self.assertTrue(data["ok"])
        m.assert_called_once_with("https://example.com")

    def test_open_app_rejects_metachar(self) -> None:
        data = json.loads(jarvis.tool_open_app({"name": "Safari; rm -rf /"}))
        self.assertFalse(data.get("ok", True))

    def test_weather_parse(self) -> None:
        fake = {
            "current_condition": [
                {
                    "temp_C": "12",
                    "weatherDesc": [{"value": "Partly cloudy"}],
                    "humidity": "70",
                    "windspeedKmph": "15",
                }
            ],
            "nearest_area": [{"areaName": [{"value": "Helsinki"}]}],
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = fake
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        with patch("jarvis.httpx.Client", return_value=mock_client):
            data = json.loads(jarvis.tool_get_weather({"location": "Helsinki"}))
        self.assertEqual(data["temp_C"], "12")
        self.assertEqual(data["weatherDesc"], "Partly cloudy")
        self.assertEqual(data["nearest_area"], "Helsinki")
        self.assertNotIn("error", data)

    def test_github_missing_gh(self) -> None:
        with patch("jarvis.shutil.which", return_value=None):
            data = json.loads(jarvis.tool_github_status({}))
        self.assertIn("error", data)
        self.assertIn("gh auth login", data["error"])

    def test_dispatch_registered(self) -> None:
        names = {t["function"]["name"] for t in jarvis.TOOLS}
        self.assertEqual(names, set(jarvis.TOOL_DISPATCH.keys()))
        for expected in (
            "open_url",
            "open_app",
            "get_clipboard",
            "set_clipboard",
            "get_weather",
            "github_status",
            "get_current_time",
            "list_notes",
            "read_note",
            "save_note",
        ):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
