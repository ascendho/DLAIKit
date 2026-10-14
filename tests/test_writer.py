import json

from dlaikit.code_assets import CodeAssetSummary
from dlaikit.parser import CourseInfo
from dlaikit.writer import (
    LessonResult,
    cleanup_legacy_export_files,
    write_lesson,
    write_manifest,
)


def test_write_lesson_adds_only_minimal_source_wrapper(tmp_path):
    lesson_path = write_lesson(
        tmp_path,
        "course",
        1,
        "Introduction",
        "https://example.test/lesson",
        "Transcript text.",
    )

    assert lesson_path.name == "01-introduction.md"
    assert lesson_path.parent.name == "transcripts"
    assert lesson_path.read_text(encoding="utf-8") == (
        "# Introduction\n\n"
        "Source: https://example.test/lesson\n\n"
        "Transcript text.\n"
    )


def test_write_manifest_contains_only_provenance_and_status(tmp_path):
    course = CourseInfo(
        title="Course",
        slug="course",
        source_url="https://example.test/course",
        description="Derived description that must not be exported.",
        instructors=["Wrongly parsed navigation item"],
        learning_objectives=["Derived objective"],
    )
    transcript_path = tmp_path / "course" / "transcripts" / "01-introduction.md"
    results = [
        LessonResult(1, "https://example.test/1", "Introduction", "saved", transcript_path),
        LessonResult(
            2,
            "https://example.test/2",
            "Code",
            "no_transcript",
            message="transcript not provided for this course item",
            kind="code",
        ),
    ]
    code_assets = CodeAssetSummary(
        source_url="https://lab.example.test/tree?token=secret",
        source_urls=[
            "https://lab.example.test/tree?token=secret",
            "https://project.example.test/tree",
        ],
        output_dir=tmp_path / "course" / "code",
        saved=2,
        skipped=1,
        failed=0,
    )

    manifest_path = write_manifest(tmp_path, course, results, code_assets)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload == {
        "schema_version": 1,
        "course": {
            "title": "Course",
            "slug": "course",
            "source_url": "https://example.test/course",
        },
        "lessons": [
            {
                "index": 1,
                "title": "Introduction",
                "source_url": "https://example.test/1",
                "status": "saved",
                "transcript_path": "transcripts/01-introduction.md",
                "message": "",
            },
            {
                "index": 2,
                "title": "Code",
                "source_url": "https://example.test/2",
                "status": "no_transcript",
                "transcript_path": "",
                "message": "transcript not provided for this course item",
            },
        ],
        "code": {
            "path": "code",
            "sources": [
                "https://lab.example.test/tree?token=REDACTED",
                "https://project.example.test/tree",
            ],
            "saved": 2,
            "skipped": 1,
            "failed": 0,
            "errors": [],
        },
    }
    serialized = manifest_path.read_text(encoding="utf-8")
    assert "secret" not in serialized
    assert "description" not in serialized
    assert "instructors" not in serialized
    assert "learning_objectives" not in serialized


def test_cleanup_legacy_export_files_is_targeted(tmp_path):
    course_dir = tmp_path / "course"
    (course_dir / "code").mkdir(parents=True)
    for relative_path in (
        "index.md",
        "course-overview.md",
        "resources.md",
        "code/.dlaikit-complete.json",
    ):
        (course_dir / relative_path).write_text("legacy", encoding="utf-8")
    user_notes = course_dir / "notes" / "personal.md"
    user_notes.parent.mkdir()
    user_notes.write_text("keep", encoding="utf-8")

    cleanup_legacy_export_files(tmp_path, "course")

    assert not (course_dir / "index.md").exists()
    assert not (course_dir / "course-overview.md").exists()
    assert not (course_dir / "resources.md").exists()
    assert not (course_dir / "code" / ".dlaikit-complete.json").exists()
    assert user_notes.read_text(encoding="utf-8") == "keep"
