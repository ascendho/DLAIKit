#!/usr/bin/env python3
import argparse
import ast
import hashlib
import io
import json
import shutil
import sys
import tokenize
from pathlib import Path


LOCALIZED_MARKER = "<!-- dlaikit-localized: zh-CN -->"
STATE_VERSION = 1
DEFAULT_MAX_ITEMS = 20
DEFAULT_MAX_CHARS = 12000
TARGET_LANGUAGE = "zh-CN"
STATE_DIRNAME = ".dlaikit-localize"
GENERATED_TOP_LEVEL_DIRS = {"zh", "notes"}
GENERATED_STATE_DIRS = {STATE_DIRNAME, ".dlaikit-notes"}


class LocalizeError(RuntimeError):
    pass


def command_prepare(args):
    source_dir = Path(args.export_dir)
    output_dir = _output_dir(source_dir, args.output_dir)
    _require_source_output(source_dir, output_dir)

    previous_state = _read_state(output_dir)
    state_dir = output_dir / STATE_DIRNAME
    pending_dir = state_dir / "pending"
    translated_dir = state_dir / "translated"

    output_dir.mkdir(parents=True, exist_ok=True)
    pending_dir.mkdir(parents=True, exist_ok=True)
    translated_dir.mkdir(parents=True, exist_ok=True)
    _clear_json_dir(pending_dir)

    files = {}
    all_items = []
    copied = 0
    skipped = 0

    for path in sorted(source_dir.rglob("*")):
        if path.is_dir() or _should_skip_source_path(source_dir, output_dir, path):
            continue

        relative_path = path.relative_to(source_dir).as_posix()
        target_path = output_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_hash = _sha256(path)

        previous_file = previous_state.get("files", {}).get(relative_path, {})
        if (
            previous_file.get("source_hash") == source_hash
            and previous_file.get("status") == "applied"
            and target_path.exists()
        ):
            files[relative_path] = previous_file
            skipped += 1
            continue

        file_items = _extract_items(path, relative_path)
        if not file_items:
            shutil.copy2(path, target_path)
            files[relative_path] = {
                "kind": "copy",
                "source_hash": source_hash,
                "status": "applied",
                "items": [],
            }
            copied += 1
            continue

        files[relative_path] = {
            "kind": _file_kind(path),
            "source_hash": source_hash,
            "status": "pending",
            "items": [_item_ref(item) for item in file_items],
        }
        all_items.extend(file_items)

    chunks = _build_chunks(all_items, args.max_items, args.max_chars)
    pending = 0
    preserved = 0
    state_chunks = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        pending_path = pending_dir / f"{chunk_id}.json"
        translated_path = translated_dir / f"{chunk_id}.json"
        expected_ids = {item["id"] for item in chunk["items"]}

        if translated_path.exists() and _translation_ids(translated_path) == expected_ids:
            status = "translated"
            preserved += 1
        else:
            if translated_path.exists():
                translated_path.unlink()
            _write_json(pending_path, chunk)
            status = "pending"
            pending += 1

        state_chunks.append(
            {
                "chunk_id": chunk_id,
                "status": status,
                "item_ids": sorted(expected_ids),
                "pending_path": f"{STATE_DIRNAME}/pending/{chunk_id}.json",
                "translated_path": f"{STATE_DIRNAME}/translated/{chunk_id}.json",
            }
        )

    state = {
        "version": STATE_VERSION,
        "target_language": TARGET_LANGUAGE,
        "source_dir": str(source_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "files": files,
        "chunks": state_chunks,
    }
    _write_state(output_dir, state)

    print(f"Source: {source_dir}")
    print(f"Output: {output_dir}")
    print(
        "Prepared: {} chunks pending, {} chunks preserved, {} files copied, {} files skipped".format(
            pending, preserved, copied, skipped
        )
    )
    if pending:
        print(f"Translate pending chunks under: {pending_dir}")
        print(f"Write translated chunks under: {translated_dir}")
    return 0


def command_apply(args):
    source_dir = Path(args.export_dir)
    output_dir = _output_dir(source_dir, args.output_dir)
    _require_source_output(source_dir, output_dir)
    state = _read_state(output_dir)
    if not state:
        raise LocalizeError("missing state; run prepare first")

    translations = _load_translations(output_dir, state)
    applied = 0
    for relative_path, info in sorted(state["files"].items()):
        if info.get("kind") == "copy":
            continue

        source_path = source_dir / relative_path
        target_path = output_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if info["kind"] == "markdown":
            item = info["items"][0]
            translated = translations[item["id"]]
            target_path.write_text(
                _wrap_markdown(translated, source_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
        elif info["kind"] == "python":
            target_path.write_text(
                _apply_python(source_path.read_text(encoding="utf-8"), info["items"], translations),
                encoding="utf-8",
            )
        elif info["kind"] == "notebook":
            target_path.write_text(
                _apply_notebook(source_path.read_text(encoding="utf-8"), info["items"], translations),
                encoding="utf-8",
            )
        else:
            raise LocalizeError(f"unsupported file kind for {relative_path}: {info['kind']}")

        info["status"] = "applied"
        applied += 1

    for chunk in state["chunks"]:
        chunk["status"] = "applied"
    _write_state(output_dir, state)
    print(f"Applied localized content for {applied} files")
    return 0


def command_validate(args):
    source_dir = Path(args.export_dir)
    output_dir = _output_dir(source_dir, args.output_dir)
    _require_source_output(source_dir, output_dir)
    state = _read_state(output_dir)
    if not state:
        raise LocalizeError("missing state; run prepare first")

    failures = []
    for relative_path, info in sorted(state["files"].items()):
        source_path = source_dir / relative_path
        target_path = output_dir / relative_path
        if not target_path.exists():
            failures.append(f"missing target: {relative_path}")
            continue

        if info.get("kind") == "copy":
            if source_path.is_file() and not _same_bytes(source_path, target_path):
                failures.append(f"copied file differs: {relative_path}")
            continue

        text = target_path.read_text(encoding="utf-8")
        if info["kind"] == "markdown":
            if LOCALIZED_MARKER not in text or "<summary>English original</summary>" not in text:
                failures.append(f"markdown missing bilingual wrapper: {relative_path}")
        elif info["kind"] == "python":
            try:
                compile(text, str(target_path), "exec")
            except SyntaxError as exc:
                failures.append(f"python syntax error in {relative_path}: {exc}")
        elif info["kind"] == "notebook":
            try:
                notebook = json.loads(text)
            except json.JSONDecodeError as exc:
                failures.append(f"notebook JSON error in {relative_path}: {exc}")
            else:
                failures.extend(_validate_notebook_markdown(notebook, relative_path, info))

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Validation passed")
    return 0


def _output_dir(source_dir, explicit_output):
    return Path(explicit_output) if explicit_output else source_dir / "zh"


def _require_source_output(source_dir, output_dir):
    if not source_dir.is_dir():
        raise LocalizeError(f"{source_dir} is not a directory")
    if source_dir.resolve() == output_dir.resolve():
        raise LocalizeError("output directory must be different from source directory")


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
    _write_json(path, state)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _clear_json_dir(path):
    if not path.exists():
        return
    for file_path in path.glob("*.json"):
        file_path.unlink()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _same_bytes(left, right):
    return left.read_bytes() == right.read_bytes()


def _is_relative_to(path, base):
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _should_skip_source_path(source_dir, output_dir, path):
    if _is_relative_to(path, output_dir):
        return True
    try:
        relative = path.relative_to(source_dir)
    except ValueError:
        return False
    parts = relative.parts
    if not parts:
        return False
    if parts[0] in GENERATED_TOP_LEVEL_DIRS:
        return True
    return any(part in GENERATED_STATE_DIRS for part in parts)


def _file_kind(path):
    if path.suffix == ".md":
        return "markdown"
    if path.suffix == ".py":
        return "python"
    if path.suffix == ".ipynb":
        return "notebook"
    return "copy"


def _extract_items(path, relative_path):
    if path.suffix == ".md":
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        return [
            _make_item(
                relative_path,
                "markdown",
                {"type": "file"},
                text,
            )
        ]
    if path.suffix == ".py":
        return _extract_python_items(path.read_text(encoding="utf-8"), relative_path)
    if path.suffix == ".ipynb":
        return _extract_notebook_items(path.read_text(encoding="utf-8"), relative_path)
    return []


def _make_item(source_path, kind, locator, text):
    key = f"{source_path}:{kind}:{json.dumps(locator, sort_keys=True)}:{text}"
    return {
        "id": f"item-{_hash_text(key)}",
        "kind": kind,
        "source_path": source_path,
        "locator": locator,
        "text": text,
    }


def _item_ref(item):
    return {
        "id": item["id"],
        "kind": item["kind"],
        "locator": item["locator"],
        "source_hash": _hash_text(item["text"]),
    }


def _extract_python_items(text, relative_path, cell_index=None):
    comments = []
    docstring_lines = _docstring_start_lines(text)
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT and _should_translate_comment(token):
                source = _comment_text(token.string)
                if not source:
                    continue
                token_index = len([item for item in comments if item["kind"].endswith("comment")])
                kind = "notebook-code-comment" if cell_index is not None else "python-comment"
                locator = {
                    "type": "code-comment",
                    "token_index": token_index,
                    "line": token.start[0],
                    "column": token.start[1],
                }
                if cell_index is not None:
                    locator["cell_index"] = cell_index
                comments.append(_make_item(relative_path, kind, locator, source))
            elif token.type == tokenize.STRING and token.start[0] in docstring_lines:
                source = _literal_string_value(token.string)
                if not source:
                    continue
                token_index = len([item for item in comments if item["kind"].endswith("docstring")])
                kind = "notebook-code-docstring" if cell_index is not None else "python-docstring"
                locator = {
                    "type": "code-docstring",
                    "token_index": token_index,
                    "line": token.start[0],
                    "column": token.start[1],
                }
                if cell_index is not None:
                    locator["cell_index"] = cell_index
                comments.append(_make_item(relative_path, kind, locator, source))
    except tokenize.TokenError:
        return []
    return comments


def _extract_notebook_items(text, relative_path):
    notebook = json.loads(text)
    items = []
    for cell_index, cell in enumerate(notebook.get("cells", [])):
        source = _cell_source_text(cell)
        if cell.get("cell_type") == "markdown" and source.strip():
            items.append(
                _make_item(
                    relative_path,
                    "notebook-markdown",
                    {"type": "notebook-markdown", "cell_index": cell_index},
                    source,
                )
            )
        elif cell.get("cell_type") == "code":
            items.extend(_extract_python_items(source, relative_path, cell_index=cell_index))
    return items


def _docstring_start_lines(text):
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    lines = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(getattr(first, "value", None), ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.add(first.lineno)
    return lines


def _should_translate_comment(token):
    text = token.string.strip()
    if not text.startswith("#"):
        return False
    if token.start[0] <= 2 and (text.startswith("#!") or "coding" in text.lower()):
        return False
    lowered = text.lower()
    pragma_markers = ("noqa", "type: ignore", "pylint:", "pragma:", "fmt:", "ruff:")
    return not any(marker in lowered for marker in pragma_markers)


def _comment_text(comment):
    return comment.lstrip("#").strip()


def _literal_string_value(token_string):
    try:
        value = ast.literal_eval(token_string)
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _build_chunks(items, max_items, max_chars):
    chunks = []
    current = []
    current_chars = 0
    for item in items:
        item_chars = len(item["text"])
        if current and (len(current) >= max_items or current_chars + item_chars > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        chunks.append(current)

    payloads = []
    for index, chunk_items in enumerate(chunks, start=1):
        payloads.append(
            {
                "chunk_id": f"chunk-{index:04d}",
                "target_language": TARGET_LANGUAGE,
                "items": chunk_items,
            }
        )
    return payloads


def _translation_ids(translated_path):
    try:
        payload = json.loads(translated_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {item.get("id") for item in payload.get("items", [])}


def _load_translations(output_dir, state):
    translated_dir = output_dir / STATE_DIRNAME / "translated"
    translations = {}
    missing = []
    for chunk in state.get("chunks", []):
        path = translated_dir / f"{chunk['chunk_id']}.json"
        if not path.exists():
            missing.append(chunk["chunk_id"])
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        expected = set(chunk["item_ids"])
        received = {item.get("id") for item in payload.get("items", [])}
        if expected != received:
            raise LocalizeError(
                "translation ids mismatch for {}: missing={}, extra={}".format(
                    chunk["chunk_id"],
                    sorted(expected - received),
                    sorted(received - expected),
                )
            )
        for item in payload.get("items", []):
            translations[item["id"]] = str(item.get("text", ""))
    if missing:
        raise LocalizeError("missing translated chunks: {}".format(", ".join(missing)))
    return translations


def _wrap_markdown(chinese, original):
    if LOCALIZED_MARKER in original:
        return original
    return (
        f"{LOCALIZED_MARKER}\n\n"
        f"{chinese.strip()}\n\n"
        "---\n\n"
        "<details>\n"
        "<summary>English original</summary>\n\n"
        f"{original.rstrip()}\n"
        "</details>\n"
    )


def _apply_python(text, item_refs, translations, cell_index=None):
    items_by_key = {}
    for item in item_refs:
        locator = item["locator"]
        if cell_index is not None and locator.get("cell_index") != cell_index:
            continue
        key = (locator["type"], locator["token_index"])
        items_by_key[key] = item["id"]

    docstring_lines = _docstring_start_lines(text)
    comment_index = 0
    docstring_index = 0
    replacements = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            replacement = None
            if token.type == tokenize.COMMENT and _should_translate_comment(token):
                item_id = items_by_key.get(("code-comment", comment_index))
                comment_index += 1
                if item_id:
                    replacement = "# {}".format(translations[item_id].lstrip("#").strip())
            elif token.type == tokenize.STRING and token.start[0] in docstring_lines:
                item_id = items_by_key.get(("code-docstring", docstring_index))
                docstring_index += 1
                if item_id:
                    replacement = _quote_docstring(translations[item_id].strip())

            if replacement is None:
                continue
            replacements.append((token.start, token.end, replacement))
    except tokenize.TokenError:
        return text
    return _replace_token_spans(text, replacements)


def _replace_token_spans(text, replacements):
    if not replacements:
        return text
    lines = text.splitlines(keepends=True)
    offsets = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line)

    def offset(position):
        line, column = position
        if line <= 0:
            return column
        if line > len(offsets):
            return len(text)
        return offsets[line - 1] + column

    result = text
    spans = [(offset(start), offset(end), replacement) for start, end, replacement in replacements]
    for start, end, replacement in sorted(spans, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _quote_docstring(text):
    return '"""{}"""'.format(text.replace('"""', '\\"\\"\\"'))


def _apply_notebook(text, item_refs, translations):
    notebook = json.loads(text)
    markdown_items = {
        item["locator"]["cell_index"]: item["id"]
        for item in item_refs
        if item["locator"]["type"] == "notebook-markdown"
    }
    for cell_index, cell in enumerate(notebook.get("cells", [])):
        source = _cell_source_text(cell)
        if cell.get("cell_type") == "markdown" and cell_index in markdown_items:
            item_id = markdown_items[cell_index]
            _set_cell_source(cell, _wrap_markdown(translations[item_id], source))
        elif cell.get("cell_type") == "code":
            _set_cell_source(cell, _apply_python(source, item_refs, translations, cell_index=cell_index))
    return json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"


def _validate_notebook_markdown(notebook, relative_path, info):
    failures = []
    cells = notebook.get("cells", [])
    for item in info.get("items", []):
        locator = item.get("locator", {})
        if locator.get("type") != "notebook-markdown":
            continue
        cell_index = locator.get("cell_index")
        if not isinstance(cell_index, int) or cell_index >= len(cells):
            failures.append(f"notebook missing markdown cell {cell_index}: {relative_path}")
            continue
        source = _cell_source_text(cells[cell_index])
        if LOCALIZED_MARKER not in source or "<summary>English original</summary>" not in source:
            failures.append(
                f"notebook markdown cell missing bilingual wrapper: {relative_path} cell {cell_index}"
            )
    return failures


def _cell_source_text(cell):
    source = cell.get("source", "")
    if isinstance(source, list):
        return "".join(source)
    return str(source)


def _set_cell_source(cell, text):
    original = cell.get("source", "")
    if isinstance(original, list):
        cell["source"] = text.splitlines(keepends=True)
    else:
        cell["source"] = text


def build_parser():
    parser = argparse.ArgumentParser(description="Prepare/apply/validate DLAIKit localization.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Scan an export and create translation chunks.")
    prepare.add_argument("export_dir")
    prepare.add_argument("--output-dir", default="")
    prepare.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    prepare.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    prepare.set_defaults(func=command_prepare)

    apply = subparsers.add_parser("apply", help="Apply translated chunks to the localized output.")
    apply.add_argument("export_dir")
    apply.add_argument("--output-dir", default="")
    apply.set_defaults(func=command_apply)

    validate = subparsers.add_parser("validate", help="Validate localized output.")
    validate.add_argument("export_dir")
    validate.add_argument("--output-dir", default="")
    validate.set_defaults(func=command_validate)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LocalizeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
