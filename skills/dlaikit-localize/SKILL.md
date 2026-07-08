---
name: dlaikit-localize
description: Use when Codex should directly localize original DLAIKit exports into Simplified Chinese, including translating transcript and Markdown files while preserving English originals, translating English code comments/docstrings, preserving executable code and notebook execution outputs, skipping generated notes/localized outputs, and validating localized Python/notebook files. Trigger for requests such as "translate exports into Chinese", "localize this DeepLearning.AI course", or "translate code comments and transcripts".
---

# DLAIKit Localization

Use the current Codex model to translate the files directly. Do not ask the
user for a separate translation command, do not call an external translation
CLI, and do not create fake placeholder translations.

## Workflow

1. Identify the export directory, usually `exports/<course-slug>/`.
2. Prepare deterministic translation chunks:
   ```sh
   python skills/dlaikit-localize/scripts/localize_pack.py prepare exports/<course-slug>
   ```
3. Translate each JSON file under `exports/<course-slug>/zh/.dlaikit-localize/pending/` with the current Codex model. For every pending `chunk-0001.json`, write `exports/<course-slug>/zh/.dlaikit-localize/translated/chunk-0001.json` with the same `chunk_id` and item `id` values:
   ```json
   {
     "chunk_id": "chunk-0001",
     "items": [
       { "id": "item-...", "text": "中文译文" }
     ]
   }
   ```
4. Apply translated chunks and validate:
   ```sh
   python skills/dlaikit-localize/scripts/localize_pack.py apply exports/<course-slug>
   python skills/dlaikit-localize/scripts/localize_pack.py validate exports/<course-slug>
   ```
5. Preserve the original export. Never write localized content back into the English source files.

The helper copies non-translated assets, stores state under `zh/.dlaikit-localize/`, supports resume, skips unchanged files after a successful apply, and ignores generated directories such as `zh/`, `notes/`, `.dlaikit-localize/`, and `.dlaikit-notes/`. When the user explicitly asks for faster or parallel execution, split different pending chunk files across agents and merge their translated JSON files before running `apply`.

## Translation Rules

- Markdown and transcript files: write Chinese first, then keep the original English in a folded block:
  ```md
  <!-- dlaikit-localized: zh-CN -->

  <Chinese translation>

  ---

  <details>
  <summary>English original</summary>

  <original English markdown>
  </details>
  ```
- Preserve Markdown structure, headings, links, lists, tables, inline code, code fences, and frontmatter.
- Python files: translate only English comments and docstrings. Preserve executable code, identifiers, imports, string literals, shebang comments, encoding comments, `# noqa`, `type: ignore`, `pylint:`, `pragma:`, `fmt:`, and `ruff:` directives.
- Notebook files: parse JSON, preserve metadata, outputs, execution counts, logs, display results, and errors. Localize Markdown cells with the Markdown rule above. Localize code cells only by translating comments/docstrings.
- Do not translate data values, filenames, package names, environment variables, API names, URLs, notebook outputs, logs, execution results, or code examples inside fenced code blocks unless they are plain explanatory comments.
- Do not localize generated notes or already-localized outputs. `notes/` is produced by `dlaikit-notes`, and `zh/` is this skill's output.

## Validation

After writing localized files:

```sh
python3 -m py_compile src/dlaikit/*.py
python3 -m pytest
```

Also inspect representative localized outputs:

- one transcript Markdown file contains Chinese text and `English original`;
- one localized `.py` file still compiles if copied out and compiled;
- one `.ipynb` remains valid JSON;
- copied CSV/image/data files are unchanged.
