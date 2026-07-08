from dlaikit.crawler import _code_group_for_lesson, TranscriptCrawler
from dlaikit.parser import CourseInfo, LessonInfo


class FakeBrowser:
    def __init__(self, pages):
        self.pages = pages

    def fetch_page(self, url):
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
