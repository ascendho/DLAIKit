import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "scholarium-notes"
    / "scripts"
    / "lesson_notes.py"
)


def load_helper():
    spec = importlib.util.spec_from_file_location("scholarium_notes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_helper(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def make_export(tmp_path):
    export_dir = tmp_path / "course"
    zh_dir = export_dir / "zh"
    (export_dir / "transcripts").mkdir(parents=True)
    (zh_dir / "transcripts").mkdir(parents=True)
    (zh_dir / "code" / "lessons" / "L1").mkdir(parents=True)
    (zh_dir / "code" / "lessons" / "lib").mkdir(parents=True)
    (zh_dir / "code" / "project").mkdir(parents=True)

    manifest = {
        "course": {"title": "Agent Course", "slug": "agent-course"},
        "lessons": [
            {
                "index": 1,
                "title": "Introduction",
                "url": "https://example.test/intro",
                "kind": "video",
                "duration": "3m",
            },
            {
                "index": 2,
                "title": "Build Agent",
                "url": "https://example.test/build",
                "kind": "code",
                "duration": "8m",
            },
            {
                "index": 3,
                "title": "Hands-On Project",
                "url": "https://example.test/project",
                "kind": "code",
                "duration": "10m",
            },
        ],
        "results": [
            {
                "index": 1,
                "title": "Introduction",
                "path": "transcripts/01-introduction.md",
                "status": "saved",
            },
            {
                "index": 2,
                "title": "Build Agent",
                "path": "transcripts/02-build-agent.md",
                "status": "saved",
            },
            {
                "index": 3,
                "title": "Hands-On Project",
                "path": "",
                "status": "metadata",
            },
        ],
        "resources": [],
    }
    for base in (export_dir, zh_dir):
        (base / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (zh_dir / "course-overview.md").write_text("# 课程概览\n\n中文课程目标。", encoding="utf-8")
    (zh_dir / "resources.md").write_text("# 资源\n\n无。", encoding="utf-8")
    (zh_dir / "index.md").write_text("# Agent Course\n", encoding="utf-8")
    (export_dir / "transcripts" / "01-introduction.md").write_text(
        "# Introduction\n\nEnglish intro.",
        encoding="utf-8",
    )
    (zh_dir / "transcripts" / "01-introduction.md").write_text(
        "# 介绍\n\n中文介绍。",
        encoding="utf-8",
    )
    (export_dir / "transcripts" / "02-build-agent.md").write_text(
        "# Build Agent\n\nOriginal Build transcript.",
        encoding="utf-8",
    )
    (zh_dir / "code" / "lessons" / "L1" / "L1.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": "# L1: Build Agent\n\nNotebook overview."},
                    {
                        "cell_type": "code",
                        "execution_count": 1,
                        "outputs": [
                            {
                                "output_type": "stream",
                                "name": "stdout",
                                "text": "\u001b[34magent ready\u001b[0m\nid=inv1vzsykq8n2\n",
                            },
                            {
                                "output_type": "execute_result",
                                "execution_count": 1,
                                "data": {"text/plain": "Result: ok"},
                                "metadata": {},
                            },
                            {
                                "output_type": "error",
                                "ename": "ValueError",
                                "evalue": "bad input",
                                "traceback": ["\u001b[31mTraceback line\u001b[0m"],
                            },
                        ],
                        "source": "def run_agent():\n    return 'ok'\n",
                    },
                    {
                        "cell_type": "code",
                        "execution_count": 2,
                        "outputs": [
                            {
                                "output_type": "display_data",
                                "data": {"image/png": "BASE64_IMAGE_PAYLOAD"},
                                "metadata": {},
                            }
                        ],
                        "source": "plot_agent_trace()\n",
                    },
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    (zh_dir / "code" / "lessons" / "L1" / "helper.py").write_text(
        "# helper comment\ndef helper():\n    return 1\n",
        encoding="utf-8",
    )
    (zh_dir / "code" / "lessons" / "lib" / "tools.py").write_text(
        "def tool():\n    return 'tool'\n",
        encoding="utf-8",
    )
    (zh_dir / "code" / "project" / "docs.md").write_text(
        "# Project docs\n\nBuild a final app.",
        encoding="utf-8",
    )
    (zh_dir / "code" / "project" / "project.ipynb").write_text(
        json.dumps(
            {
                "cells": [
                    {"cell_type": "markdown", "source": "# Project\n\nFinal challenge."},
                    {"cell_type": "code", "source": "print('project')\n"},
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )
    return export_dir


def write_valid_notes(export_dir):
    helper = load_helper()
    notes_dir = export_dir / "notes"
    for pending in sorted((notes_dir / ".scholarium-notes" / "pending").glob("*.md")):
        output_name = pending.name
        text = "\n\n".join(
            [
                "# {}".format(output_name),
                *helper.REQUIRED_SECTIONS,
                "正文。",
            ]
        )
        (notes_dir / output_name).write_text(text + "\n", encoding="utf-8")


def test_prepare_builds_lesson_contexts_from_translated_and_fallback_materials(tmp_path):
    export_dir = make_export(tmp_path)

    result = run_helper("prepare", str(export_dir))

    assert result.returncode == 0, result.stderr
    pending_dir = export_dir / "notes" / ".scholarium-notes" / "pending"
    pending = sorted(pending_dir.glob("*.md"))
    assert [path.name for path in pending] == [
        "01-introduction.md",
        "02-build-agent.md",
        "03-hands-on-project.md",
    ]

    intro = (pending_dir / "01-introduction.md").read_text(encoding="utf-8")
    build = (pending_dir / "02-build-agent.md").read_text(encoding="utf-8")
    project = (pending_dir / "03-hands-on-project.md").read_text(encoding="utf-8")

    assert "中文介绍" in intro
    assert "English intro" not in intro
    assert "Original Build transcript" in build
    assert "code/lessons/L1/L1.ipynb" in build
    assert "def run_agent" in build
    assert "execution_count: 1" in build
    assert "Notebook outputs" in build
    assert "[stdout]" in build
    assert "agent ready" in build
    assert "id=<redacted>" in build
    assert "Result: ok" in build
    assert "ValueError: bad input" in build
    assert "Binary/rich display output omitted: image/png" in build
    assert "BASE64_IMAGE_PAYLOAD" not in build
    assert "\u001b" not in build
    assert "code/lessons/lib/tools.py" in build
    assert "code/project/project.ipynb" in project
    assert "Project docs" in project

    index = (export_dir / "notes" / "index.md").read_text(encoding="utf-8")
    assert "(01-introduction.md)" in index
    assert "(02-build-agent.md)" in index
    assert "(03-hands-on-project.md)" in index


def test_validate_requires_notes_index_links_and_sections(tmp_path):
    export_dir = make_export(tmp_path)
    assert run_helper("prepare", str(export_dir)).returncode == 0

    missing = run_helper("validate", str(export_dir))
    assert missing.returncode == 1
    assert "missing note" in missing.stderr

    write_valid_notes(export_dir)
    valid = run_helper("validate", str(export_dir))
    assert valid.returncode == 0, valid.stderr

    bad_note = export_dir / "notes" / "01-introduction.md"
    bad_note.write_text("# bad\n\n## 学习目标\n", encoding="utf-8")
    invalid = run_helper("validate", str(export_dir))
    assert invalid.returncode == 1
    assert "missing required section" in invalid.stderr


def test_prepare_skips_unchanged_notes_and_requeues_changed_lesson(tmp_path):
    export_dir = make_export(tmp_path)
    assert run_helper("prepare", str(export_dir)).returncode == 0
    write_valid_notes(export_dir)

    rerun = run_helper("prepare", str(export_dir))
    assert rerun.returncode == 0, rerun.stderr
    pending_dir = export_dir / "notes" / ".scholarium-notes" / "pending"
    assert not list(pending_dir.glob("*.md"))

    transcript = export_dir / "zh" / "transcripts" / "01-introduction.md"
    transcript.write_text("# 介绍\n\n中文介绍已更新。", encoding="utf-8")
    changed = run_helper("prepare", str(export_dir))
    assert changed.returncode == 0, changed.stderr
    pending = sorted(path.name for path in pending_dir.glob("*.md"))
    assert pending == ["01-introduction.md"]
