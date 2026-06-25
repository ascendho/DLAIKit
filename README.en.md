> 中文版本同样可用：[README.md](README.md)。

# DeepLearning.AI Course Exporter

![Python](https://img.shields.io/badge/python-%3E%3D3.9-blue)
![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33)
![Tests](https://img.shields.io/badge/tests-pytest-blueviolet)
![Output](https://img.shields.io/badge/output-Markdown%20%2B%20JSON-lightgrey)
![Config](https://img.shields.io/badge/config-JSON-informational)
![License](https://img.shields.io/badge/license-MIT-green)

Export DeepLearning.AI course transcripts, course metadata, resource links, and
optional lab code to local files. The extractor uses Playwright so it can work
with rendered course pages and authenticated lessons.

## Features

- Discover lessons from a course page.
- Save one Markdown transcript per lesson.
- Always generate the full study pack: `index.md`, `course-overview.md`,
  `resources.md`, and `manifest.json`.
- Recursively download course code from the configured Jupyter/Lab URL.
- Automatically read the temporary Jupyter token from course code lesson
  iframes in normal cases.
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

Edit `dlai-transcripts.json` in the project root:

```json
{
  "course_url": "https://www.deeplearning.ai/courses/building-coding-agents-with-tool-execution",
  "code_url": "https://...lab-aws-production.deeplearning.ai/tree",
  "output_dir": "exports",
  "auth_state": ".auth/deeplearning_ai.json",
  "browser_visibility": "auto",
  "force": false
}
```

`course_url` is required. `code_url` may be empty; when it is empty, the tool
exports transcripts and study-pack metadata without downloading lab code.

## Run

```sh
dlai-transcripts
```

The command always exports the full study pack for all visible resources. No
extra arguments are needed. The first authenticated run may open a browser
window. Complete login in that browser, and the command will continue
automatically. Later runs reuse the saved login state and run in the background
by default.

## Export Structure

By default, files are exported under `exports/` in the project root:

```text
exports/<course-slug>/
  index.md
  transcripts/
    01-<lesson-slug>.md
  code/
  course-overview.md
  resources.md
  manifest.json
```

- `index.md`: lesson index, crawl status, and code download summary.
- `transcripts/`: per-lesson transcript Markdown files.
- `code/`: course code and materials downloaded from the Jupyter/Lab URL.
- `course-overview.md`: course summary, learning objectives, instructors,
  lesson types, and durations.
- `resources.md`: code examples, quiz or assignment pages, and visible resource
  links.
- `manifest.json`: structured course, lesson, resource, and crawl result data.

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

In normal cases, the tool reads the temporary token from the course code lesson
iframe. Only when the course page does not expose an iframe token, add
`"code_token": "your Jupyter token"` to `dlai-transcripts.json` in the project
root, or set `"browser_visibility"` to `"visible"` and run the command once.

## Notes

- This project is intended for personal study workflows.
- Source code lives in `src/study/`, the import package directory for
  the standard Python `src` layout. It is not an output directory.
- DeepLearning.AI page structure can change; parser tests use local HTML
  fixtures to keep core behavior stable.
