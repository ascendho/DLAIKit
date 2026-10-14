from pathlib import Path

from .code_assets import (
    BrowserJupyterClient,
    CODE_GROUP_LESSONS,
    CODE_GROUP_PROJECT,
    CodeAssetSummary,
    extract_jupyter_lab_links,
    JupyterCodeDownloader,
)
from .fetchers import BrowserFetcher, LoginRequiredError, NavigationError
from .parser import (
    clean_lines,
    CourseInfo,
    LessonInfo,
    extract_course_info,
    extract_lesson_data,
    extract_title,
    find_lesson_links,
)
from .text import course_slug_from_url, is_lesson_url, normalize_url, resolve_project_path, slugify
from .writer import (
    cleanup_legacy_export_files,
    LessonResult,
    write_lesson,
    write_manifest,
)


PROJECT_CODE_KEYWORDS = ("project", "graded", "assignment")
TRANSCRIPT_OPTIONAL_KINDS = {"code", "quiz", "assignment", "reference"}


class CourseDiscoveryError(RuntimeError):
    pass


class TranscriptCrawler:
    def __init__(
        self,
        output_root="exports",
        auth_state=".auth/deeplearning_ai.json",
        force=False,
        browser_visibility="auto",
        browser_channel="chromium",
        browser_profile_dir="",
        code_url="",
        code_token="",
        skip_code_dirs=None,
        progress_callback=None,
    ):
        self.output_root = Path(output_root)
        self.auth_state = resolve_project_path(auth_state)
        self.force = force
        self.browser_visibility = browser_visibility
        self.browser_channel = browser_channel
        self.browser_profile_dir = (
            resolve_project_path(browser_profile_dir) if browser_profile_dir else ""
        )
        self.code_url = code_url
        self.code_token = code_token
        self.skip_code_dirs = list(skip_code_dirs or [])
        self.progress_callback = progress_callback
        self.code_assets_summary = None
        self.browser_fetcher = None

    def __enter__(self):
        self.browser_fetcher = BrowserFetcher(
            self.auth_state,
            browser_visibility=self.browser_visibility,
            browser_channel=self.browser_channel,
            browser_profile_dir=self.browser_profile_dir,
        ).__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.browser_fetcher is not None:
            self.browser_fetcher.__exit__(exc_type, exc, traceback)

    def run(self, start_url):
        self._emit_progress(0, 0, "discovering", "course lessons")
        course_slug, lesson_urls, html_cache, course_info = self.discover_lessons(start_url)
        cleanup_legacy_export_files(self.output_root, course_slug)
        results = []
        lesson_metadata = {normalize_url(lesson.url): lesson for lesson in course_info.lessons}
        total = len(lesson_urls)

        for index, url in enumerate(lesson_urls, start=1):
            lesson = lesson_metadata.get(normalize_url(url))
            progress_title = lesson.title if lesson else "lesson"
            self._emit_progress(index, total, "fetching", progress_title)
            existing = self._existing_lesson_path(course_slug, index)
            transcript_optional = bool(
                lesson and lesson.kind in TRANSCRIPT_OPTIONAL_KINDS
            )
            if existing is not None and not self.force and not transcript_optional:
                result = LessonResult(
                    index=index,
                    url=url,
                    title=lesson.title if lesson else existing.stem[3:].replace("-", " ").title(),
                    status="skipped",
                    path=existing,
                    message="already exists",
                    kind=lesson.kind if lesson else "lesson",
                    duration=lesson.duration if lesson else "",
                    module_title=lesson.module_title if lesson else "",
                )
                results.append(result)
                self._emit_progress(index, total, result.status, result.title)
                continue

            try:
                html = html_cache.get(normalize_url(url)) or self.fetch_lesson(url)
                html_cache[normalize_url(url)] = html
                title, transcript = extract_lesson_data(html)
                if lesson and lesson.title:
                    title = lesson.title
                if not transcript:
                    if transcript_optional:
                        if existing is not None and existing.parent.name == "transcripts":
                            existing.unlink()
                        result = LessonResult(
                            index,
                            url,
                            title,
                            "no_transcript",
                            message="transcript not provided for this course item",
                            kind=lesson.kind,
                            duration=lesson.duration,
                            module_title=lesson.module_title,
                        )
                        results.append(result)
                        self._emit_progress(index, total, result.status, result.title)
                        continue
                    result = LessonResult(
                        index,
                        url,
                        title,
                        "failed",
                        message="transcript not found",
                        kind=lesson.kind if lesson else "lesson",
                        duration=lesson.duration if lesson else "",
                        module_title=lesson.module_title if lesson else "",
                    )
                    results.append(result)
                    self._emit_progress(index, total, result.status, result.title)
                    continue

                path = write_lesson(self.output_root, course_slug, index, title, url, transcript)
                result = LessonResult(
                    index,
                    url,
                    title,
                    "saved",
                    path=path,
                    kind=lesson.kind if lesson else "lesson",
                    duration=lesson.duration if lesson else "",
                    module_title=lesson.module_title if lesson else "",
                )
                results.append(result)
                self._emit_progress(index, total, result.status, result.title)
            except (LoginRequiredError, NavigationError):
                raise
            except Exception as exc:
                result = LessonResult(
                    index,
                    url,
                    lesson.title if lesson else "lesson",
                    "failed",
                    message=str(exc),
                    kind=lesson.kind if lesson else "lesson",
                    duration=lesson.duration if lesson else "",
                    module_title=lesson.module_title if lesson else "",
                )
                results.append(result)
                self._emit_progress(index, total, result.status, result.title)

        self._emit_progress(0, 0, "discovering", "course code")
        lab_links = self.discover_jupyter_lab_links(course_info, html_cache)
        if self.code_url or lab_links:
            self.code_assets_summary = self.download_code_assets(course_slug, lab_links)

        self._emit_progress(0, 0, "writing", "manifest")
        manifest_path = write_manifest(
            self.output_root,
            course_info,
            results,
            self.code_assets_summary,
        )
        return course_slug, manifest_path, results

    def discover_lessons(self, start_url):
        start_url = normalize_url(start_url)
        html_cache = {}

        html = self._browser().fetch(start_url)
        html_cache[start_url] = html
        lines, soup = clean_lines(html)
        course_info = extract_course_info(html, start_url)
        lesson_urls = [lesson.url for lesson in course_info.lessons] or find_lesson_links(soup, start_url)

        if not lesson_urls and not is_lesson_url(start_url):
            html = self._browser().fetch(start_url)
            html_cache[start_url] = html
            lines, soup = clean_lines(html)
            course_info = extract_course_info(html, start_url)
            lesson_urls = [lesson.url for lesson in course_info.lessons] or find_lesson_links(
                soup,
                start_url,
            )

        if is_lesson_url(start_url) and start_url not in lesson_urls:
            lesson_urls.insert(0, start_url)
        if not lesson_urls:
            raise CourseDiscoveryError(
                "No lesson links were found after reloading the course page. "
                "Confirm that the course URL is correct and finish login in the opened browser."
            )

        title = extract_title(soup, fallback="course")
        course_slug = course_slug_from_url(start_url) or slugify(title, fallback="course")
        course_info.slug = course_slug
        if not course_info.lessons:
            course_info.lessons = [
                LessonInfo(index=index, title="Lesson", url=url)
                for index, url in enumerate(lesson_urls, start=1)
            ]
        return course_slug, lesson_urls, html_cache, course_info

    def fetch_lesson(self, url):
        return self._browser().fetch(url)

    def discover_jupyter_lab_links(self, course_info, html_cache):
        links = []
        seen = set()

        for lesson in course_info.lessons:
            group = _code_group_for_lesson(lesson)
            if group is None:
                continue
            try:
                normalized_url = normalize_url(lesson.url)
                html = html_cache.get(normalized_url)
                discovered = extract_jupyter_lab_links(
                    html or "",
                    lesson_url=lesson.url,
                    group=group,
                )
                if not discovered:
                    html = self._browser().fetch_page(
                        lesson.url,
                        wait_for_lab=True,
                    )
                    discovered = extract_jupyter_lab_links(
                        html,
                        lesson_url=lesson.url,
                        group=group,
                    )
                html_cache[normalized_url] = html
            except Exception:
                continue

            for link in discovered:
                key = (link.url, link.token, link.group)
                if key in seen:
                    continue
                seen.add(key)
                links.append(link)

        return links

    def download_code_assets(self, course_slug, lab_links=None):
        self._emit_progress(1, 1, "fetching", "course code")
        downloader = JupyterCodeDownloader(
            BrowserJupyterClient(self._browser()),
            self.output_root,
            course_slug,
            force=self.force,
            code_token=self.code_token,
            skip_code_dirs=self.skip_code_dirs,
            state_root=self.auth_state.parent / "code-downloads",
        )
        summary: CodeAssetSummary = downloader.download(self.code_url, discovered_links=lab_links or [])
        if summary.failed:
            status = "failed"
        elif summary.saved:
            status = "saved"
        else:
            status = "skipped"
        self._emit_progress(1, 1, status, "course code")
        return summary

    def _browser(self):
        if self.browser_fetcher is None:
            self.browser_fetcher = BrowserFetcher(
                self.auth_state,
                browser_visibility=self.browser_visibility,
                browser_channel=self.browser_channel,
                browser_profile_dir=self.browser_profile_dir,
            ).__enter__()
        return self.browser_fetcher

    def _existing_lesson_path(self, course_slug, index):
        course_dir = self.output_root / course_slug
        pattern = "{:02d}-*.md".format(index)
        matches = sorted((course_dir / "transcripts").glob(pattern))
        if not matches:
            matches = sorted(course_dir.glob(pattern))
        return matches[0] if matches else None

    def _emit_progress(self, index, total, status, title):
        if self.progress_callback is not None:
            self.progress_callback(index, total, status, title)


def _code_group_for_lesson(lesson):
    text = " ".join([lesson.kind or "", lesson.title or "", lesson.module_title or ""]).lower()
    if lesson.kind in {"assignment", "quiz"} or any(keyword in text for keyword in PROJECT_CODE_KEYWORDS):
        return CODE_GROUP_PROJECT
    if lesson.kind == "code":
        return CODE_GROUP_LESSONS
    return None
