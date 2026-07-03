import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "scholarium-localize"
    / "scripts"
    / "localize_pack.py"
)


def load_helper():
    spec = importlib.util.spec_from_file_location("scholarium_localize", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_helper(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def write_translated_chunks(export_dir, prefix="ZH"):
    pending_dir = export_dir / "zh" / ".scholarium-localize" / "pending"
    translated_dir = export_dir / "zh" / ".scholarium-localize" / "translated"
    translated_dir.mkdir(parents=True, exist_ok=True)
    for pending_path in sorted(pending_dir.glob("*.json")):
        payload = json.loads(pending_path.read_text(encoding="utf-8"))
        translated = {
            "chunk_id": payload["chunk_id"],
            "items": [
                {"id": item["id"], "text": "{}:{}".format(prefix, item["id"])}
                for item in payload["items"]
            ],
        }
        (translated_dir / pending_path.name).write_text(
            json.dumps(translated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def make_export(tmp_path):
    export_dir = tmp_path / "course"
    (export_dir / "transcripts").mkdir(parents=True)
    (export_dir / "code").mkdir()
    (export_dir / "transcripts" / "01-intro.md").write_text(
        "# Intro\n\nEnglish paragraph.",
        encoding="utf-8",
    )
    (export_dir / "code" / "app.py").write_text(
        "#!/usr/bin/env python3\n"
        "# coding: utf-8\n"
        "\"\"\"Module doc.\"\"\"\n"
        "# setup sandbox\n"
        "value = 1  # inline comment\n"
        "ignored = 2  # noqa\n"
        "def run():\n"
        "    \"\"\"Return value.\"\"\"\n"
        "    return value\n",
        encoding="utf-8",
    )
    (export_dir / "code" / "demo.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "metadata": {}, "source": "# Lesson\n\nEnglish notes."},
                    {
                        "cell_type": "code",
                        "metadata": {"trusted": True},
                        "outputs": [
                            {
                                "output_type": "stream",
                                "name": "stdout",
                                "text": "runtime log\n",
                            },
                            {
                                "output_type": "execute_result",
                                "execution_count": 7,
                                "data": {"text/plain": "rendered result"},
                                "metadata": {},
                            },
                            {
                                "output_type": "display_data",
                                "data": {"image/png": "BASE64_IMAGE_PAYLOAD"},
                                "metadata": {},
                            },
                            {
                                "output_type": "error",
                                "ename": "RuntimeError",
                                "evalue": "remote failure",
                                "traceback": ["Traceback line"],
                            },
                        ],
                        "execution_count": 7,
                        "source": ["# explain code\n", "x = 1\n"],
                    },
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "code" / "data.csv").write_text("name,value\nA,1\n", encoding="utf-8")
    return export_dir


def test_prepare_creates_chunks_and_copies_assets(tmp_path):
    export_dir = make_export(tmp_path)

    result = run_helper("prepare", str(export_dir), "--max-items", "2")

    assert result.returncode == 0, result.stderr
    output_dir = export_dir / "zh"
    pending = sorted((output_dir / ".scholarium-localize" / "pending").glob("*.json"))
    assert pending
    assert (output_dir / "code" / "data.csv").read_text(encoding="utf-8") == "name,value\nA,1\n"

    kinds = []
    item_text = []
    for path in pending:
        payload = json.loads(path.read_text(encoding="utf-8"))
        kinds.extend(item["kind"] for item in payload["items"])
        item_text.extend(item["text"] for item in payload["items"])
    assert "markdown" in kinds
    assert "python-comment" in kinds
    assert "python-docstring" in kinds
    assert "notebook-markdown" in kinds
    assert "notebook-code-comment" in kinds
    combined_text = "\n".join(item_text)
    assert "runtime log" not in combined_text
    assert "rendered result" not in combined_text
    assert "BASE64_IMAGE_PAYLOAD" not in combined_text
    assert "remote failure" not in combined_text


def test_prepare_skips_generated_dirs_with_custom_output(tmp_path):
    export_dir = make_export(tmp_path)
    (export_dir / "zh").mkdir()
    (export_dir / "zh" / "already-localized.md").write_text(
        "# 已翻译\n\nAlready localized output.",
        encoding="utf-8",
    )
    (export_dir / "notes" / ".scholarium-notes").mkdir(parents=True)
    (export_dir / "notes" / "01-intro.md").write_text(
        "# Note\n\nGenerated study note.",
        encoding="utf-8",
    )
    (export_dir / "notes" / ".scholarium-notes" / "state.json").write_text(
        "{}",
        encoding="utf-8",
    )

    output_dir = export_dir / "localized"
    result = run_helper("prepare", str(export_dir), "--output-dir", str(output_dir), "--max-items", "50")

    assert result.returncode == 0, result.stderr
    state = json.loads((output_dir / ".scholarium-localize" / "state.json").read_text(encoding="utf-8"))
    assert not any(path.startswith("zh/") for path in state["files"])
    assert not any(path.startswith("notes/") for path in state["files"])
    assert not (output_dir / "notes").exists()
    assert not (output_dir / "zh").exists()


def test_apply_writes_localized_markdown_python_and_notebook(tmp_path):
    export_dir = make_export(tmp_path)
    helper = load_helper()
    assert run_helper("prepare", str(export_dir), "--max-items", "3").returncode == 0
    write_translated_chunks(export_dir)

    apply_result = run_helper("apply", str(export_dir))
    validate_result = run_helper("validate", str(export_dir))

    assert apply_result.returncode == 0, apply_result.stderr
    assert validate_result.returncode == 0, validate_result.stderr

    output_dir = export_dir / "zh"
    source_notebook = json.loads((export_dir / "code" / "demo.ipynb").read_text(encoding="utf-8"))
    localized_md = (output_dir / "transcripts" / "01-intro.md").read_text(encoding="utf-8")
    assert localized_md.startswith(helper.LOCALIZED_MARKER)
    assert "<summary>English original</summary>" in localized_md
    assert "# Intro\n\nEnglish paragraph." in localized_md
    assert "ZH:item-" in localized_md

    localized_py = (output_dir / "code" / "app.py").read_text(encoding="utf-8")
    assert "#!/usr/bin/env python3" in localized_py
    assert "# coding: utf-8" in localized_py
    assert "# noqa" in localized_py
    assert "setup sandbox" not in localized_py
    assert "inline comment" not in localized_py
    assert "Module doc." not in localized_py
    compile(localized_py, "<localized.py>", "exec")

    notebook = json.loads((output_dir / "code" / "demo.ipynb").read_text(encoding="utf-8"))
    markdown_source = notebook["cells"][0]["source"]
    code_source = "".join(notebook["cells"][1]["source"])
    assert helper.LOCALIZED_MARKER in markdown_source
    assert "English notes." in markdown_source
    assert "explain code" not in code_source
    assert "# ZH:item-" in code_source
    assert notebook["cells"][1]["execution_count"] == source_notebook["cells"][1]["execution_count"]
    assert notebook["cells"][1]["metadata"] == source_notebook["cells"][1]["metadata"]
    assert notebook["cells"][1]["outputs"] == source_notebook["cells"][1]["outputs"]


def test_prepare_skips_unchanged_after_apply_and_requeues_changed_file(tmp_path):
    export_dir = make_export(tmp_path)

    assert run_helper("prepare", str(export_dir), "--max-items", "10").returncode == 0
    write_translated_chunks(export_dir)
    assert run_helper("apply", str(export_dir)).returncode == 0

    rerun = run_helper("prepare", str(export_dir), "--max-items", "10")
    assert rerun.returncode == 0, rerun.stderr
    assert not list((export_dir / "zh" / ".scholarium-localize" / "pending").glob("*.json"))

    transcript = export_dir / "transcripts" / "01-intro.md"
    transcript.write_text("# Intro\n\nChanged English paragraph.", encoding="utf-8")
    changed = run_helper("prepare", str(export_dir), "--max-items", "10")
    assert changed.returncode == 0, changed.stderr
    pending = list((export_dir / "zh" / ".scholarium-localize" / "pending").glob("*.json"))
    assert len(pending) == 1
    payload = json.loads(pending[0].read_text(encoding="utf-8"))
    assert [item["source_path"] for item in payload["items"]] == ["transcripts/01-intro.md"]


def test_validate_rejects_notebook_markdown_without_bilingual_wrapper(tmp_path):
    export_dir = make_export(tmp_path)

    assert run_helper("prepare", str(export_dir), "--max-items", "10").returncode == 0
    write_translated_chunks(export_dir)
    assert run_helper("apply", str(export_dir)).returncode == 0

    notebook_path = export_dir / "zh" / "code" / "demo.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    notebook["cells"][0]["source"] = "只有中文，没有英文原文"
    notebook_path.write_text(json.dumps(notebook), encoding="utf-8")

    result = run_helper("validate", str(export_dir))

    assert result.returncode == 1
    assert "notebook markdown cell missing bilingual wrapper" in result.stderr
