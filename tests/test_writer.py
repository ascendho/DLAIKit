import json

from dlaikit.code_assets import CodeAssetFile, CodeAssetSummary
from dlaikit.parser import CourseInfo, LessonInfo, ResourceLink
from dlaikit.writer import LessonResult, write_index, write_lesson
from dlaikit.writer import write_course_overview, write_manifest, write_resources


def test_write_lesson_and_index(tmp_path):
    lesson_path = write_lesson(
        tmp_path,
        "course",
        1,
        "Introduction",
        "https://example.test/lesson",
        "Transcript text.",
    )

    index_path = write_index(
        tmp_path,
        "course",
        "https://example.test/course",
        [LessonResult(1, "https://example.test/lesson", "Introduction", "saved", lesson_path)],
    )

    assert lesson_path.name == "01-introduction.md"
    assert lesson_path.parent.name == "transcripts"
    assert "Transcript text." in lesson_path.read_text(encoding="utf-8")
    assert "[01. Introduction](transcripts/01-introduction.md)" in index_path.read_text(encoding="utf-8")


def test_write_study_pack_files(tmp_path):
    course = CourseInfo(
        title="Building Coding Agents with Tool Execution",
        slug="building-coding-agents-with-tool-execution",
        source_url="https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution",
        description="Build coding agents with safe tool execution.",
        level="Intermediate",
        duration="1 hour",
        instructors=["Tereza Tizkova", "Francesco Zuppichinni"],
        learning_objectives=["Run generated code safely."],
        lessons=[
            LessonInfo(
                1,
                "Introduction",
                "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction",
                "video",
                "3 mins",
            ),
            LessonInfo(
                2,
                "Data analyst agent",
                "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/abc123/data-analyst-agent",
                "code",
                "12 mins",
            ),
        ],
        resources=[
            ResourceLink("Course notebooks", "https://github.com/example/course-notebooks", "repository")
        ],
    )
    results = [
        LessonResult(
            1,
            course.lessons[0].url,
            "Introduction",
            "saved",
            tmp_path
            / "building-coding-agents-with-tool-execution"
            / "transcripts"
            / "01-introduction.md",
            kind="video",
            duration="3 mins",
        ),
        LessonResult(
            2,
            course.lessons[1].url,
            "Data analyst agent",
            "metadata",
            message="transcript not expected",
            kind="code",
            duration="12 mins",
        ),
    ]

    overview_path = write_course_overview(tmp_path, course)
    resources_path = write_resources(tmp_path, course)
    manifest_path = write_manifest(tmp_path, course, results)

    assert "Run generated code safely." in overview_path.read_text(encoding="utf-8")
    assert "Data analyst agent" in resources_path.read_text(encoding="utf-8")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["course"]["slug"] == "building-coding-agents-with-tool-execution"
    assert payload["lessons"][1]["kind"] == "code"
    assert payload["results"][0]["path"] == "transcripts/01-introduction.md"
    assert payload["results"][1]["status"] == "metadata"


def test_write_index_and_manifest_include_code_assets(tmp_path):
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://example.test/course",
        lessons=[
            LessonInfo(1, "Introduction", "https://example.test/lesson"),
        ],
    )
    results = [
        LessonResult(
            1,
            "https://example.test/lesson",
            "Introduction",
            "saved",
            tmp_path / "course" / "transcripts" / "01-introduction.md",
        )
    ]
    code_assets = CodeAssetSummary(
        source_url="https://lab.example.test/tree",
        output_dir=tmp_path / "course" / "code",
        saved=1,
        skipped=1,
        failed=0,
        deduplicated=2,
        rewritten=1,
        executed=1,
        execution_failed=1,
        files=[
            CodeAssetFile("lessons/app.py", "saved", bytes=12),
            CodeAssetFile("project/README.md", "skipped"),
        ],
    )

    index_path = write_index(
        tmp_path,
        course.slug,
        course.source_url,
        results,
        course,
        code_assets,
    )
    manifest_path = write_manifest(tmp_path, course, results, code_assets)

    index = index_path.read_text(encoding="utf-8")
    assert "## Code" in index
    assert "[code](code/)" in index
    assert "Lesson code: [code/lessons](code/lessons/)" in index
    assert "Project code: [code/project](code/project/)" in index
    assert (
        "Saved: 1  Skipped: 1  Failed: 0  Deduplicated: 2  Rewritten: 1  "
        "Executed: 1  Execution Failed: 1"
    ) in index

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["code_assets"]["source_url"] == "https://lab.example.test/tree"
    assert payload["code_assets"]["path"] == "code"
    assert payload["code_assets"]["deduplicated"] == 2
    assert payload["code_assets"]["rewritten"] == 1
    assert payload["code_assets"]["executed"] == 1
    assert payload["code_assets"]["execution_failed"] == 1
    assert payload["code_assets"]["files"][0]["path"] == "lessons/app.py"


def test_write_index_and_manifest_redact_code_tokens(tmp_path):
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://example.test/course",
    )
    code_assets = CodeAssetSummary(
        source_url="https://lab.example.test/tree?token=secret",
        output_dir=tmp_path / "course" / "code",
        failed=1,
        errors=["GET https://lab.example.test/api/contents?token=secret&content=1 failed"],
    )

    index_path = write_index(tmp_path, course.slug, course.source_url, [], course, code_assets)
    manifest_path = write_manifest(tmp_path, course, [], code_assets)

    index = index_path.read_text(encoding="utf-8")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "secret" not in index
    assert "secret" not in manifest_path.read_text(encoding="utf-8")
    assert "token=REDACTED" in index
    assert payload["code_assets"]["source_url"] == "https://lab.example.test/tree?token=REDACTED"
