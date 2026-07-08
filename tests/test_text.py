from dlaikit.text import course_slug_from_url, resolve_project_path, slugify


def test_slugify_normalizes_for_filenames():
    assert slugify("Intro: Coding Agents!") == "intro-coding-agents"


def test_course_slug_from_url():
    url = "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction"

    assert course_slug_from_url(url) == "building-coding-agents-with-tool-execution"


def test_resolve_project_path_finds_root_from_src(tmp_path):
    project = tmp_path / "dlaikit"
    package_dir = project / "src" / "dlaikit"
    package_dir.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")

    resolved = resolve_project_path(".auth/deeplearning_ai.json", start=project / "src")

    assert resolved == project / ".auth" / "deeplearning_ai.json"
