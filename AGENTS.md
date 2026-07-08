# Repository Guidelines

## Project Structure & Module Organization

Core code lives in `src/dlaikit/`. Keep parsing, fetching,
crawling, writing, and CLI concerns in separate modules. Tests live in `tests/`
and should use local HTML strings or fixtures instead of live course pages.
Generated study packs belong under `exports/<course-slug>/`; local browser login
state belongs under `.auth/`. Both directories are ignored by git.

## Build, Test, and Development Commands

Create an editable development environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e ".[dev]"
python3 -m playwright install chromium
```

Run the extractor:

```sh
dlaikit
```

Run checks:

```sh
python3 -m py_compile src/dlaikit/*.py
python3 -m pytest
```

## Coding Style & Naming Conventions

Use standard Python style: 4-space indentation, `snake_case` for functions and
variables, and `UPPER_SNAKE_CASE` for constants. Keep file and URL slugs
lowercase with hyphen separators, for example `01-introduction.md`. Avoid
hard-coding course-specific selectors unless tests document the expected HTML
shape.

## Testing Guidelines

Use `pytest` and name test files `tests/test_*.py`. Cover transcript extraction,
lesson-link discovery, slug generation, and Markdown writing. Tests should not
perform network requests or require DeepLearning.AI login. For browser behavior,
prefer small integration tests guarded by explicit opt-in markers.

## Commit & Pull Request Guidelines

Use short imperative commit messages, preferably conventional prefixes such as
`feat: crawl full course` or
`fix: preserve lesson order`. Pull requests should describe behavior changes,
list commands run, and include sample output paths when export generation
changes.

## Security & Configuration Tips

Do not commit credentials, cookies, or `.auth/` files. Treat fetched HTML as
untrusted input and never execute page content. Keep generated exports out
of source changes unless a fixture is intentionally added for testing.
