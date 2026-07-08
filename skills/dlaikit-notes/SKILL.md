---
name: dlaikit-notes
description: Generate comprehensive Chinese Markdown study notes for each lesson in a DLAIKit export, usually after localization. Use when Codex should synthesize translated transcripts, translated Markdown, executed notebook outputs, lab/project code, and fallback untranslated materials into high-quality per-lesson notes under an export's notes/ directory.
---

# DLAIKit Lesson Notes

Use this skill after a DLAIKit export has been localized when possible. Prefer
`exports/<course-slug>/zh/` as the main source, and use untranslated files from
`exports/<course-slug>/` only as fallback or extra context.

## Workflow

1. Identify the export directory, usually `exports/<course-slug>/`.
2. Prepare lesson context packs:
   ```sh
   python skills/dlaikit-notes/scripts/lesson_notes.py prepare exports/<course-slug>
   ```
3. For each Markdown context under `exports/<course-slug>/notes/.dlaikit-notes/pending/`, write the final note to the `Output note` path shown inside that context.
4. Run validation:
   ```sh
   python skills/dlaikit-notes/scripts/lesson_notes.py validate exports/<course-slug>
   ```

The helper creates `notes/index.md`, stores state in `notes/.dlaikit-notes/`,
skips unchanged lessons that already have notes, and prepares only pending
contexts that need writing or rewriting.

## Note Requirements

Write notes in Chinese by default. Use a comprehensive but study-friendly style:

- Start with `# NN. Lesson Title`.
- Include these exact sections:
  - `## 学习目标`
  - `## 核心概念`
  - `## 代码/实践解读`
  - `## 关键收获`
  - `## 复习问题`
- Use translated transcripts and localized notebooks as primary evidence.
- Treat executed notebook outputs, return values, logs, and errors as important evidence for the `代码/实践解读` section.
- Integrate code from notebooks, helper files, shared libraries, and project docs when it helps learning.
- Add useful background knowledge as `补充理解`, but do not present it as course transcript content.
- Quote only short code snippets. Link or name source paths for longer files instead of copying whole notebooks or large code files.
- Do not copy full transcripts, full notebooks, full lab/project files, long logs, or raw notebook outputs into the notes.

## Context Packs

Each pending context contains:

- output note path;
- lesson metadata and source URL;
- course overview/resource excerpts;
- transcript content if available;
- matched notebook/code/project/shared files, including summarized notebook outputs when present;
- warnings when a lesson lacks a transcript or code match.

Use the context pack as the source of truth for that lesson. If a context pack
lists multiple possible code files, synthesize only the parts relevant to the
lesson title and learning flow. When notebook outputs are present, explain what
they demonstrate instead of merely restating the code.

## Validation

After writing all notes, run the helper's `validate` command. Fix every reported
error before finishing. Validation checks that:

- every lesson in the manifest has a note;
- `notes/index.md` links every note;
- every note contains all required sections.
