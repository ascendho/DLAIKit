import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse


def normalize_url(url):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def course_slug_from_url(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        index = parts.index("courses")
    except ValueError:
        return ""

    if index + 1 >= len(parts):
        return ""
    return slugify(parts[index + 1], fallback="course")


def is_lesson_url(url):
    parts = [part for part in urlparse(url).path.split("/") if part]
    return "courses" in parts and "lesson" in parts


def slugify(text, fallback="item", max_length=80):
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    if not text:
        text = fallback
    return text[:max_length].strip("-._") or fallback


def find_project_root(start=None):
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if (
            (candidate / "pyproject.toml").exists()
            and (candidate / "src" / "study").exists()
        ):
            return candidate

    return current


def resolve_project_path(path, start=None):
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return find_project_root(start) / path
