#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


STATE_DIRNAME = ".scholarium-notes"
PENDING_DIRNAME = "pending"
STATE_VERSION = 1
DEFAULT_MAX_FILE_CHARS = 24000
NOTEBOOK_OUTPUT_MAX_CHARS = 3000
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
REQUIRED_SECTIONS = (
    "## 学习目标",
    "## 核心概念",
    "## 代码/实践解读",
    "## 关键收获",
    "## 复习问题",
)
TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".txt",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".csv",
    ".gitignore",
}


class LessonNotesError(RuntimeError):
    pass


@dataclass
class Material:
    rel_path: str
    path: Path
    label: str


@dataclass
class NotebookCandidate:
    rel_path: str
    path: Path
    title: str
    order: int


def command_prepare(args):
    export_dir = Path(args.export_dir)
    localized_dir = _localized_dir(export_dir, args.localized_dir)
    output_dir = _output_dir(export_dir, args.output_dir)
    _require_export(export_dir)

    manifest_path = _preferred_path(export_dir, localized_dir, "manifest.json")
    if manifest_path is None:
        raise LessonNotesError("missing manifest.json; run scholarium first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    state_dir = output_dir / STATE_DIRNAME
    pending_dir = state_dir / PENDING_DIRNAME
    output_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)
    _clear_markdown_dir(pending_dir)

    previous_state = _read_state(output_dir)
    lessons = manifest.get("lessons", [])
    results_by_index = {
        int(result.get("index", 0)): result
        for result in manifest.get("results", [])
        if str(result.get("index", "")).isdigit()
    }
    course_docs = _course_docs(export_dir, localized_dir)
    notebooks = _notebook_candidates(export_dir, localized_dir)
    notebook_matches = _match_notebooks(lessons, notebooks)
    shared_materials = _shared_materials(export_dir, localized_dir)
    project_materials = _project_materials(export_dir, localized_dir)

    state_lessons = []
    pending_count = 0
    skipped_count = 0

    for lesson in lessons:
        index = int(lesson.get("index", 0))
        title = str(lesson.get("title") or f"Lesson {index}")
        note_rel = f"{index:02d}-{_slugify(title, fallback='lesson')}.md"
        note_path = output_dir / note_rel
        pending_path = pending_dir / note_rel

        transcript = _transcript_material(export_dir, localized_dir, lesson, results_by_index.get(index, {}))
        notebook = notebook_matches.get(index)
        lesson_materials = []
        if transcript:
            lesson_materials.append(transcript)
        if notebook:
            lesson_materials.append(Material(notebook.rel_path, notebook.path, "matched lesson notebook"))
            lesson_materials.extend(_sibling_materials(notebook.path, export_dir, localized_dir))
            lesson_materials.extend(shared_materials)
        if _is_project_lesson(lesson):
            lesson_materials.extend(project_materials)

        context = _render_context(
            export_dir=export_dir,
            localized_dir=localized_dir,
            output_dir=output_dir,
            note_rel=note_rel,
            lesson=lesson,
            course_docs=course_docs,
            lesson_materials=_unique_materials(lesson_materials),
            warnings=_lesson_warnings(lesson, transcript, notebook, project_materials),
            max_file_chars=args.max_file_chars,
        )
        source_hash = _hash_text(context)

        previous = previous_state.get("lessons", {}).get(str(index), {})
        if (
            not args.force
            and note_path.exists()
            and previous.get("source_hash") == source_hash
            and previous.get("note_path") == note_rel
        ):
            status = "skipped"
            skipped_count += 1
        else:
            pending_path.write_text(context, encoding="utf-8")
            status = "pending"
            pending_count += 1

        state_lessons.append(
            {
                "index": index,
                "title": title,
                "kind": lesson.get("kind", ""),
                "note_path": note_rel,
                "pending_path": f"{STATE_DIRNAME}/{PENDING_DIRNAME}/{note_rel}",
                "source_hash": source_hash,
                "status": status,
            }
        )

    _write_notes_index(output_dir, manifest, state_lessons)
    _write_state(
        output_dir,
        {
            "version": STATE_VERSION,
            "source_dir": str(export_dir.resolve()),
            "localized_dir": str(localized_dir.resolve()) if localized_dir else "",
            "output_dir": str(output_dir.resolve()),
            "required_sections": list(REQUIRED_SECTIONS),
            "lessons": {str(item["index"]): item for item in state_lessons},
        },
    )

    print(f"Source: {export_dir}")
    print(f"Localized source: {localized_dir if localized_dir else '(none)'}")
    print(f"Output: {output_dir}")
    print(f"Prepared: {pending_count} pending, {skipped_count} skipped")
    if pending_count:
        print(f"Write notes from contexts under: {pending_dir}")
    return 0


def command_validate(args):
    export_dir = Path(args.export_dir)
    output_dir = _output_dir(export_dir, args.output_dir)
    _require_export(export_dir)
    state = _read_state(output_dir)
    if not state:
        raise LessonNotesError("missing notes state; run prepare first")

    failures = []
    index_path = output_dir / "index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    if not index_text:
        failures.append("missing notes/index.md")

    for lesson in sorted(state.get("lessons", {}).values(), key=lambda item: item["index"]):
        note_rel = lesson["note_path"]
        note_path = output_dir / note_rel
        if not note_path.exists():
            failures.append(f"missing note: {note_rel}")
            continue
        if note_rel not in index_text:
            failures.append(f"notes index missing link: {note_rel}")
        text = note_path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                failures.append(f"{note_rel} missing required section: {section}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Validation passed")
    return 0


def _localized_dir(export_dir, explicit):
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    path = export_dir / "zh"
    return path if path.exists() else None


def _output_dir(export_dir, explicit):
    return Path(explicit) if explicit else export_dir / "notes"


def _require_export(export_dir):
    if not export_dir.is_dir():
        raise LessonNotesError(f"{export_dir} is not a directory")


def _state_path(output_dir):
    return output_dir / STATE_DIRNAME / "state.json"


def _read_state(output_dir):
    path = _state_path(output_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(output_dir, state):
    path = _state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clear_markdown_dir(path):
    if not path.exists():
        return
    for file_path in path.glob("*.md"):
        file_path.unlink()


def _preferred_path(export_dir, localized_dir, rel_path):
    candidates = []
    if localized_dir:
        candidates.append(localized_dir / rel_path)
    candidates.append(export_dir / rel_path)
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _course_docs(export_dir, localized_dir):
    docs = []
    for rel_path in ("course-overview.md", "resources.md", "index.md"):
        path = _preferred_path(export_dir, localized_dir, rel_path)
        if path:
            docs.append(Material(rel_path, path, "course context"))
    return docs


def _transcript_material(export_dir, localized_dir, lesson, result):
    rel_path = result.get("path") or ""
    if rel_path:
        path = _preferred_path(export_dir, localized_dir, rel_path)
        if path:
            return Material(rel_path, path, "lesson transcript")
    index = int(lesson.get("index", 0))
    pattern = f"transcripts/{index:02d}-*.md"
    for base in (localized_dir, export_dir):
        if not base:
            continue
        matches = sorted(base.glob(pattern))
        if matches:
            return Material(matches[0].relative_to(base).as_posix(), matches[0], "lesson transcript")
    return None


def _preferred_files(export_dir, localized_dir, rel_root):
    chosen = {}
    for base in (export_dir, localized_dir):
        if not base:
            continue
        root = base / rel_root
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                chosen[path.relative_to(base).as_posix()] = path
    return [Material(rel, path, "material") for rel, path in sorted(chosen.items())]


def _notebook_candidates(export_dir, localized_dir):
    candidates = []
    order = 0
    for material in _preferred_files(export_dir, localized_dir, "code/lessons"):
        if material.path.suffix != ".ipynb":
            continue
        order += 1
        candidates.append(
            NotebookCandidate(
                rel_path=material.rel_path,
                path=material.path,
                title=_notebook_title(material.path),
                order=_path_order(material.rel_path, order),
            )
        )
    return sorted(candidates, key=lambda item: item.order)


def _match_notebooks(lessons, notebooks):
    matches = {}
    used = set()
    code_lessons = [
        lesson
        for lesson in lessons
        if lesson.get("kind") == "code" and not _is_project_lesson(lesson)
    ]

    for lesson in code_lessons:
        index = int(lesson.get("index", 0))
        title = str(lesson.get("title") or "")
        best = None
        best_score = 0.0
        for notebook in notebooks:
            if notebook.rel_path in used:
                continue
            score = _title_score(title, notebook.title)
            if score > best_score:
                best = notebook
                best_score = score
        if best is not None and best_score >= 0.32:
            matches[index] = best
            used.add(best.rel_path)

    remaining = [notebook for notebook in notebooks if notebook.rel_path not in used]
    for lesson, notebook in zip(code_lessons, remaining):
        index = int(lesson.get("index", 0))
        if index not in matches:
            matches[index] = notebook
    return matches


def _notebook_title(path):
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path.stem
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "markdown":
            continue
        source = _cell_source(cell)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return re.sub(r"^#+\s*", "", stripped).strip()
    return path.stem


def _path_order(rel_path, fallback):
    match = re.search(r"/L(\d+)/", rel_path, flags=re.IGNORECASE)
    return int(match.group(1)) if match else fallback


def _title_score(left, right):
    left_norm = _normalize_title(left)
    right_norm = _normalize_title(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _normalize_title(text):
    text = str(text).lower()
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"^l\d+\s*[:：-]\s*", "", text.strip())
    return "".join(ch for ch in text if ch.isalnum())


def _shared_materials(export_dir, localized_dir):
    materials = []
    for material in _preferred_files(export_dir, localized_dir, "code/lessons/lib"):
        if material.path.suffix in {".py", ".md", ".txt"}:
            material.label = "shared lesson code"
            materials.append(material)
    for rel_path in ("code/lessons/helper.py", "code/lessons/requirements.txt"):
        path = _preferred_path(export_dir, localized_dir, rel_path)
        if path:
            materials.append(Material(rel_path, path, "shared lesson code"))
    return materials


def _project_materials(export_dir, localized_dir):
    materials = []
    for material in _preferred_files(export_dir, localized_dir, "code/project"):
        if material.path.suffix in {".ipynb", ".md", ".py", ".txt"} or material.path.name == "requirements.txt":
            material.label = "project material"
            materials.append(material)
        elif material.path.suffix:
            material.label = "project asset"
            materials.append(material)
    return materials


def _sibling_materials(notebook_path, export_dir, localized_dir):
    base = _base_for_path(notebook_path, export_dir, localized_dir)
    if base is None:
        return []
    rel_dir = notebook_path.parent.relative_to(base).as_posix()
    materials = []
    for material in _preferred_files(export_dir, localized_dir, rel_dir):
        if material.path == notebook_path:
            continue
        if material.path.suffix in {".py", ".md", ".txt"} or material.path.name == "requirements.txt":
            material.label = "lesson support file"
            materials.append(material)
        elif material.path.suffix in {".csv", ".json"}:
            material.label = "lesson data file"
            materials.append(material)
    return materials


def _base_for_path(path, export_dir, localized_dir):
    for base in (localized_dir, export_dir):
        if not base:
            continue
        try:
            path.resolve().relative_to(base.resolve())
            return base
        except ValueError:
            continue
    return None


def _is_project_lesson(lesson):
    text = "{} {}".format(lesson.get("title", ""), lesson.get("kind", "")).lower()
    keywords = ("project", "hands-on", "assignment", "graded", "动手", "项目", "作业")
    return any(keyword in text for keyword in keywords)


def _lesson_warnings(lesson, transcript, notebook, project_materials):
    warnings = []
    if transcript is None:
        warnings.append("No transcript file was found for this lesson.")
    if lesson.get("kind") == "code" and not _is_project_lesson(lesson) and notebook is None:
        warnings.append("No lesson notebook was confidently matched.")
    if _is_project_lesson(lesson) and not project_materials:
        warnings.append("No project materials were found.")
    return warnings


def _render_context(
    export_dir,
    localized_dir,
    output_dir,
    note_rel,
    lesson,
    course_docs,
    lesson_materials,
    warnings,
    max_file_chars,
):
    index = int(lesson.get("index", 0))
    title = str(lesson.get("title") or f"Lesson {index}")
    lines = [
        f"# Lesson Context: {index:02d}. {title}",
        "",
        "<!-- scholarium-notes-context: zh-CN -->",
        "",
        f"Output note: {output_dir.name}/{note_rel}",
        f"Lesson index: {index}",
        f"Lesson title: {title}",
        f"Lesson kind: {lesson.get('kind', '')}",
        f"Duration: {lesson.get('duration', '')}",
        f"Source URL: {lesson.get('url', '')}",
        "",
        "## Writing Contract",
        "",
        "Write a comprehensive Chinese Markdown study note at the output path above. Include these exact sections:",
    ]
    lines.extend(f"- {section}" for section in REQUIRED_SECTIONS)
    lines.extend(
        [
            "",
            "Use short code snippets only. Cite source paths when discussing code.",
            "If adding outside knowledge, mark it as 补充理解.",
            "",
        ]
    )
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    lines.extend(["## Course Context", ""])
    for material in course_docs:
        lines.extend(_render_material(material, export_dir, localized_dir, max_file_chars // 2))

    lines.extend(["## Lesson Materials", ""])
    if lesson_materials:
        for material in lesson_materials:
            lines.extend(_render_material(material, export_dir, localized_dir, max_file_chars))
    else:
        lines.append("No lesson-specific materials were found.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_material(material, export_dir, localized_dir, max_chars):
    rel_display = material.rel_path
    source = "zh" if localized_dir and _is_relative_to(material.path, localized_dir) else "original"
    lines = [
        f"### {material.label}: `{rel_display}`",
        "",
        f"Source set: {source}",
        "",
    ]
    if material.path.suffix == ".ipynb":
        content = _render_notebook(material.path, max_chars)
        lines.extend(["```markdown", content.rstrip(), "```", ""])
    elif _is_text_file(material.path):
        content = _read_limited(material.path, max_chars)
        fence = _fence_for(material.path)
        lines.extend([f"```{fence}", content.rstrip(), "```", ""])
    else:
        lines.extend(["Binary or non-text asset; use path only.", ""])
    return lines


def _render_notebook(path, max_chars):
    try:
        notebook = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Could not parse notebook: {exc}"
    parts = []
    total = 0
    for index, cell in enumerate(notebook.get("cells", []), start=1):
        cell_type = cell.get("cell_type", "")
        source = _cell_source(cell).strip()
        outputs = cell.get("outputs") or []
        if not source and not outputs:
            continue
        block = f"<!-- cell {index}: {cell_type} -->\n"
        if cell_type == "code":
            execution_count = cell.get("execution_count")
            if execution_count is not None:
                block += f"<!-- execution_count: {execution_count} -->\n"
            block += "```python\n{}\n```\n".format(source)
            output_text = _render_notebook_outputs(outputs)
            if output_text:
                block += "\nNotebook outputs:\n{}\n".format(output_text)
        else:
            block += source + "\n"
        if total + len(block) > max_chars:
            parts.append("\n[truncated notebook content]\n")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts).strip()


def _render_notebook_outputs(outputs):
    rendered = []
    for index, output in enumerate(outputs, start=1):
        if not isinstance(output, dict):
            continue
        output_type = str(output.get("output_type") or "output")
        text = _notebook_output_text(output)
        if not text:
            continue
        rendered.append(f"Output {index} ({output_type}):\n{text}")
    return "\n\n".join(rendered)


def _notebook_output_text(output):
    output_type = output.get("output_type")
    if output_type == "stream":
        name = output.get("name") or "stream"
        text = _clean_notebook_output_text(output.get("text", ""))
        if not text:
            return ""
        return _limit_text(f"[{name}]\n{text}", NOTEBOOK_OUTPUT_MAX_CHARS, "[truncated notebook stream output]")

    if output_type == "error":
        ename = output.get("ename") or "Error"
        evalue = output.get("evalue") or ""
        traceback = _clean_notebook_output_text(output.get("traceback", ""))
        summary = f"{ename}: {evalue}".rstrip(": ")
        if traceback:
            summary = f"{summary}\n{traceback}"
        return _limit_text(summary, NOTEBOOK_OUTPUT_MAX_CHARS, "[truncated notebook error output]")

    if output_type in {"execute_result", "display_data"}:
        data = output.get("data") or {}
        text = _mime_bundle_text(data)
        if text:
            return _limit_text(text, NOTEBOOK_OUTPUT_MAX_CHARS, "[truncated notebook rich output]")
        omitted = _omitted_mime_types(data)
        if omitted:
            return "Binary/rich display output omitted: {}".format(", ".join(omitted))
    return ""


def _mime_bundle_text(data):
    if not isinstance(data, dict):
        return ""
    for mime_type in ("text/plain", "text/markdown", "application/json", "text/html"):
        if mime_type not in data:
            continue
        value = data[mime_type]
        if mime_type == "text/html":
            value = _strip_html(_source_text(value))
        elif mime_type == "application/json":
            value = json.dumps(value, ensure_ascii=False, indent=2)
        return _clean_notebook_output_text(value)
    return ""


def _omitted_mime_types(data):
    if not isinstance(data, dict):
        return []
    return sorted(mime_type for mime_type in data if mime_type.startswith("image/") or mime_type.startswith("application/"))


def _source_text(value):
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _clean_notebook_output_text(value):
    text = _source_text(value)
    text = ANSI_ESCAPE_RE.sub("", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"\bid=[A-Za-z0-9_-]{8,}\b", "id=<redacted>", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_html(text):
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _limit_text(text, max_chars, marker):
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"\n\n{marker}"


def _cell_source(cell):
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _is_text_file(path):
    return path.suffix in TEXT_EXTENSIONS or path.name in TEXT_EXTENSIONS


def _read_limited(path, max_chars):
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n[truncated file content]\n"


def _fence_for(path):
    if path.suffix == ".py":
        return "python"
    if path.suffix == ".json":
        return "json"
    if path.suffix == ".md":
        return "markdown"
    if path.suffix == ".csv":
        return "csv"
    return ""


def _is_relative_to(path, base):
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _unique_materials(materials):
    seen = set()
    unique = []
    for material in materials:
        key = material.path.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique.append(material)
    return unique


def _write_notes_index(output_dir, manifest, lessons):
    title = manifest.get("course", {}).get("title") or "Course"
    lines = [
        f"# {title} 学习笔记",
        "",
        "这些笔记由本地导出的课程材料综合生成，用于个人学习复习。",
        "",
        "## Lessons",
        "",
    ]
    for lesson in sorted(lessons, key=lambda item: item["index"]):
        metadata = []
        if lesson.get("kind"):
            metadata.append(str(lesson["kind"]))
        suffix = f" ({', '.join(metadata)})" if metadata else ""
        lines.append(f"- [{lesson['index']:02d}. {lesson['title']}]({lesson['note_path']}){suffix}")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hash_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slugify(text, fallback="note"):
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or fallback


def build_parser():
    parser = argparse.ArgumentParser(description="Prepare and validate Scholarium lesson notes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create per-lesson note context packs.")
    prepare.add_argument("export_dir")
    prepare.add_argument("--localized-dir", default="")
    prepare.add_argument("--output-dir", default="")
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--max-file-chars", type=int, default=DEFAULT_MAX_FILE_CHARS)
    prepare.set_defaults(func=command_prepare)

    validate = subparsers.add_parser("validate", help="Validate generated lesson notes.")
    validate.add_argument("export_dir")
    validate.add_argument("--output-dir", default="")
    validate.set_defaults(func=command_validate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LessonNotesError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
