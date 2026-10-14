from dlaikit.text import course_slug_from_url, is_lesson_url, resolve_project_path, slugify


def test_slugify_normalizes_for_filenames():
    assert slugify("Intro: Coding Agents!") == "intro-coding-agents"


def test_course_slug_from_url():
    url = "https://learn.deeplearning.ai/courses/building-coding-agents-with-tool-execution/lesson/deetno/introduction"

    assert course_slug_from_url(url) == "building-coding-agents-with-tool-execution"


def test_is_lesson_url_requires_lesson_identifier():
    assert is_lesson_url("https://www.deeplearning.ai/courses/course/lesson") is False
    assert is_lesson_url("https://learn.deeplearning.ai/courses/course/lesson/id") is True
    assert is_lesson_url("https://learn.deeplearning.ai/courses/course/lesson/id/introduction") is True


def test_resolve_project_path_finds_root_from_src(tmp_path):
    project = tmp_path / "dlaikit"
    package_dir = project / "src" / "dlaikit"
    package_dir.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")

    resolved = resolve_project_path(".auth/deeplearning_ai.json", start=project / "src")

    assert resolved == project / ".auth" / "deeplearning_ai.json"
