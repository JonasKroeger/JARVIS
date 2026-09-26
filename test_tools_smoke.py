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
            "calendar_events",
            "volume_control",
            "start_timer",
            "list_timers",
            "fetch_url",
            "stock_quote",
            "dark_mode",
            "daily_briefing",
            "remember",
            "recall",
            "list_memories",
            "forget",
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

    # --- premium wave: validation / Linux-safe ---

    def test_fetch_url_rejects_file_scheme(self) -> None:
        data = json.loads(jarvis.tool_fetch_url({"url": "file:///etc/passwd"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("http", data["error"].lower())

    def test_fetch_url_rejects_empty(self) -> None:
        data = json.loads(jarvis.tool_fetch_url({"url": ""}))
        self.assertFalse(data.get("ok", True))

    def test_fetch_url_parse_html(self) -> None:
        html = (
            "<html><head><title>Hello World</title>"
            "<script>evil()</script><style>.x{}</style></head>"
            "<body><p>Visible text here</p></body></html>"
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        with patch("jarvis.httpx.Client", return_value=mock_client):
            data = json.loads(jarvis.tool_fetch_url({"url": "https://example.com", "max_chars": 100}))
        self.assertTrue(data["ok"])
        self.assertEqual(data["title"], "Hello World")
        self.assertIn("Visible text here", data["text"])
        self.assertNotIn("evil", data["text"])

    def test_volume_control_bad_action(self) -> None:
        data = json.loads(jarvis.tool_volume_control({"action": "blast"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("action must be", data["error"])

    def test_volume_control_set_requires_level(self) -> None:
        data = json.loads(jarvis.tool_volume_control({"action": "set"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("level", data["error"])

    def test_volume_level_clamp(self) -> None:
        data = json.loads(jarvis.tool_volume_control({"action": "set", "level": 150}))
        self.assertEqual(data.get("level"), 100)
        data2 = json.loads(jarvis.tool_volume_control({"action": "set", "level": -5}))
        self.assertEqual(data2.get("level"), 0)

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_volume_control_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_volume_control({"action": "get"}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("macOS", data["error"])

    def test_start_timer_requires_duration(self) -> None:
        data = json.loads(jarvis.tool_start_timer({}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("seconds or minutes", data["error"])

    def test_start_timer_rejects_negative(self) -> None:
        data = json.loads(jarvis.tool_start_timer({"seconds": -1}))
        self.assertFalse(data.get("ok", True))

    def test_start_timer_cap_24h(self) -> None:
        data = json.loads(jarvis.tool_start_timer({"seconds": 86400 + 1}))
        self.assertFalse(data.get("ok", True))
        self.assertIn("24h", data["error"])

    def test_start_timer_minutes(self) -> None:
        data = json.loads(jarvis.tool_start_timer({"minutes": 0.01, "label": "smoke"}))
        self.assertTrue(data.get("ok"), data)
        self.assertEqual(data["seconds"], 1)  # rounds to at least 1
        self.assertEqual(data["label"], "smoke")
        self.assertIn("ends_at", data)
        listed = json.loads(jarvis.tool_list_timers({}))
        self.assertGreaterEqual(listed["count"], 1)

    def test_calendar_days_clamped(self) -> None:
        data = json.loads(jarvis.tool_calendar_events({"days": 99}))
        # On Linux: error + empty events; days not always echoed on error path
        if platform.system() != "Darwin":
            self.assertIn("error", data)
            self.assertEqual(data.get("events"), [])
        else:
            self.assertEqual(data.get("days"), 7)

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_calendar_events_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_calendar_events({"days": 1}))
        self.assertIn("error", data)
        self.assertEqual(data.get("events"), [])

    @unittest.skipUnless(platform.system() != "Darwin", "non-Darwin path")
    def test_dark_mode_non_darwin(self) -> None:
        data = json.loads(jarvis.tool_dark_mode({"mode": "status"}))
        self.assertFalse(data.get("ok", True))

    def test_dark_mode_bad_mode(self) -> None:
        data = json.loads(jarvis.tool_dark_mode({"mode": "sepia"}))
        self.assertFalse(data.get("ok", True))

    def test_stock_quote_requires_symbol(self) -> None:
        data = json.loads(jarvis.tool_stock_quote({"symbol": ""}))
        self.assertFalse(data.get("ok", True))

    def test_stock_quote_invalid_symbol(self) -> None:
        data = json.loads(jarvis.tool_stock_quote({"symbol": "AAPL;rm"}))
        self.assertFalse(data.get("ok", True))

    def test_stock_quote_parse(self) -> None:
        fake = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "AAPL",
                            "regularMarketPrice": 190.5,
                            "currency": "USD",
                            "chartPreviousClose": 188.0,
                        }
                    }
                ],
                "error": None,
            }
        }
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = fake
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_resp
        with patch("jarvis.httpx.Client", return_value=mock_client):
            data = json.loads(jarvis.tool_stock_quote({"symbol": "aapl"}))
        self.assertTrue(data["ok"])
        self.assertEqual(data["symbol"], "AAPL")
        self.assertEqual(data["price"], 190.5)
        self.assertEqual(data["currency"], "USD")
        self.assertAlmostEqual(data["change_pct"], round((190.5 - 188.0) / 188.0 * 100, 4))

    def test_daily_briefing_skips_weather_when_empty_city(self) -> None:
        with (
            patch("jarvis.tool_get_current_time", return_value=json.dumps({"iso_local": "t"})),
            patch("jarvis.tool_get_system_status", return_value=json.dumps({"os": "Linux"})),
            patch(
                "jarvis.tool_calendar_events",
                return_value=json.dumps({"events": [], "days": 1}),
            ),
            patch("jarvis.tool_github_status", return_value=json.dumps({"error": "no gh"})),
            patch("jarvis.tool_get_weather") as weather,
        ):
            data = json.loads(jarvis.tool_daily_briefing({"city": ""}))
        weather.assert_not_called()
        self.assertTrue(data.get("ok"))
        self.assertTrue(data["weather"].get("skipped"))

    def test_daily_briefing_default_city(self) -> None:
        with (
            patch("jarvis.tool_get_current_time", return_value=json.dumps({"iso_local": "t"})),
            patch("jarvis.tool_get_system_status", return_value=json.dumps({"os": "Linux"})),
            patch(
                "jarvis.tool_calendar_events",
                return_value=json.dumps({"events": [], "days": 1}),
            ),
            patch("jarvis.tool_github_status", return_value=json.dumps({"authored": []})),
            patch(
                "jarvis.tool_get_weather",
                return_value=json.dumps({"temp_C": "5", "nearest_area": "Helsinki"}),
            ) as weather,
        ):
            data = json.loads(jarvis.tool_daily_briefing({}))
        weather.assert_called_once()
        self.assertEqual(weather.call_args[0][0].get("location"), "Helsinki")
        self.assertEqual(data["weather"]["temp_C"], "5")

    def test_chitchat_hi_still_fast(self) -> None:
        self.assertTrue(jarvis.is_chitchat("hi"))
        self.assertTrue(jarvis.is_chitchat("thanks"))
        self.assertTrue(jarvis.should_skip_tools("hi"))

    def test_briefing_phrases_not_chitchat(self) -> None:
        self.assertFalse(jarvis.is_chitchat("good morning"))
        self.assertFalse(jarvis.is_chitchat("brief me"))
        self.assertFalse(jarvis.is_chitchat("status report"))
        self.assertFalse(jarvis.should_skip_tools("good morning"))
        self.assertFalse(jarvis.should_skip_tools("brief me"))

    def test_personal_memory_questions_skip_tools(self) -> None:
        for phrase in (
            "what's my name",
            "what is my name",
            "who am i",
            "where do I live",
            "what do you know about me",
            "what do you remember about me",
            "what are my preferences",
            "what's my favorite color",
            "do you remember me",
        ):
            self.assertTrue(
                jarvis.is_personal_memory_question(phrase),
                msg=phrase,
            )
            self.assertTrue(jarvis.should_skip_tools(phrase), msg=phrase)
            self.assertFalse(jarvis.is_chitchat(phrase), msg=phrase)

    def test_memory_search_and_actions_keep_tools(self) -> None:
        for phrase in (
            "remember that my name is Jonas",
            "forget my name",
            "list memories",
            "recall helsinki",
            "what do you remember about the project",
            "what's my clipboard",
            "open safari",
            "what's the weather",
            "set a timer for 5 minutes",
            "search the web for rust",
            "volume up",
            "take a screenshot",
            "good morning",
        ):
            self.assertFalse(jarvis.should_skip_tools(phrase), msg=phrase)

    def test_short_general_qa_skips_tools(self) -> None:
        for phrase in (
            "what is pi",
            "what's pi",
            "what is π",
            "what's 2+2",
            "who is Einstein",
            "explain gravity briefly",
            "tell me a joke",
            "define photosynthesis",
            "how does wifi work?",
        ):
            self.assertTrue(jarvis.is_short_general_qa(phrase), msg=phrase)
            self.assertTrue(jarvis.should_skip_tools(phrase), msg=phrase)

    def test_long_without_action_skips_tools(self) -> None:
        """Tools are opt-in: long text without action keywords stays lean."""
        long_q = "what is pi " + ("x" * 130)
        self.assertFalse(jarvis.is_short_general_qa(long_q))
        self.assertFalse(jarvis.needs_tools(long_q))
        self.assertTrue(jarvis.should_skip_tools(long_q))

    def test_needs_tools_opt_in(self) -> None:
        self.assertFalse(jarvis.needs_tools("what is pi"))
        self.assertFalse(jarvis.needs_tools("what's my name"))
        self.assertFalse(jarvis.needs_tools("tell me a joke"))
        self.assertTrue(jarvis.needs_tools("what's the weather"))
        self.assertTrue(jarvis.needs_tools("good morning"))
        self.assertTrue(jarvis.needs_tools("open safari"))
        self.assertTrue(jarvis.needs_tools("remember that I like tea"))
        # Coder teammate — any mention enables tools so ask_coder can run
        self.assertTrue(jarvis.needs_tools("talk to coder"))
        self.assertTrue(jarvis.needs_tools("what does coder say"))
        self.assertTrue(jarvis.needs_tools("hello coder"))
        self.assertTrue(jarvis.needs_tools("ask coder X"))
        self.assertTrue(jarvis.needs_tools("tell coder to fix the bug"))
        self.assertTrue(jarvis.needs_tools("message coder please"))
        self.assertTrue(jarvis.needs_tools("ping coder"))

    def test_direct_tool_reply_weather(self) -> None:
        raw = json.dumps({
            "location_query": "Helsinki",
            "nearest_area": "Helsinki",
            "temp_C": "5",
            "weatherDesc": "Partly cloudy",
            "humidity": "80",
            "windspeedKmph": "12",
        })
        line = jarvis._format_direct_tool_reply("get_weather", raw)
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIn("Helsinki", line)
        self.assertIn("5°C", line)
        self.assertIn("Partly cloudy", line)

    def test_direct_tool_reply_skips_errors(self) -> None:
        self.assertIsNone(
            jarvis._format_direct_tool_reply(
                "get_weather", json.dumps({"error": "boom"})
            )
        )



class MemoryStoreTests(unittest.TestCase):
    """CRUD + injection tests with an injectable MEMORY_PATH (tempfile)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "memory.json"
        self._prev = jarvis.memory_store.MEMORY_PATH
        jarvis.memory_store.MEMORY_PATH = self._path

    def tearDown(self) -> None:
        jarvis.memory_store.MEMORY_PATH = self._prev
        self._tmpdir.cleanup()

    def test_remember_and_list(self) -> None:
        data = json.loads(jarvis.tool_remember({"text": "Works in Helsinki", "tags": ["work"]}))
        self.assertTrue(data["ok"])
        self.assertFalse(data["updated"])
        self.assertTrue(data["memory"]["id"].startswith("m_"))
        self.assertEqual(data["memory"]["text"], "Works in Helsinki")
        listed = json.loads(jarvis.tool_list_memories({"limit": 5}))
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["memories"][0]["text"], "Works in Helsinki")
        self.assertTrue(self._path.is_file())

    def test_remember_upsert_exact_text(self) -> None:
        first = json.loads(jarvis.tool_remember({"text": "Prefers tea"}))
        mid = first["memory"]["id"]
        second = json.loads(jarvis.tool_remember({"text": "Prefers tea", "tags": ["pref"]}))
        self.assertTrue(second["updated"])
        self.assertEqual(second["memory"]["id"], mid)
        listed = json.loads(jarvis.tool_list_memories({}))
        self.assertEqual(listed["count"], 1)

    def test_remember_caps_text(self) -> None:
        long = "x" * 600
        data = json.loads(jarvis.tool_remember({"text": long}))
        self.assertEqual(len(data["memory"]["text"]), jarvis.memory_store.MEMORY_TEXT_MAX)

    def test_remember_requires_text(self) -> None:
        data = json.loads(jarvis.tool_remember({"text": "  "}))
        self.assertIn("error", data)

    def test_recall_query_and_recent(self) -> None:
        jarvis.tool_remember({"text": "Name is Jonas", "tags": ["identity"]})
        jarvis.tool_remember({"text": "Lives in Helsinki", "tags": ["home"]})
        hits = json.loads(jarvis.tool_recall({"query": "helsinki"}))
        self.assertEqual(hits["count"], 1)
        self.assertIn("Helsinki", hits["memories"][0]["text"])
        tag_hits = json.loads(jarvis.tool_recall({"query": "identity"}))
        self.assertEqual(tag_hits["count"], 1)
        recent = json.loads(jarvis.tool_recall({}))
        self.assertEqual(recent["count"], 2)

    def test_forget_by_id_and_text(self) -> None:
        a = json.loads(jarvis.tool_remember({"text": "Fact A"}))
        b = json.loads(jarvis.tool_remember({"text": "Fact B"}))
        gone = json.loads(jarvis.tool_forget({"id": a["memory"]["id"]}))
        self.assertTrue(gone["ok"])
        self.assertTrue(gone["found"])
        miss = json.loads(jarvis.tool_forget({"id": "m_missing"}))
        self.assertFalse(miss["ok"])
        by_text = json.loads(jarvis.tool_forget({"text": "Fact B"}))
        self.assertTrue(by_text["ok"])
        listed = json.loads(jarvis.tool_list_memories({}))
        self.assertEqual(listed["count"], 0)

    def test_forget_requires_id_or_text(self) -> None:
        data = json.loads(jarvis.tool_forget({}))
        self.assertFalse(data["ok"])

    def test_inject_memory_into_messages(self) -> None:
        jarvis.tool_remember({"text": "User name is Jonas"})
        msgs = [{"role": "system", "content": "You are JARVIS."}, {"role": "user", "content": "hi"}]
        out = jarvis.memory_store.inject_memory_messages(msgs)
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(out[1]["role"], "system")
        self.assertTrue(out[1]["content"].startswith("## Long-term memory"))
        self.assertIn("Jonas", out[1]["content"])
        # Refresh replaces same sticky slot
        jarvis.tool_remember({"text": "Prefers dark mode"})
        out2 = jarvis.memory_store.inject_memory_messages(out)
        mem_msgs = [m for m in out2 if m.get("role") == "system" and str(m.get("content", "")).startswith("## Long-term memory")]
        self.assertEqual(len(mem_msgs), 1)
        self.assertIn("dark mode", mem_msgs[0]["content"])

    def test_atomic_write_creates_dir(self) -> None:
        nested = Path(self._tmpdir.name) / "sub" / "memory.json"
        jarvis.memory_store.MEMORY_PATH = nested
        jarvis.tool_remember({"text": "Nested path works"})
        self.assertTrue(nested.is_file())
        data = json.loads(nested.read_text())
        self.assertEqual(len(data), 1)




class VoiceTtsChunkTests(unittest.TestCase):
    def test_chunk_keeps_short_intact(self) -> None:
        import voice

        short = "The answer is forty-two."
        self.assertEqual(voice._chunk_for_tts(short), [short])

    def test_chunk_splits_on_sentences(self) -> None:
        import voice

        # Force small budget
        with patch.dict("os.environ", {"ELEVENLABS_MAX_CHARS": "60"}, clear=False):
            # Re-read limit via env each call
            text = (
                "First sentence ends here. Second sentence is also here. "
                "Third wraps past the budget nicely."
            )
            chunks = voice._chunk_for_tts(text)
        self.assertGreaterEqual(len(chunks), 2)
        joined = " ".join(chunks)
        for word in ("First", "Second", "Third", "budget"):
            self.assertIn(word, joined)
        for c in chunks:
            self.assertLessEqual(len(c), 60)
            # Never mid-word ellipsis from old truncator
            self.assertFalse(c.endswith("…"))

    def test_truncate_at_sentence_boundary(self) -> None:
        import voice

        text = "Alpha sentence one. Beta sentence two continues quite a bit further."
        out = voice._truncate_at_boundary(text, 40)
        self.assertTrue(out.endswith("."), msg=repr(out))
        self.assertNotIn("Beta", out)
        self.assertIn("Alpha", out)

    def test_predict_caps_raised(self) -> None:
        self.assertGreaterEqual(jarvis.NO_TOOLS_NUM_PREDICT, 256)
        self.assertGreaterEqual(jarvis.TOOLS_NARRATE_NUM_PREDICT, 200)
        self.assertLessEqual(jarvis.TOOLS_DECISION_NUM_PREDICT, 160)


class BridgeSmokeTests(unittest.TestCase):
    """Request parsing / health for the Coder → JARVIS bridge (no Ollama)."""

    def test_build_messages_plain(self) -> None:
        import bridge_server
        import jarvis

        msgs = bridge_server.build_messages("hello", None)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn(jarvis.SYSTEM_PROMPT[:20], msgs[0]["content"])
        self.assertEqual(msgs[-1], {"role": "user", "content": "hello"})

    def test_build_messages_with_draft(self) -> None:
        import bridge_server

        msgs = bridge_server.build_messages(
            "confirm",
            {"source": "coder", "grok_draft": "maybe four"},
        )
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[-1], "user")
        # Extra system note with draft
        mid = [m for m in msgs[1:-1] if m["role"] == "system"]
        self.assertTrue(mid)
        self.assertIn("maybe four", mid[0]["content"])
        self.assertIn("coder", mid[0]["content"])

    def test_health_endpoint(self) -> None:
        import bridge_server
        from unittest.mock import patch

        with patch.dict("os.environ", {"JARVIS_BRIDGE_PORT": "0"}, clear=False):
            # port 0 → OS picks a free port
            server = bridge_server.create_server(port=0, log=lambda *_: None)
        host, port = server.server_address
        t = __import__("threading").Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            import urllib.request

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                body = r.read().decode()
            self.assertEqual(body, '{"ok": true}')
        finally:
            server.shutdown()
            server.server_close()

    def test_chat_handler_mocked(self) -> None:
        import bridge_server
        import json
        import urllib.request
        from unittest.mock import patch

        def fake_run_turn(client, model, messages, on_token=None):  # noqa: ARG001
            return messages + [{"role": "assistant", "content": "four"}], "four"

        with patch("jarvis.run_turn", side_effect=fake_run_turn):
            server = bridge_server.create_server(port=0, log=lambda *_: None)
            host, port = server.server_address
            t = __import__("threading").Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/chat",
                    data=json.dumps({"message": "2+2", "context": {"source": "test"}}).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = json.loads(r.read().decode())
                self.assertEqual(data, {"reply": "four"})
            finally:
                server.shutdown()
                server.server_close()

    def test_chat_requires_message(self) -> None:
        import bridge_server

        with self.assertRaises(ValueError):
            bridge_server.handle_chat({})

    def test_auth_optional(self) -> None:
        import bridge_server
        import json
        import urllib.error
        import urllib.request
        from unittest.mock import patch

        def fake_run_turn(client, model, messages, on_token=None):  # noqa: ARG001
            return messages, "ok"

        with patch.dict("os.environ", {"JARVIS_API_KEY": "secret-test"}, clear=False):
            with patch("jarvis.run_turn", side_effect=fake_run_turn):
                server = bridge_server.create_server(port=0, log=lambda *_: None)
                port = server.server_address[1]
                t = __import__("threading").Thread(target=server.serve_forever, daemon=True)
                t.start()
                try:
                    # no auth → 401
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/chat",
                        data=json.dumps({"message": "hi"}).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as cm:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(cm.exception.code, 401)

                    # with auth → ok
                    req2 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/chat",
                        data=json.dumps({"message": "hi"}).encode(),
                        method="POST",
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": "Bearer secret-test",
                        },
                    )
                    with urllib.request.urlopen(req2, timeout=5) as r:
                        data = json.loads(r.read().decode())
                    self.assertEqual(data["reply"], "ok")
                finally:
                    server.shutdown()
                    server.server_close()

    def test_coder_client_demo(self) -> None:
        import coder_jarvis_bridge

        code = coder_jarvis_bridge.main(["--demo", "ping"])
        self.assertEqual(code, 0)



if __name__ == "__main__":
    unittest.main()
