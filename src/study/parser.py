import re
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .text import course_slug_from_url, is_lesson_url, normalize_url, slugify


UI_LABELS = {
    "Sign In",
    "Log In",
    "Start Learning",
    "Start Your Course",
    "Show Transcript",
    "Hide Transcript",
}


@dataclass
class ResourceLink:
    title: str
    url: str
    kind: str = "resource"
    lesson_url: str = ""


@dataclass
class LessonInfo:
    index: int
    title: str
    url: str
    kind: str = "lesson"
    duration: str = ""
    module_title: str = ""


@dataclass
class CourseInfo:
    title: str
    slug: str
    source_url: str
    description: str = ""
    level: str = ""
    duration: str = ""
    instructors: List[str] = field(default_factory=list)
    learning_objectives: List[str] = field(default_factory=list)
    lessons: List[LessonInfo] = field(default_factory=list)
    resources: List[ResourceLink] = field(default_factory=list)


def clean_lines(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    lines = []
    for line in soup.get_text("\n").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines, soup


def extract_title(soup, fallback="lesson"):
    for tag_name in ("h1", "h2", "title"):
        for candidate in soup.find_all(tag_name):
            text = candidate.get_text(" ", strip=True)
            if text:
                return re.sub(r"\s+", " ", text)
    return fallback


def extract_transcript_from_lines(lines):
    marker_index = -1
    for index, line in enumerate(lines):
        if line in {"Show Transcript", "Hide Transcript"}:
            marker_index = index
            break

    if marker_index == -1:
        return ""

    transcript = []
    index = marker_index - 1

    while index >= 0 and len(lines[index]) < 40:
        index -= 1

    while index >= 0:
        line = lines[index]
        looks_like_ui = (
            line in UI_LABELS
            or line.startswith("Image")
            or "・" in line
            or line.startswith("http")
        )
        looks_like_transcript = (
            len(line) >= 40
            and not looks_like_ui
            and (re.search(r"[.!?。！？]$", line) or len(line) >= 100)
        )

        if looks_like_transcript:
            transcript.append(line)
            index -= 1
            continue

        if transcript:
            break
        index -= 1

    transcript.reverse()
    return "\n\n".join(transcript)


def extract_lesson_data(html):
    lines, soup = clean_lines(html)
    return extract_title(soup), extract_transcript_from_lines(lines)


def extract_course_info(html, base_url):
    lines, soup = clean_lines(html)
    title = extract_title(soup, fallback=course_slug_from_url(base_url) or "course")
    slug = course_slug_from_url(base_url) or slugify(title, fallback="course")

    return CourseInfo(
        title=title,
        slug=slug,
        source_url=normalize_url(base_url),
        description=_extract_description(soup),
        level=_extract_level(lines),
        duration=_extract_duration(lines),
        instructors=_extract_instructors(lines),
        learning_objectives=_extract_section_items(
            soup,
            {
                "what you will learn",
                "what you'll learn",
                "what you’ll learn",
                "learning objectives",
            },
        ),
        lessons=extract_lesson_infos(soup, base_url),
        resources=extract_resource_links(html, base_url),
    )


def extract_lesson_infos(soup, base_url):
    lessons = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if not is_lesson_url(href):
            continue
        base_course = course_slug_from_url(base_url)
        if base_course and course_slug_from_url(href) != base_course:
            continue
        if href in seen:
            continue

        seen.add(href)
        context = _nearby_text(anchor)
        title = _lesson_title(anchor, href)
        lessons.append(
            LessonInfo(
                index=len(lessons) + 1,
                title=title,
                url=href,
                kind=_infer_lesson_kind(" ".join([title, context])),
                duration=_extract_duration([context]),
                module_title=_nearest_module_title(anchor),
            )
        )

    return lessons


def extract_resource_links(html, base_url, lesson_url=""):
    _, soup = clean_lines(html)
    resources = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, anchor["href"]))
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        if is_lesson_url(href):
            continue

        text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not _looks_like_resource(text, href):
            continue

        key = (href, lesson_url)
        if key in seen:
            continue
        seen.add(key)

        resources.append(
            ResourceLink(
                title=text or _title_from_url(href),
                url=href,
                kind=_infer_resource_kind(text, href),
                lesson_url=normalize_url(lesson_url) if lesson_url else "",
            )
        )

    return resources


def find_lesson_links(soup, base_url):
    base_course = course_slug_from_url(base_url)
    links = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = normalize_url(urljoin(base_url, anchor["href"]))
        if not is_lesson_url(href):
            continue
        if base_course and course_slug_from_url(href) != base_course:
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)

    return links


def _extract_description(soup):
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return re.sub(r"\s+", " ", meta["content"]).strip()

    for paragraph in soup.find_all("p"):
        text = re.sub(r"\s+", " ", paragraph.get_text(" ", strip=True)).strip()
        if len(text) >= 60:
            return text
    return ""


def _extract_level(lines):
    levels = {"beginner", "intermediate", "advanced"}
    for line in lines:
        words = set(re.findall(r"[a-z]+", line.lower()))
        match = levels.intersection(words)
        if match:
            return sorted(match)[0].title()
    return ""


def _extract_duration(lines):
    pattern = re.compile(
        r"\b\d+\s*h\s*\d+\s*m\b|\b\d+\s*[hm]\b|"
        r"\b\d+\s*(?:mins?|minutes?|hrs?|hours?)\b|\b\d{1,2}:\d{2}(?::\d{2})?\b",
        re.IGNORECASE,
    )
    for line in lines:
        match = pattern.search(line)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return ""


def _extract_instructors(lines):
    instructors = []
    stop_words = {
        "what you will learn",
        "what you'll learn",
        "course outline",
        "syllabus",
        "enroll",
    }

    for line in lines:
        if line.lower().startswith("instructors:"):
            names = _split_instructor_names(line.split(":", 1)[1])
            if names:
                return names

    for index, line in enumerate(lines):
        normalized = line.strip().lower().rstrip(":")
        if normalized not in {"instructor", "instructors", "taught by"}:
            continue

        for candidate in lines[index + 1 : index + 8]:
            candidate_text = candidate.strip()
            candidate_key = candidate_text.lower().rstrip(":")
            if candidate_key == "":
                continue
            if candidate_key == ":":
                continue
            if "," in candidate_text:
                instructors.extend(_split_instructor_names(candidate_text))
                break
            if candidate_key in stop_words or len(candidate_text) > 80:
                break
            if candidate_text and candidate_text not in instructors:
                instructors.append(candidate_text)
        break

    return instructors


def _split_instructor_names(text):
    return [
        name.strip()
        for name in re.split(r",| and ", text)
        if name.strip()
    ]


def _extract_section_items(soup, headings):
    for heading in soup.find_all(["h2", "h3"]):
        label = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip().lower()
        if label not in headings:
            continue

        items = []
        for sibling in heading.find_next_siblings():
            if sibling.name in {"h1", "h2", "h3"}:
                break
            for item in sibling.find_all("li"):
                text = re.sub(r"\s+", " ", item.get_text(" ", strip=True)).strip()
                if text:
                    items.append(text)
            if items:
                break
        return items

    return []


def _lesson_title(anchor, href):
    for candidate in anchor.find_all(["h3", "h4", "strong"]):
        text = re.sub(r"\s+", " ", candidate.get_text(" ", strip=True)).strip()
        if text:
            return text

    for line in anchor.get_text("\n", strip=True).splitlines():
        text = re.sub(r"\s+", " ", line).strip()
        if _is_metadata_line(text):
            continue
        if text:
            return text

    parts = [part for part in urlparse(href).path.split("/") if part]
    return parts[-1].replace("-", " ").title() if parts else "Lesson"


def _is_metadata_line(text):
    if not text:
        return True
    lower = text.lower()
    if lower in {"video", "lesson", "code", "code example", "quiz", "assignment"}:
        return True
    if _extract_duration([text]):
        return True
    return False


def _nearby_text(anchor):
    candidate = anchor
    for _ in range(4):
        if candidate.parent is None:
            break
        candidate = candidate.parent
        text = re.sub(r"\s+", " ", candidate.get_text(" ", strip=True)).strip()
        if candidate.name in {"li", "article", "section", "div"} and len(text) <= 800:
            return text
    return re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()


def _nearest_module_title(anchor):
    for parent in anchor.parents:
        if parent.name not in {"section", "article", "main", "body"}:
            continue
        for heading_name in ("h2", "h3"):
            heading = parent.find(heading_name)
            if heading and not heading.find_parent("a"):
                text = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
                if text and text != anchor.get_text(" ", strip=True):
                    return text
    return ""


def _infer_lesson_kind(text):
    lower = text.lower()
    if "graded assignment" in lower or "assignment" in lower:
        return "assignment"
    if "quiz" in lower:
        return "quiz"
    if "code example" in lower or "coding exercise" in lower or "notebook" in lower:
        return "code"
    if "video" in lower:
        return "video"
    return "lesson"


def _looks_like_resource(text, href):
    lower_text = text.lower()
    lower_href = href.lower()
    blocked = {
        "sign in",
        "log in",
        "enroll",
        "start learning",
        "privacy",
        "terms",
        "facebook",
        "linkedin",
        "twitter",
        "copy link",
    }
    if lower_text in blocked:
        return False
    if lower_text == "resources" and urlparse(href).path.rstrip("/") == "/resources":
        return False

    markers = {
        "github",
        "colab",
        "kaggle",
        "notebook",
        "resource",
        "starter",
        "download",
        "source code",
        "open in",
    }
    suffixes = (".ipynb", ".zip", ".pdf", ".py", ".csv", ".json")
    return any(marker in lower_text or marker in lower_href for marker in markers) or lower_href.endswith(suffixes)


def _infer_resource_kind(text, href):
    combined = " ".join([text.lower(), href.lower()])
    if "github" in combined:
        return "repository"
    if "colab" in combined or "notebook" in combined or ".ipynb" in combined:
        return "notebook"
    if "download" in combined or combined.endswith((".zip", ".pdf", ".py", ".csv", ".json")):
        return "download"
    return "resource"


def _title_from_url(url):
    parsed = urlparse(url)
    name = parsed.path.rstrip("/").split("/")[-1]
    return name.replace("-", " ").replace("_", " ").title() if name else parsed.netloc
