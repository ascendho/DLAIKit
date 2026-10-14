import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .parser import CourseInfo
from .text import slugify


LEGACY_EXPORT_FILES = (
    "index.md",
    "course-overview.md",
    "resources.md",
    "code/.dlaikit-complete.json",
)


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


def cleanup_legacy_export_files(output_root, course_slug):
    """Remove only files that older DLAIKit versions generated themselves."""
    course_dir = Path(output_root) / course_slug
    for relative_path in LEGACY_EXPORT_FILES:
        path = course_dir / relative_path
        if path.is_file():
            path.unlink()


def write_lesson(output_root, course_slug, index, title, url, transcript):
    course_dir = Path(output_root) / course_slug
    transcripts_dir = course_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    filename = "{:02d}-{}.md".format(index, slugify(title, fallback="lesson"))
    path = transcripts_dir / filename

    content = "# {}\n\nSource: {}\n\n{}\n".format(title, url, transcript.strip())
    path.write_text(content, encoding="utf-8")
    return path


def write_manifest(output_root, course_info: CourseInfo, results, code_assets=None):
    course_dir = Path(output_root) / course_info.slug
    course_dir.mkdir(parents=True, exist_ok=True)
    path = course_dir / "manifest.json"

    payload = {
        "schema_version": 1,
        "course": {
            "title": course_info.title,
            "slug": course_info.slug,
            "source_url": course_info.source_url,
        },
        "lessons": [
            {
                "index": result.index,
                "title": result.title,
                "source_url": result.url,
                "status": result.status,
                "transcript_path": _relative_path_label(result.path, course_dir)
                if result.path
                else "",
                "message": result.message,
            }
            for result in results
        ],
    }
    if code_assets is not None:
        payload["code"] = _code_assets_payload(course_dir, code_assets)

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _code_assets_payload(course_dir, code_assets):
    sources = list(code_assets.source_urls)
    if not sources and code_assets.source_url:
        sources = [code_assets.source_url]
    return {
        "path": _relative_path_label(code_assets.output_dir, course_dir),
        "sources": [_redact_url(source) for source in sources],
        "saved": code_assets.saved,
        "skipped": code_assets.skipped,
        "failed": code_assets.failed,
        "errors": [_redact_url(error) for error in code_assets.errors],
    }


def _relative_path_label(path, base=None):
    path = Path(path)
    if base is not None:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _redact_url(text):
    from .code_assets import redact_url

    return redact_url(text)
