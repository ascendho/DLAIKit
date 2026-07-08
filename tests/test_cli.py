import sys

import pytest

from dlaikit.cli import (
    ConfigError,
    ProgressReporter,
    build_parser,
    load_config,
    load_settings,
    print_progress,
    settings_from_config,
)


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
          "execute_lesson_notebooks": true,
          "notebook_execute_timeout_seconds": 123,
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
    assert settings.execute_lesson_notebooks is True
    assert settings.notebook_execute_timeout_seconds == 123
    assert settings.force is True


def test_settings_from_config_uses_defaults():
    settings = settings_from_config({"course_url": "https://example.test/course"})

    assert settings.course_url == "https://example.test/course"
    assert settings.code_url == ""
    assert settings.output_dir == "exports"
    assert settings.auth_state == ".auth/deeplearning_ai.json"
    assert settings.browser_visibility == "auto"
    assert settings.execute_lesson_notebooks is False
    assert settings.notebook_execute_timeout_seconds == 900
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


def test_settings_from_config_validates_execute_lesson_notebooks_bool():
    with pytest.raises(ConfigError, match="execute_lesson_notebooks"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "execute_lesson_notebooks": "yes",
            }
        )


def test_settings_from_config_validates_notebook_execute_timeout_seconds_int():
    with pytest.raises(ConfigError, match="notebook_execute_timeout_seconds"):
        settings_from_config(
            {
                "course_url": "https://example.test/course",
                "notebook_execute_timeout_seconds": 0,
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
    reporter.update(0, 0, "writing", "study pack")

    captured = capsys.readouterr()
    assert captured.err == (
        "discovering browser session\n"
        "[01/02] fetching Introduction\n"
        "[01/02] skipped  Introduction\n"
        "[01/01] skipped  course code\n"
        "writing study pack\n"
    )


def test_progress_reporter_tty_uses_spinner_and_status_icon():
    stream = FakeTTY()
    reporter = ProgressReporter(stream=stream, enabled=True, interval=0.001)

    reporter.update(0, 0, "discovering", "browser session")
    reporter.update(2, 11, "fetching", "Inside a Coding Agent")
    reporter.update(2, 11, "saved", "Inside a Coding Agent")
    reporter.update(1, 1, "skipped", "course code")
    reporter.update(0, 0, "writing", "study pack")
    reporter.close()

    output = stream.getvalue()
    assert "discovering browser session" in output
    assert "[02/11] fetching Inside a Coding Agent" in output
    assert "+ [02/11] saved    Inside a Coding Agent\n" in output
    assert "- [01/01] skipped  course code\n" in output
    assert "writing study pack" in output
    assert "+ saved    study pack\n" not in output
    assert "\r" in output
