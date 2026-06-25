import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .parser import CourseInfo
from .text import slugify


@dataclass
class LessonResult:
    index: int
    url: str
    title: str
    status: str
    path: Optional[Path] = None
    message: str = ""
    kind: str = "lesson"
    duration: str = ""
    module_title: str = ""


def write_lesson(output_root, course_slug, index, title, url, transcript):
    course_dir = Path(output_root) / course_slug
    transcripts_dir = course_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    filename = "{:02d}-{}.md".format(index, slugify(title, fallback="lesson"))
    path = transcripts_dir / filename

    content = "# {}\n\nSource: {}\n\n{}\n".format(title, url, transcript.strip())
    path.write_text(content, encoding="utf-8")
    return path


def write_index(output_root, course_slug, start_url, results, course_info=None, code_assets=None):
    course_dir = Path(output_root) / course_slug
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "index.md"

    lines = [
        "# {}".format(course_info.title if course_info else "Course Transcripts"),
        "",
        "Source: {}".format(start_url),
        "",
    ]

    if code_assets is not None:
        lines.extend(_format_code_assets_section(code_assets))

    lines.extend(["## Lessons", ""])

    for result in results:
        label = "{:02d}. {}".format(result.index, result.title)
        metadata = _format_result_metadata(result)
        if result.path is not None:
            lesson_path = _relative_path_label(result.path, course_dir)
            lines.append("- [{}]({}) - {}{}".format(label, lesson_path, result.status, metadata))
        else:
            message = " - {}".format(result.message) if result.message else ""
            lines.append("- {} - {}{}{}".format(label, result.status, metadata, message))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_course_overview(output_root, course_info: CourseInfo):
    course_dir = Path(output_root) / course_info.slug
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "course-overview.md"

    lines = [
        "# {}".format(course_info.title),
        "",
        "Source: {}".format(course_info.source_url),
        "",
    ]

    if course_info.description:
        lines.extend([course_info.description, ""])

    facts = []
    if course_info.level:
        facts.append("Level: {}".format(course_info.level))
    if course_info.duration:
        facts.append("Duration: {}".format(course_info.duration))
    if course_info.instructors:
        facts.append("Instructors: {}".format(", ".join(course_info.instructors)))
    if facts:
        lines.extend(["## Course Facts", ""])
        lines.extend("- {}".format(fact) for fact in facts)
        lines.append("")

    if course_info.learning_objectives:
        lines.extend(["## Learning Objectives", ""])
        lines.extend("- {}".format(item) for item in course_info.learning_objectives)
        lines.append("")

    if course_info.lessons:
        lines.extend(["## Course Outline", ""])
        for lesson in course_info.lessons:
            metadata = _format_lesson_metadata(lesson.kind, lesson.duration)
            lines.append("- {:02d}. [{}]({}){}".format(lesson.index, lesson.title, lesson.url, metadata))
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def write_resources(output_root, course_info: CourseInfo):
    course_dir = Path(output_root) / course_info.slug
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "resources.md"

    lines = [
        "# Course Resources",
        "",
        "Source: {}".format(course_info.source_url),
        "",
    ]

    study_pages = [
        lesson
        for lesson in course_info.lessons
        if lesson.kind in {"code", "quiz", "assignment"}
    ]
    if study_pages:
        lines.extend(["## Course Pages", ""])
        for lesson in study_pages:
            metadata = _format_lesson_metadata(lesson.kind, lesson.duration)
            lines.append("- {:02d}. [{}]({}){}".format(lesson.index, lesson.title, lesson.url, metadata))
        lines.append("")

    if course_info.resources:
        lines.extend(["## External Links", ""])
        for resource in course_info.resources:
            label = resource.kind.replace("_", " ").title()
            suffix = " - from {}".format(resource.lesson_url) if resource.lesson_url else ""
            lines.append("- [{}]({}) - {}{}".format(resource.title, resource.url, label, suffix))
        lines.append("")

    if not study_pages and not course_info.resources:
        lines.extend(["No dedicated resource links were found.", ""])

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def write_manifest(output_root, course_info: CourseInfo, results, code_assets=None):
    course_dir = Path(output_root) / course_info.slug
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "manifest.json"

    payload = {
        "course": {
            "title": course_info.title,
            "slug": course_info.slug,
            "source_url": course_info.source_url,
            "description": course_info.description,
            "level": course_info.level,
            "duration": course_info.duration,
            "instructors": course_info.instructors,
            "learning_objectives": course_info.learning_objectives,
        },
        "lessons": [
            {
                "index": lesson.index,
                "title": lesson.title,
                "url": lesson.url,
                "kind": lesson.kind,
                "duration": lesson.duration,
                "module_title": lesson.module_title,
            }
            for lesson in course_info.lessons
        ],
        "resources": [
            {
                "title": resource.title,
                "url": resource.url,
                "kind": resource.kind,
                "lesson_url": resource.lesson_url,
            }
            for resource in course_info.resources
        ],
        "results": [
            {
                "index": result.index,
                "title": result.title,
                "url": result.url,
                "status": result.status,
                "path": _relative_path_label(result.path, course_dir) if result.path else "",
                "message": result.message,
                "kind": result.kind,
                "duration": result.duration,
                "module_title": result.module_title,
            }
            for result in results
        ],
    }
    if code_assets is not None:
        payload["code_assets"] = _code_assets_payload(course_dir, code_assets)

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _format_result_metadata(result):
    return _format_lesson_metadata(result.kind, result.duration)


def _format_lesson_metadata(kind, duration):
    parts = []
    if kind and kind != "lesson":
        parts.append(kind)
    if duration:
        parts.append(duration)
    return " ({})".format(", ".join(parts)) if parts else ""


def _format_code_assets_section(code_assets):
    label = _relative_path_label(code_assets.output_dir)
    lines = [
        "## Code",
        "",
        "Source: {}".format(_redact_url(code_assets.source_url)),
        "",
        "- Directory: [{}]({}/)".format(label, label),
        "- Saved: {}  Skipped: {}  Failed: {}".format(
            code_assets.saved,
            code_assets.skipped,
            code_assets.failed,
        ),
    ]
    lines.extend("- Error: {}".format(_redact_url(error)) for error in code_assets.errors)
    lines.append("")
    return lines


def _code_assets_payload(course_dir, code_assets):
    return {
        "source_url": _redact_url(code_assets.source_url),
        "path": _relative_path_label(code_assets.output_dir, course_dir),
        "saved": code_assets.saved,
        "skipped": code_assets.skipped,
        "failed": code_assets.failed,
        "errors": [_redact_url(error) for error in code_assets.errors],
        "files": [
            {
                "path": file.path,
                "status": file.status,
                "bytes": file.bytes,
                "message": file.message,
            }
            for file in code_assets.files
        ],
    }


def _relative_path_label(path, base=None):
    path = Path(path)
    if base is None:
        return path.name
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _redact_url(text):
    return re.sub(r"([?&]token=)[^&\s\"']+", r"\1REDACTED", str(text))
