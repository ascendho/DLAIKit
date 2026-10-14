import sys

import pytest

import dlaikit.cli as cli_module

from dlaikit.cli import (
    ConfigError,
    ProgressReporter,
    build_parser,
    load_config,
    load_settings,
    print_progress,
    settings_from_config,
)
from dlaikit.writer import LessonResult


class FakeTTY:
    def __init__(self):
        self.parts = []

    def isatty(self):
        return True

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass

    def getvalue(self):
        return "".join(self.parts)


def test_cli_accepts_no_arguments():
    parser = build_parser()

    args = parser.parse_args([])

    assert vars(args) == {}


def test_cli_rejects_course_url_argument():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["https://example.test/course"])


def test_cli_rejects_removed_options():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--study-pack"])


def test_cli_returns_failure_for_partial_transcript_failure(monkeypatch, tmp_path):
    class FakeCrawler:
        def __init__(self, **kwargs):
            self.code_assets_summary = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            pass

        def run(self, course_url):
            return (
                "course",
                tmp_path / "course" / "manifest.json",
                [
                    LessonResult(1, "https://example.test/1", "One", "saved"),
                    LessonResult(2, "https://example.test/2", "Two", "failed"),
                ],
            )

    monkeypatch.setattr(
        cli_module,
        "load_settings",
        lambda path: cli_module.Settings("https://example.test/course"),
    )
    monkeypatch.setattr(cli_module, "TranscriptCrawler", FakeCrawler)

    assert cli_module.main([]) == 1


def test_load_settings_from_config_file(tmp_path):
    config_path = tmp_path / "dlaikit.json"
    config_path.write_text(
        """
        {
          "course_url": "https://example.test/course",
          "code_url": "https://lab.example.test/tree",
          "code_token": "secret",
          "output_dir": "exports",
          "auth_state": ".auth/custom.json",
          "browser_visibility": "hidden",
          "browser_channel": "chrome",
          "browser_profile_dir": ".auth/chrome-profile",
          "skip_code_dirs": ["models"],
          "force": true
        }
        """,
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.course_url == "https://example.test/course"
    assert settings.code_url == "https://lab.example.test/tree"
    assert settings.code_token == "secret"
    assert settings.output_dir == "exports"
    assert settings.auth_state == ".auth/custom.json"
    assert settings.browser_visibility == "hidden"
    assert settings.browser_channel == "chrome"
    assert settings.browser_profile_dir == ".auth/chrome-profile"
    assert settings.skip_code_dirs == ["models"]
    assert settings.force is True


def test_settings_from_config_uses_defaults():
    settings = settings_from_config({"course_url": "https://example.test/course"})

    assert settings.course_url == "https://example.test/course"
    assert settings.code_url == ""
    assert settings.output_dir == "exports"
    assert settings.auth_state == ".auth/deeplearning_ai.json"
    assert settings.browser_visibility == "auto"
    assert settings.browser_channel == "chromium"
    assert settings.browser_profile_dir == ""
    assert settings.skip_code_dirs == []
    assert settings.force is False


def test_load_config_requires_existing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.json")


def test_settings_from_config_requires_course_url():
    with pytest.raises(ConfigError, match="course_url is required"):
        settings_from_config({})


def test_settings_from_config_validates_browser_visibility():
    with pytest.raises(ConfigError, match="browser_visibility"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "browser_visibility": "sometimes",
            }
        )


def test_settings_from_config_validates_force_bool():
    with pytest.raises(ConfigError, match="force"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "force": "yes",
            }
        )


def test_settings_from_config_validates_browser_channel():
    with pytest.raises(ConfigError, match="browser_channel"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "browser_channel": "safari",
            }
        )


def test_settings_from_config_validates_browser_profile_dir_string():
    with pytest.raises(ConfigError, match="browser_profile_dir"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "browser_profile_dir": [".auth/chrome-profile"],
            }
        )


def test_settings_from_config_validates_skip_code_dirs_list():
    with pytest.raises(ConfigError, match="skip_code_dirs"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "skip_code_dirs": "models",
            }
        )


def test_print_progress_uses_compact_status_line(capsys):
    print_progress(3, 11, "saved", "Your First Coding Agent")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[03/11] saved    Your First Coding Agent\n"


def test_print_progress_pads_total_width(capsys):
    print_progress(1, 1, "skipped", "course code")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "[01/01] skipped  course code\n"


def test_progress_reporter_non_tty_uses_plain_lines(capsys):
    reporter = ProgressReporter(stream=sys.stderr, enabled=False)

    reporter.update(0, 0, "discovering", "browser session")
    reporter.update(1, 2, "fetching", "Introduction")
    reporter.update(1, 2, "skipped", "Introduction")
    reporter.update(1, 1, "skipped", "course code")
    reporter.update(0, 0, "writing", "manifest")

    captured = capsys.readouterr()
    assert captured.err == (
        "discovering browser session\n"
        "[01/02] fetching Introduction\n"
        "[01/02] skipped  Introduction\n"
        "[01/01] skipped  course code\n"
        "writing manifest\n"
    )


def test_progress_reporter_tty_uses_spinner_and_status_icon():
    stream = FakeTTY()
    reporter = ProgressReporter(stream=stream, enabled=True, interval=0.001)

    reporter.update(0, 0, "discovering", "browser session")
    reporter.update(2, 11, "fetching", "Inside a Coding Agent")
    reporter.update(2, 11, "saved", "Inside a Coding Agent")
    reporter.update(1, 1, "skipped", "course code")
    reporter.update(0, 0, "writing", "manifest")
    reporter.close()

    output = stream.getvalue()
    assert "discovering browser session" in output
    assert "[02/11] fetching Inside a Coding Agent" in output
    assert "+ [02/11] saved    Inside a Coding Agent\n" in output
    assert "- [01/01] skipped  course code\n" in output
    assert "writing manifest" in output
    assert "+ saved    manifest\n" not in output
    assert "\r" in output
