import pytest

from dlaikit.code_assets import CodeAssetSummary, JupyterLabLink
from dlaikit.crawler import CourseDiscoveryError, _code_group_for_lesson, TranscriptCrawler
from dlaikit.fetchers import LoginRequiredError
from dlaikit.parser import CourseInfo, LessonInfo


class FakeBrowser:
    def __init__(self, pages):
        self.pages = pages

    def fetch_page(self, url, wait_for_lab=False):
        return self.pages[url]


def test_existing_lesson_path_prefers_transcripts_directory(tmp_path):
    course_dir = tmp_path / "course"
    transcripts_dir = course_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    legacy_path = course_dir / "01-introduction.md"
    new_path = transcripts_dir / "01-introduction.md"
    legacy_path.write_text("legacy", encoding="utf-8")
    new_path.write_text("new", encoding="utf-8")

    crawler = TranscriptCrawler(output_root=tmp_path)

    assert crawler._existing_lesson_path("course", 1) == new_path


def test_existing_lesson_path_falls_back_to_legacy_root_file(tmp_path):
    course_dir = tmp_path / "course"
    course_dir.mkdir()
    legacy_path = course_dir / "01-introduction.md"
    legacy_path.write_text("legacy", encoding="utf-8")

    crawler = TranscriptCrawler(output_root=tmp_path)

    assert crawler._existing_lesson_path("course", 1) == legacy_path


def test_code_group_for_lesson_splits_lesson_and_project_code():
    assert (
        _code_group_for_lesson(
            LessonInfo(
                1,
                "Tool Execution Environments",
                "https://example.test/code",
                kind="code",
            )
        )
        == "lessons"
    )
    assert (
        _code_group_for_lesson(
            LessonInfo(
                2,
                "Hands-On Project",
                "https://example.test/project",
                kind="lesson",
            )
        )
        == "project"
    )
    assert (
        _code_group_for_lesson(
            LessonInfo(
                3,
                "Graded",
                "https://example.test/graded",
                kind="assignment",
            )
        )
        == "project"
    )
    assert (
        _code_group_for_lesson(
            LessonInfo(
                4,
                "Conclusion",
                "https://example.test/conclusion",
                kind="video",
            )
        )
        is None
    )


def test_discover_jupyter_lab_links_marks_project_pages_as_project_group():
    lesson_url = "https://learn.example.test/lesson/data-analyst-agent"
    project_url = "https://learn.example.test/lesson/hands-on-project"
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://example.test/course",
        lessons=[
            LessonInfo(1, "Data analyst agent", lesson_url, kind="code"),
            LessonInfo(2, "Hands-On Project", project_url, kind="code"),
        ],
    )
    crawler = TranscriptCrawler()
    crawler.browser_fetcher = FakeBrowser(
        {
            lesson_url: """
            <iframe src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/L5/L5.ipynb?token=lesson-token"></iframe>
            """,
            project_url: """
            <a href="https://s172-29-9-999p8888.lab-aws-production.deeplearning.ai/lab/tree/project">
              Open project
            </a>
            """,
        }
    )

    links = crawler.discover_jupyter_lab_links(course, {})

    assert [(link.group, link.token) for link in links] == [
        ("lessons", "lesson-token"),
        ("project", ""),
    ]
    assert links[0].lesson_url == lesson_url
    assert links[1].lesson_url == project_url


def test_discover_lessons_reloads_dynamic_course_page(tmp_path):
    course_url = "https://www.deeplearning.ai/courses/course"
    lesson_url = "https://learn.deeplearning.ai/courses/course/lesson/id/introduction"

    class SequenceBrowser:
        def __init__(self):
            self.calls = 0

        def fetch(self, url):
            self.calls += 1
            if self.calls == 1:
                return "<html><h1>Course</h1></html>"
            return '<html><h1>Course</h1><a href="{}">Introduction</a></html>'.format(
                lesson_url
            )

    browser = SequenceBrowser()
    crawler = TranscriptCrawler(output_root=tmp_path)
    crawler.browser_fetcher = browser

    _, lesson_urls, _, _ = crawler.discover_lessons(course_url)

    assert lesson_urls == [lesson_url]
    assert browser.calls == 2


def test_discover_lessons_fails_instead_of_creating_placeholder(tmp_path):
    class EmptyBrowser:
        def __init__(self):
            self.calls = 0

        def fetch(self, url):
            self.calls += 1
            return "<html><h1>Course</h1></html>"

    browser = EmptyBrowser()
    crawler = TranscriptCrawler(output_root=tmp_path)
    crawler.browser_fetcher = browser

    with pytest.raises(CourseDiscoveryError, match="No lesson links"):
        crawler.discover_lessons("https://www.deeplearning.ai/courses/course")

    assert browser.calls == 2


def test_run_stops_immediately_when_login_is_required(tmp_path):
    lesson_url = "https://learn.deeplearning.ai/courses/course/lesson/id/introduction"
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://www.deeplearning.ai/courses/course",
        lessons=[LessonInfo(1, "Introduction", lesson_url, kind="video")],
    )

    class LoginCrawler(TranscriptCrawler):
        def discover_lessons(self, start_url):
            return "course", [lesson_url], {}, course

        def fetch_lesson(self, url):
            raise LoginRequiredError("login required")

    crawler = LoginCrawler(output_root=tmp_path)

    with pytest.raises(LoginRequiredError, match="login required"):
        crawler.run(course.source_url)


def test_run_records_reference_without_transcript_and_removes_stale_file(tmp_path):
    lesson_url = "https://learn.deeplearning.ai/courses/course/lesson/id/glossary"
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://www.deeplearning.ai/courses/course",
        lessons=[LessonInfo(1, "Glossary", lesson_url, kind="reference")],
    )

    class ReferenceCrawler(TranscriptCrawler):
        def discover_lessons(self, start_url):
            return "course", [lesson_url], {lesson_url: "<html><h1>Glossary</h1></html>"}, course

    stale = tmp_path / "course" / "transcripts" / "01-glossary.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("modal text", encoding="utf-8")
    crawler = ReferenceCrawler(output_root=tmp_path)

    _, manifest_path, results = crawler.run(course.source_url)

    assert results[0].status == "no_transcript"
    assert results[0].message == "transcript not provided for this course item"
    assert not stale.exists()
    assert manifest_path.name == "manifest.json"


def test_run_saves_transcript_for_video_with_code_example(tmp_path):
    lesson_url = "https://learn.deeplearning.ai/courses/course/lesson/id/code-video"
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://www.deeplearning.ai/courses/course",
        lessons=[LessonInfo(1, "Code Video", lesson_url, kind="code")],
    )
    html = """
    <html><body>
      <h1>Code Video</h1>
      <div class="drawer-content overflow-scroll">
        <div class="hidden">
          This official transcript belongs to a video that also contains a code example.
        </div>
        <div class="hidden">course detail</div>
      </div>
    </body></html>
    """

    class CodeVideoCrawler(TranscriptCrawler):
        def discover_lessons(self, start_url):
            return "course", [lesson_url], {lesson_url: html}, course

        def discover_jupyter_lab_links(self, course_info, html_cache):
            return []

    crawler = CodeVideoCrawler(output_root=tmp_path)

    _, _, results = crawler.run(course.source_url)

    assert results[0].status == "saved"
    assert results[0].path.name == "01-code-video.md"
    assert "official transcript" in results[0].path.read_text(encoding="utf-8")


def test_run_downloads_auto_discovered_lab_without_manual_code_url(tmp_path):
    lesson_url = "https://learn.deeplearning.ai/courses/course/lesson/id/code"
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://www.deeplearning.ai/courses/course",
        lessons=[LessonInfo(1, "Code", lesson_url, kind="code")],
    )

    class AutoLabCrawler(TranscriptCrawler):
        def __init__(self):
            super().__init__(output_root=tmp_path, code_url="")
            self.downloaded_links = None

        def discover_lessons(self, start_url):
            return "course", [lesson_url], {lesson_url: "<html><h1>Code</h1></html>"}, course

        def discover_jupyter_lab_links(self, course_info, html_cache):
            return [JupyterLabLink("https://lab.example.test/tree", group="lessons")]

        def download_code_assets(self, course_slug, lab_links=None):
            self.downloaded_links = lab_links
            return CodeAssetSummary(
                source_url=lab_links[0].url,
                output_dir=tmp_path / course_slug / "code",
            )

    crawler = AutoLabCrawler()

    crawler.run(course.source_url)

    assert crawler.downloaded_links[0].url == "https://lab.example.test/tree"
