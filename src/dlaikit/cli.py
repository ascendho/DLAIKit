import argparse
import itertools
import json
import sys
import threading
import time
from pathlib import Path

from .crawler import TranscriptCrawler
from .fetchers import MissingDependencyError


CONFIG_PATH = Path("dlaikit.json")
DEFAULT_OUTPUT_ROOT = "exports"
DEFAULT_AUTH_STATE = ".auth/deeplearning_ai.json"
DEFAULT_BROWSER_VISIBILITY = "auto"
DEFAULT_NOTEBOOK_EXECUTE_TIMEOUT_SECONDS = 900
BROWSER_VISIBILITY_CHOICES = {"auto", "hidden", "visible"}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dlaikit",
        usage="dlaikit",
        description="Extract a DeepLearning.AI course using dlaikit.json.",
    )
    return parser


def main(argv=None):
    build_parser().parse_args(argv)
    try:
        settings = load_settings(CONFIG_PATH)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    progress = ProgressReporter(sys.stderr)

    try:
        progress.update(0, 0, "discovering", "browser session")
        with TranscriptCrawler(
            output_root=settings.output_dir,
            auth_state=settings.auth_state,
            force=settings.force,
            study_pack=True,
            browser_visibility=settings.browser_visibility,
            code_url=settings.code_url,
            code_token=settings.code_token,
            execute_lesson_notebooks=settings.execute_lesson_notebooks,
            notebook_execute_timeout_seconds=settings.notebook_execute_timeout_seconds,
            progress_callback=progress.update,
        ) as crawler:
            course_slug, index_path, results = crawler.run(settings.course_url)
    except MissingDependencyError as exc:
        progress.close()
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        progress.close()

    saved = sum(1 for result in results if result.status == "saved")
    skipped = sum(1 for result in results if result.status == "skipped")
    metadata = sum(1 for result in results if result.status == "metadata")
    failed = sum(1 for result in results if result.status == "failed")

    print("Course: {}".format(course_slug))
    print("Index: {}".format(index_path))
    for label, path in crawler.study_pack_paths.items():
        print("{}: {}".format(label.title(), path))
    if crawler.code_assets_summary is not None:
        code_assets = crawler.code_assets_summary
        code_counts = [
            "Saved: {}".format(code_assets.saved),
            "Skipped: {}".format(code_assets.skipped),
            "Failed: {}".format(code_assets.failed),
        ]
        if code_assets.deduplicated:
            code_counts.append("Deduplicated: {}".format(code_assets.deduplicated))
        if code_assets.rewritten:
            code_counts.append("Rewritten: {}".format(code_assets.rewritten))
        if code_assets.executed:
            code_counts.append("Executed: {}".format(code_assets.executed))
        if code_assets.execution_failed:
            code_counts.append("Execution Failed: {}".format(code_assets.execution_failed))
        print("Code: {}".format(code_assets.output_dir))
        print("Code {}".format("  ".join(code_counts)))
        for error in code_assets.errors:
            print("Code Failed: {}".format(error))
    print(
        "Transcripts Saved: {}  Skipped: {}  Metadata: {}  Failed: {}".format(
            saved,
            skipped,
            metadata,
            failed,
        )
    )

    for result in results:
        if result.status == "failed":
            print("Failed {:02d}: {} ({})".format(result.index, result.url, result.message))

    if crawler.code_assets_summary is not None and crawler.code_assets_summary.failed:
        return 1
    return 1 if failed and not (saved or skipped) else 0


class ConfigError(Exception):
    pass


class Settings:
    def __init__(
        self,
        course_url,
        code_url="",
        code_token="",
        output_dir=DEFAULT_OUTPUT_ROOT,
        auth_state=DEFAULT_AUTH_STATE,
        browser_visibility=DEFAULT_BROWSER_VISIBILITY,
        force=False,
        execute_lesson_notebooks=False,
        notebook_execute_timeout_seconds=DEFAULT_NOTEBOOK_EXECUTE_TIMEOUT_SECONDS,
    ):
        self.course_url = course_url
        self.code_url = code_url
        self.code_token = code_token
        self.output_dir = output_dir
        self.auth_state = auth_state
        self.browser_visibility = browser_visibility
        self.force = force
        self.execute_lesson_notebooks = execute_lesson_notebooks
        self.notebook_execute_timeout_seconds = notebook_execute_timeout_seconds


def load_settings(config_path=CONFIG_PATH):
    config = load_config(config_path)
    return settings_from_config(config, config_path)


def load_config(config_path=CONFIG_PATH):
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(
            "{} not found. Create it with course_url before running dlaikit.".format(path)
        )
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError("{} is not valid JSON: {}".format(path, exc)) from exc
    if not isinstance(payload, dict):
        raise ConfigError("{} must contain a JSON object.".format(path))
    return payload


def settings_from_config(config, config_path=CONFIG_PATH):
    course_url = _config_string(config, "course_url")
    if not course_url:
        raise ConfigError(
            "course_url is required in {}.".format(config_path)
        )
    browser_visibility = _config_string(
        config,
        "browser_visibility",
        default=DEFAULT_BROWSER_VISIBILITY,
    )
    if browser_visibility not in BROWSER_VISIBILITY_CHOICES:
        raise ConfigError(
            "browser_visibility must be one of: auto, hidden, visible."
        )
    return Settings(
        course_url=course_url,
        code_url=_config_string(config, "code_url"),
        code_token=_config_string(config, "code_token"),
        output_dir=_config_string(config, "output_dir", default=DEFAULT_OUTPUT_ROOT),
        auth_state=_config_string(config, "auth_state", default=DEFAULT_AUTH_STATE),
        browser_visibility=browser_visibility,
        force=_config_bool(config, "force", default=False),
        execute_lesson_notebooks=_config_bool(config, "execute_lesson_notebooks", default=False),
        notebook_execute_timeout_seconds=_config_int(
            config,
            "notebook_execute_timeout_seconds",
            default=DEFAULT_NOTEBOOK_EXECUTE_TIMEOUT_SECONDS,
            minimum=1,
        ),
    )


def _config_string(config, key, default=""):
    value = config.get(key, default)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError("Config value {} must be a string.".format(key))
    return value.strip()


def _config_bool(config, key, default=False):
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError("Config value {} must be true or false.".format(key))
    return value


def _config_int(config, key, default=0, minimum=None):
    value = config.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError("Config value {} must be an integer.".format(key))
    if minimum is not None and value < minimum:
        raise ConfigError("Config value {} must be at least {}.".format(key, minimum))
    return value


def print_progress(index, total, status, title):
    ProgressReporter(sys.stderr, enabled=False).update(index, total, status, title)


class ProgressReporter:
    SPINNER_FRAMES = ("|", "/", "-", "\\")
    ACTIVE_STATUSES = {"discovering", "fetching", "writing"}
    STATUS_ICONS = {
        "saved": "+",
        "skipped": "-",
        "metadata": "*",
        "failed": "!",
    }

    def __init__(self, stream, enabled=None, interval=0.12):
        self.stream = stream
        self.enabled = stream.isatty() if enabled is None else enabled
        self.interval = interval
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._current = None
        self._line_length = 0

    def update(self, index, total, status, title):
        title = self._compact_title(title)
        if status in self.ACTIVE_STATUSES:
            self._start(index, total, status, title)
            return
        self._finish(index, total, status, title)

    def close(self):
        self._stop_spinner(clear=True)

    def _start(self, index, total, status, title):
        if not self.enabled:
            self._write_line(self._format_plain_active_line(index, total, status, title))
            return
        line = self._format_spinner_line(self.SPINNER_FRAMES[0], index, total, status, title)
        self._stop_spinner()
        with self._lock:
            self._current = (index, total, status, title)
            self._stop_event.clear()
            self._write_carriage(line)
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()

    def _finish(self, index, total, status, title):
        if self.enabled:
            self._stop_spinner(clear=True)
            icon = self.STATUS_ICONS.get(status, " ")
            if index <= 0 or total <= 0:
                self._write_line("{} {:<8} {}".format(icon, status, title))
                return
            self._write_line("{} [{}] {:<8} {}".format(icon, self._format_counter(index, total), status, title))
            return
        if index <= 0 or total <= 0:
            self._write_line("{:<8} {}".format(status, title))
            return
        self._write_line("[{}] {:<8} {}".format(self._format_counter(index, total), status, title))

    def _spin(self):
        for frame in itertools.cycle(self.SPINNER_FRAMES):
            if self._stop_event.is_set():
                return
            with self._lock:
                if self._current is None:
                    return
                index, total, status, title = self._current
            self._write_carriage(self._format_spinner_line(frame, index, total, status, title))
            time.sleep(self.interval)

    def _stop_spinner(self, clear=False):
        thread = self._thread
        if thread is not None:
            self._stop_event.set()
            thread.join()
            self._thread = None
        if clear and self.enabled:
            self._write_carriage("")

    def _write_line(self, line):
        print(line, file=self.stream, flush=True)

    def _write_carriage(self, line):
        padding = max(0, self._line_length - len(line))
        self.stream.write("\r{}{}\r".format(line, " " * padding))
        self.stream.flush()
        self._line_length = len(line)

    def _compact_title(self, title):
        title = " ".join(str(title).split())
        if len(title) > 80:
            title = title[:77] + "..."
        return title

    def _format_plain_active_line(self, index, total, status, title):
        if index <= 0 or total <= 0:
            return "{} {}".format(status, title)
        return "[{}] {} {}".format(self._format_counter(index, total), status, title)

    def _format_spinner_line(self, frame, index, total, status, title):
        if index <= 0 or total <= 0:
            return "{} {} {}".format(frame, status, title)
        return "{} [{}] {} {}".format(frame, self._format_counter(index, total), status, title)

    def _format_counter(self, index, total):
        width = max(2, len(str(total)))
        return "{index:0{width}d}/{total:0{width}d}".format(
            index=index,
            total=total,
            width=width,
        )


if __name__ == "__main__":
    raise SystemExit(main())
