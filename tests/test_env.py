from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from prts_crawler.config import load_settings
from prts_crawler.env import (
    env_bool,
    env_float,
    env_int,
    find_dotenv,
    load_dotenv,
    parse_dotenv,
)


class ParseDotenvTests(unittest.TestCase):
    def test_basic_and_comments(self) -> None:
        values = parse_dotenv(
            "# 注释\n"
            "\n"
            "PRTS_RATE=4\n"
            "export PRTS_WORKERS=8\n"
            "  PRTS_OUT_DIR = data  \n"
        )
        self.assertEqual(values["PRTS_RATE"], "4")
        self.assertEqual(values["PRTS_WORKERS"], "8")
        self.assertEqual(values["PRTS_OUT_DIR"], "data")

    def test_quoted_values_and_escapes(self) -> None:
        values = parse_dotenv(
            'PRTS_USER_AGENT="prts-crawler/0.1 (contact: me@example.com) # not a comment"\n'
            "SINGLE='keep # inside'\n"
            'MULTI="line1\\nline2"\n'
        )
        self.assertEqual(
            values["PRTS_USER_AGENT"],
            "prts-crawler/0.1 (contact: me@example.com) # not a comment",
        )
        self.assertEqual(values["SINGLE"], "keep # inside")
        self.assertEqual(values["MULTI"], "line1\nline2")

    def test_trailing_comment_removed_only_when_unquoted(self) -> None:
        values = parse_dotenv("PRTS_RATE=4  # 每秒请求数\nUA=a#b\n")
        self.assertEqual(values["PRTS_RATE"], "4")
        self.assertEqual(values["UA"], "a#b")

    def test_crlf_and_bom(self) -> None:
        values = parse_dotenv("\ufeffPRTS_RATE=2\r\nPRTS_MEDIA=0\r\n")
        self.assertEqual(values, {"PRTS_RATE": "2", "PRTS_MEDIA": "0"})

    def test_malformed_lines_are_skipped(self) -> None:
        values = parse_dotenv("nonsense line\n=novalue\nPRTS_RATE=4\n")
        self.assertEqual(values, {"PRTS_RATE": "4"})


class LoadDotenvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_writes_environment(self) -> None:
        env_file = self.tmp_path / ".env"
        env_file.write_text("PRTS_RATE=2\nPRTS_MEDIA=0\n", encoding="utf-8")

        loaded = load_dotenv(env_file)

        self.assertEqual(loaded, env_file)
        self.assertEqual(os.environ["PRTS_RATE"], "2")
        self.assertEqual(os.environ["PRTS_MEDIA"], "0")

    def test_real_environment_wins_unless_override(self) -> None:
        env_file = self.tmp_path / ".env"
        env_file.write_text("PRTS_RATE=2\n", encoding="utf-8")
        os.environ["PRTS_RATE"] = "9"

        load_dotenv(env_file)
        self.assertEqual(os.environ["PRTS_RATE"], "9")

        load_dotenv(env_file, override=True)
        self.assertEqual(os.environ["PRTS_RATE"], "2")

    def test_missing_file_is_ignored(self) -> None:
        self.assertIsNone(load_dotenv(self.tmp_path / "nope.env"))

    def test_find_dotenv_honours_env_var(self) -> None:
        env_file = self.tmp_path / "custom.env"
        env_file.write_text("PRTS_RATE=1\n", encoding="utf-8")
        os.environ["PRTS_ENV_FILE"] = str(env_file)
        try:
            self.assertEqual(find_dotenv(), env_file)
        finally:
            del os.environ["PRTS_ENV_FILE"]

    def test_find_dotenv_walks_up_from_start(self) -> None:
        env_file = self.tmp_path / ".env"
        env_file.write_text("PRTS_RATE=1\n", encoding="utf-8")
        nested = self.tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        self.assertEqual(find_dotenv(nested), env_file)


class TypedGetterTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_env_int_float_bool(self) -> None:
        os.environ.update({"I": "4", "F": "2.5", "T": "yes", "N": "off"})
        self.assertEqual(env_int("I", 1), 4)
        self.assertEqual(env_int("MISSING", 7), 7)
        self.assertEqual(env_float("F", 1.0), 2.5)
        self.assertTrue(env_bool("T", False))
        self.assertFalse(env_bool("N", True))
        self.assertTrue(env_bool("MISSING", True))
        self.assertFalse(env_bool("MISSING", False))

    def test_empty_value_uses_default(self) -> None:
        os.environ["EMPTY"] = ""
        self.assertTrue(env_bool("EMPTY", True))
        self.assertEqual(env_int("EMPTY", 3), 3)

    def test_invalid_numbers_fall_back(self) -> None:
        os.environ.update({"I": "abc", "F": "4/s"})
        self.assertEqual(env_int("I", 5), 5)
        self.assertEqual(env_float("F", 3.0), 3.0)


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults(self) -> None:
        settings = load_settings()
        self.assertEqual(settings.rate, 4.0)
        self.assertEqual(settings.workers, 4)
        self.assertEqual(settings.timeout, 30.0)
        self.assertEqual(settings.retries, 5)
        self.assertEqual(settings.out_dir, Path("data"))
        self.assertIsNone(settings.limit)
        self.assertTrue(settings.with_media)
        self.assertEqual(settings.export_format, "both")
        self.assertIn("Accept-Language", settings.headers)
        self.assertEqual(settings.headers["Accept-Language"], "zh-CN,zh;q=0.9")

    def test_env_overrides(self) -> None:
        os.environ.update(
            {
                "PRTS_RATE": "1.5",
                "PRTS_WORKERS": "2",
                "PRTS_LIMIT": "20",
                "PRTS_MEDIA": "0",
                "PRTS_OUT_DIR": "out",
                "PRTS_USER_AGENT": "my-bot/1.0 (me@example.com)",
            }
        )
        settings = load_settings()
        self.assertEqual(settings.rate, 1.5)
        self.assertEqual(settings.workers, 2)
        self.assertEqual(settings.limit, 20)
        self.assertFalse(settings.with_media)
        self.assertEqual(settings.out_dir, Path("out"))
        self.assertEqual(settings.headers["User-Agent"], "my-bot/1.0 (me@example.com)")

    def test_zero_limit_means_all(self) -> None:
        os.environ["PRTS_LIMIT"] = "0"
        self.assertIsNone(load_settings().limit)

    def test_export_format_is_lowercased(self) -> None:
        os.environ["PRTS_EXPORT_FORMAT"] = "HTML"
        self.assertEqual(load_settings().export_format, "html")

    def test_invalid_values_are_clamped(self) -> None:
        os.environ.update({"PRTS_RATE": "0", "PRTS_WORKERS": "-3", "PRTS_TIMEOUT": "0"})
        settings = load_settings()
        self.assertGreaterEqual(settings.rate, 0.1)
        self.assertGreaterEqual(settings.workers, 1)
        self.assertGreaterEqual(settings.timeout, 1.0)


if __name__ == "__main__":
    unittest.main()
