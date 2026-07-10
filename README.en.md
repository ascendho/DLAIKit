> 中文版本同样可用：[README.md](README.md)。

# DLAIKit

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33)
![Tests](https://img.shields.io/badge/tests-pytest-blueviolet)
![Output](https://img.shields.io/badge/output-Markdown%20%2B%20JSON-lightgrey)
![Config](https://img.shields.io/badge/config-JSON-informational)
![License](https://img.shields.io/badge/license-MIT-green)

DLAIKit is an unofficial personal study helper for organizing
DeepLearning.AI course pages that the user is already authorized to access.
This repository does not include or redistribute any DeepLearning.AI or
Coursera course materials; local outputs created by users are the users'
responsibility. The tool uses Playwright to control a local browser for pages
the user is logged in to and authorized to access.

## Legal and Usage Notice

DLAIKit is an unofficial personal study helper. It is not affiliated with,
endorsed by, sponsored by, or officially authorized by DeepLearning.AI or
Coursera. Users should organize only content they are authorized to access and
are responsible for complying with DeepLearning.AI terms, Coursera terms,
course platform terms, lab provider terms, and applicable laws. Do not use this
project to bypass paywalls, login requirements, access controls, or platform
restrictions, and do not publish, share, sell, or redistribute exported
transcripts, notebooks, labs, quizzes, assignments, solutions, or other course
materials without authorization.

See [NOTICE.md](NOTICE.md) for details. If you are a rights holder, or if you
believe this project or related public content harms your rights, contact the
maintainer through GitHub Issues or [ascendho@outlook.com](mailto:ascendho@outlook.com) for prompt review.

## Features

- Discover lessons from course pages the user is logged in to and authorized to access.
- Save lesson transcript Markdown for local personal study.
- Always generate the full study pack: `index.md`, `course-overview.md`,
  `resources.md`, and `manifest.json`.
- Save accessible lesson code locally when the user explicitly configures a
  Jupyter/Lab link.
- Use page-provided temporary lab access credentials only within course code,
  project, or graded pages that the user is logged in to and authorized to access.
- Reuse local Playwright login state from `.auth/deeplearning_ai.json`.

## Installation

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
python3 -m playwright install chromium
```

## Configuration

Edit `dlaikit.json` in the project root:

```json
{
  "course_url": "https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution",
  "code_url": "https://...lab-aws-production.deeplearning.ai/tree",
  "output_dir": "exports",
  "auth_state": ".auth/deeplearning_ai.json",
  "browser_visibility": "auto",
  "execute_lesson_notebooks": false,
  "notebook_execute_timeout_seconds": 900,
  "force": false,
  "skip_code_dirs": ["models"]
}
```

`course_url` is required. `code_url` may be empty; when it is empty, the tool
exports transcripts and study-pack metadata without saving lab code. The
configured `code_url` is treated as the lesson lab entry; project or graded labs
visible from course pages may also be discovered. Confirm that you are
authorized to access and locally save the relevant content before using this
feature.

Use `skip_code_dirs` to name directories that should not be downloaded. For
example, `["models"]` skips a directory named `models` at any depth, matches
case-insensitively, and does not fetch that directory's children. The default
is an empty list; DLAIKit does not decide which course directories to skip.
Technical directories such as `.git`, `.venv`, `node_modules`, and hidden
directories remain excluded by built-in rules.

Set `"execute_lesson_notebooks": true` to save lesson notebooks with outputs.
When enabled, DLAIKit executes notebooks under `code/lessons/` in the remote
Jupyter/Lab environment that the user is authorized to access, then saves the
executed `.ipynb` files locally. Notebooks under `code/project/`, graded,
assignment, or quiz materials are not executed automatically. This can take
time and may modify the remote lab session state; if one notebook execution
fails, the download continues and the code summary records the execution
failure.

## Run

```sh
dlaikit
```

The command generates a local study pack for course resources that are visible
to your authenticated browser and that you are authorized to access. No extra
arguments are needed. The first authenticated run may open a browser window.
Complete login in that browser, and the command will continue automatically.
Later runs reuse the saved login state and run in the background by default.

## AI Skills Post-Processing Workflow

This repository includes two Codex skills for post-processing local study-pack
exports. In normal use, you do not need to run the internal helper scripts
directly. Ask Codex in natural language and include the skill name and export
directory.

Recommended order:

1. Run `dlaikit` to create `exports/<course-slug>/`.
2. Localize the export:

   ```text
   Use the dlaikit-localize skill to translate exports/<course-slug>.
   ```

   Output is written to `exports/<course-slug>/zh/`. The original English export
   is preserved.

3. Generate per-lesson study notes:

   ```text
   Use the dlaikit-notes skill to generate lesson notes for exports/<course-slug>.
   ```

   Output is written to `exports/<course-slug>/notes/`, including
   `notes/index.md`.

The skills internally use helper scripts for chunking, resumability,
unchanged-file skipping, and validation. Those scripts are implementation
details for automation and debugging. Generated translations, notes, and code
materials remain local personal-study outputs; do not commit them to public
repositories or redistribute them.

## Export Structure

By default, files are exported under `exports/` in the project root:

```text
exports/<course-slug>/
  index.md
  transcripts/
    01-<lesson-slug>.md
  code/
    lessons/
    project/
  course-overview.md
  resources.md
  manifest.json
```

- `index.md`: lesson index, processing status, and local code-save summary.
- `transcripts/`: per-lesson transcript Markdown files.
- `code/`: accessible code and materials saved locally after a Jupyter/Lab link
  is configured.
- `code/lessons/`: lesson code from the configured `code_url` or regular code
  lesson pages.
- `code/project/`: project code from lab entries visible on project, graded, or
  assignment pages; it remains empty when no project lab is found.
- `course-overview.md`: course summary, learning objectives, instructors,
  lesson types, and durations.
- `resources.md`: code examples, quiz or assignment pages, and visible resource
  links.
- `manifest.json`: structured course, lesson, resource, and processing result data.

`metadata` means the course item did not produce a standalone transcript
Markdown file. It is recorded in `index.md` and `manifest.json` instead. Code
examples, quizzes, or assignments without visible transcripts are marked as
`metadata`, not `failed`.

## Authentication

The extractor does not store usernames or passwords. It stores only the local
Playwright browser state needed to reuse an existing web login:

```text
.auth/deeplearning_ai.json
```

On course code, project, or graded pages that the user is logged in to and
authorized to access, the tool may use page-provided temporary lab access
credentials to request related Jupyter/Lab resources. Only add
`"code_token": "your Jupyter token"` to `dlaikit.json`, or set
`"browser_visibility"` to `"visible"` and run the command once, when you have
confirmed that you are authorized to access the relevant lab and the course
page does not provide a reusable lab entry. Do not commit or publish local
files containing tokens, login state, or exported course materials.

## Notes

- This project is intended for personal study workflows.
- Source code lives in `src/dlaikit/`, the import package directory for
  the standard Python `src` layout. It is not an output directory.
- DeepLearning.AI page structure can change; parser tests use local HTML
  fixtures to keep core behavior stable.
