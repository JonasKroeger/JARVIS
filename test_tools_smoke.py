#!/usr/bin/env python3
"""Tiny smoke tests for JARVIS tools (no Ollama required)."""

from __future__ import annotations

import json
import platform
import tempfile
import unittest
from pathlib import Path
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
            "get_system_status",
            "notify",
            "create_reminder",
            "music_control",
            "take_screenshot",
            "list_running_apps",
            "read_file",
            "web_search",
        ):
            self.assertIn(expected, names)

    # --- helpers ---

    def test_escape_applescript(self) -> None:
        self.assertEqual(jarvis._escape_applescript('say "hi"\\'), 'say \\"hi\\"\\\\')
        self.assertEqual(jarvis._escape_applescript("plain"), "plain")

    def test_resolve_under_home_ok(self) -> None:
        home = Path.home()
        p = jarvis._resolve_under_home(str(home / "Documents" / "x.txt"))
        self.assertIsNotNone(p)
        assert p is not None
        self.assertTrue(str(p).startswith(str(home.resolve())))

    def test_resolve_under_home_rejects_escape(self) -> None:
        self.assertIsNone(jarvis._resolve_under_home("/etc/passwd"))
        # Attempt to escape via .. from a home-relative path
        sneaky = str(Path.home() / ".." / ".." / "etc" / "passwd")
        self.assertIsNone(jarvis._resolve_under_home(sneaky))

    def test_parse_battery_pmset(self) -> None:
        sample = (
            "Now drawing from 'Battery Power'\n"
            " -InternalBattery-0 (id=123)	82%; discharging; 3:21 remaining present: true"
        )
        info = jarvis._parse_battery_pmset(sample)
        self.assertEqual(info["percent"], 82)
        self.assertFalse(info["charging"])

        charging = " -InternalBattery-0\t50%; charging; 0:00 remaining"
        info2 = jarvis._parse_battery_pmset(charging)
        self.assertEqual(info2["percent"], 50)
        self.assertTrue(info2["charging"])

    # --- new tools: validation / Linux-safe ---

    def test_notify_rejects_empty(self) -> None:
        data = json.loads(jarvis.tool_notify({"title": "  ", "message": ""}))
        self.assertFalse(data.get("ok", True))

    def test_notify_rejects_insane_length(self) -> None:
        data = json.loads(
            jarvis.tool_notify({"title": "x" * (jarvis.NOTIFY_TITLE_MAX * 5), "message": "hi"})
        )
        self.assertFalse(data.get("ok", True))
        self.assertIn("insanely long", data["error"])

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_notify_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_notify({"title": "Hi", "message": "There"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("macOS", data["error"])

    def test_create_reminder_requires_text(self) -> None:
        data = json.loads(jarvis.tool_create_reminder({"text": "  "}))
        self.assertFalse(data.get("ok", True))

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_create_reminder_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_create_reminder({"text": "Buy milk"}))
        self.assertFalse(data.get("ok", True))

    def test_music_control_bad_action(self) -> None:
        data = json.loads(jarvis.tool_music_control({"action": "shuffle"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("action must be", data["error"])

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_music_control_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_music_control({"action": "play"}))
        self.assertFalse(data.get("ok", True))

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_take_screenshot_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_take_screenshot({}))
        self.assertFalse(data.get("ok", True))

    def test_take_screenshot_path_sandbox(self) -> None:
        # Even on Darwin this should reject /tmp; on Linux also early-returns macOS-only.
        # Force Darwin path for sandbox check via platform mock.
        with patch("jarvis.platform.system", return_value="Darwin"):
            data = json.loads(jarvis.tool_take_screenshot({"path": "/tmp/evil.png"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("home", data["error"])

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_list_running_apps_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_list_running_apps({}))
        self.assertEqual(data.get("apps"), [])
        self.assertIn("error", data)

    def test_read_file_sandbox(self) -> None:
        data = json.loads(jarvis.tool_read_file({"path": "/etc/passwd"}))
        self.assertIn("error", data)
        self.assertIn("home", data["error"])

    def test_read_file_ok_under_home(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=Path.home(), suffix=".jarvis-test"
        ) as f:
            f.write("hello jarvis")
            tmp = f.name
        try:
            data = json.loads(jarvis.tool_read_file({"path": tmp, "max_bytes": 100}))
            self.assertEqual(data["content"], "hello jarvis")
            self.assertFalse(data["truncated"])
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_read_file_truncates(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb", delete=False, dir=Path.home(), suffix=".jarvis-test"
        ) as f:
            f.write(b"abcdefghij")
            tmp = f.name
        try:
            data = json.loads(jarvis.tool_read_file({"path": tmp, "max_bytes": 4}))
            self.assertTrue(data["truncated"])
            self.assertEqual(data["bytes_read"], 4)
            self.assertEqual(data["content"], "abcd")
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_read_file_requires_path(self) -> None:
        data = json.loads(jarvis.tool_read_file({}))
        self.assertIn("error", data)

    def test_web_search_requires_query(self) -> None:
        data = json.loads(jarvis.tool_web_search({"query": "  "}))
        self.assertIn("error", data)

    def test_web_search_parse(self) -> None:
        fake = {
            "AbstractText": "Finland is a Nordic country.",
            "AbstractURL": "https://example.com/finland",
            "Heading": "Finland",
            "RelatedTopics": [
                {"Text": "Helsinki is the capital."},
                {"Text": "Finnish is spoken there."},
                {
                    "Name": "Related",
                    "Topics": [
                        {"Text": "Nordic countries"},
                        {"Text": "Scandinavia"},
                        {"Text": "Europe"},
                    ],
                },
            ],
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = fake
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        with patch("jarvis.httpx.Client", return_value=mock_client):
            data = json.loads(jarvis.tool_web_search({"query": "Finland"}))
        self.assertEqual(data["AbstractText"], "Finland is a Nordic country.")
        self.assertEqual(data["AbstractURL"], "https://example.com/finland")
        self.assertLessEqual(len(data["RelatedTopics"]), 5)
        self.assertIn("Helsinki is the capital.", data["RelatedTopics"])
        self.assertNotIn("error", data)

    def test_system_status_linux_or_darwin(self) -> None:
        data = json.loads(jarvis.tool_get_system_status({}))
        self.assertIn("os", data)
        self.assertIn("hostname", data)
        self.assertIn("disk", data)
        self.assertIn("uptime", data)
        self.assertIn("battery", data)
        # disk should have avail or error
        if "error" not in data["disk"]:
            self.assertTrue("avail" in data["disk"] or "raw" in data["disk"])

    @unittest.skipUnless(platform.system() == "Darwin", "Darwin-only live osascript")
    def test_notify_darwin_live(self) -> None:
        data = json.loads(jarvis.tool_notify({"title": "JARVIS test", "message": "smoke"}))
        self.assertTrue(data.get("ok"), data)


if __name__ == "__main__":
    unittest.main()
