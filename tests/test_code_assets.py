import json
from base64 import b64encode
from urllib.parse import parse_qs, urlparse

from dlaikit.code_assets import (
    extract_jupyter_lab_links,
    JupyterCodeDownloader,
    JupyterLabLink,
    NotebookExecutionError,
    parse_jupyter_contents_location,
    redact_url,
)


class FakeJupyterClient:
    def __init__(self, responses, auth_payload=None):
        self.responses = responses
        self.primed = []
        self.requested = []
        self.auth_payload = auth_payload
        self.authenticated = []

    def prime(self, url):
        self.primed.append(url)

    def get_json(self, url):
        self.requested.append(url)
        parsed = urlparse(url)
        key = "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path)
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response

    def authenticate(self, login_url, check_url):
        self.authenticated.append((login_url, check_url))
        return self.auth_payload


class TokenPrimingJupyterClient(FakeJupyterClient):
    def get_json(self, url):
        if not self.primed:
            self.requested.append(url)
            raise FakeHttpError(403)
        return super().get_json(url)


class FakeHttpError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__("GET https://lab.example.test/api/contents?content=1 failed with HTTP {}".format(status))


class FakeNotebookExecutor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def execute(self, location, notebook_path, notebook, token=None):
        self.calls.append((location.base_url, notebook_path, token))
        cell = notebook["cells"][0]
        cell["execution_count"] = 1
        cell["outputs"] = [
            {
                "output_type": "stream",
                "name": "stdout",
                "text": "executed\n",
            }
        ]
        if self.fail:
            raise NotebookExecutionError("boom", notebook=notebook)
        return notebook


def jupyter_dir(name, path, content):
    return {
        "type": "directory",
        "name": name,
        "path": path,
        "content": content,
    }


def jupyter_file(name, path, content):
    return {
        "type": "file",
        "name": name,
        "path": path,
        "format": "text",
        "content": content,
    }


def jupyter_notebook(name, path, source):
    return {
        "type": "notebook",
        "name": name,
        "path": path,
        "format": "json",
        "content": {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": source,
                }
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        },
    }


def shared_lib(path):
    return jupyter_dir(
        "lib",
        path,
        [
            jupyter_file("__init__.py", "{}/__init__.py".format(path), ""),
            jupyter_file("tools.py", "{}/tools.py".format(path), "def run():\n    return 'ok'\n"),
            jupyter_file("sbx_tools.py", "{}/sbx_tools.py".format(path), "VALUE = 'sandbox'\n"),
            jupyter_file(
                "utils.py",
                "{}/utils.py".format(path),
                "def read_tools():\n"
                "    with open(\"lib/sbx_tools.py\", \"r\") as handle:\n"
                "        return handle.read()\n",
            ),
        ],
    )


def write_rewritten_shared_lib(path):
    path.mkdir(parents=True)
    (path / "__init__.py").write_text("", encoding="utf-8")
    (path / "tools.py").write_text("def run():\n    return 'ok'\n", encoding="utf-8")
    (path / "sbx_tools.py").write_text("VALUE = 'sandbox'\n", encoding="utf-8")
    (path / "utils.py").write_text(
        "from pathlib import Path\n\n"
        "def read_tools():\n"
        "    with open(Path(__file__).resolve().parent / \"sbx_tools.py\", \"r\") as handle:\n"
        "        return handle.read()\n",
        encoding="utf-8",
    )


def test_parse_tree_url_to_contents_api_preserves_token_query():
    location = parse_jupyter_contents_location(
        "https://lab.example.test/tree/course/notebooks?token=abc"
    )

    url = location.url_for(location.root_path)

    parsed = urlparse(url)
    assert "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path) == (
        "https://lab.example.test/api/contents/course/notebooks"
    )
    assert parse_qs(parsed.query) == {"token": ["abc"], "content": ["1"]}


def test_explicit_code_token_overrides_url_token():
    location = parse_jupyter_contents_location(
        "https://lab.example.test/tree/course?token=old"
    )

    parsed = urlparse(location.url_for(location.root_path, token="new"))

    assert parse_qs(parsed.query) == {"token": ["new"], "content": ["1"]}


def test_tree_url_for_preserves_token_without_content():
    location = parse_jupyter_contents_location(
        "https://lab.example.test/tree/course?token=abc&content=1"
    )

    parsed = urlparse(location.tree_url_for(token=None))

    assert "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path) == (
        "https://lab.example.test/tree/course"
    )
    assert parse_qs(parsed.query) == {"token": ["abc"]}


def test_parse_lab_tree_url_to_prefixed_contents_api():
    location = parse_jupyter_contents_location(
        "https://lab.example.test/user/session/lab/tree/work"
    )

    assert location.url_for(location.root_path) == (
        "https://lab.example.test/user/session/api/contents/work?content=1"
    )


def test_extract_jupyter_lab_links_from_lesson_iframe():
    html = """
    <html>
      <body>
        <iframe
          id="lab-iframe"
          title="Laboratory notebook"
          src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/L2/L2.ipynb?token=secret-token">
        </iframe>
      </body>
    </html>
    """

    links = extract_jupyter_lab_links(html, lesson_url="https://learn.example.test/lesson")

    assert len(links) == 1
    assert links[0].url == (
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/tree?token=secret-token"
    )
    assert links[0].token == "secret-token"
    assert links[0].lesson_url == "https://learn.example.test/lesson"
    assert links[0].group == "lessons"


def test_extract_jupyter_lab_links_accepts_iframe_without_token():
    html = """
    <html>
      <body>
        <iframe
          src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/project.ipynb">
        </iframe>
      </body>
    </html>
    """

    links = extract_jupyter_lab_links(
        html,
        lesson_url="https://learn.example.test/project",
        group="project",
    )

    assert len(links) == 1
    assert links[0].url == "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/tree"
    assert links[0].token == ""
    assert links[0].lesson_url == "https://learn.example.test/project"
    assert links[0].group == "project"


def test_extract_jupyter_lab_links_from_anchor_href():
    html = """
    <html>
      <body>
        <a href="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/lab/tree/project">
          Open project lab
        </a>
      </body>
    </html>
    """

    links = extract_jupyter_lab_links(html, group="project")

    assert len(links) == 1
    assert links[0].url == "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/tree"
    assert links[0].token == ""
    assert links[0].group == "project"


def test_extract_jupyter_lab_links_from_project_lab_tree_iframe():
    html = """
    <html>
      <body>
        <iframe
          title="Laboratory notebook"
          src="https://s172-29-64-174p8888.lab-aws-production.deeplearning.ai/lab/tree/project.ipynb?token=project-token">
        </iframe>
      </body>
    </html>
    """

    links = extract_jupyter_lab_links(
        html,
        lesson_url="https://learn.example.test/project",
        group="project",
    )

    assert len(links) == 1
    assert links[0].url == (
        "https://s172-29-64-174p8888.lab-aws-production.deeplearning.ai/tree?token=project-token"
    )
    assert links[0].token == "project-token"
    assert links[0].group == "project"


def test_redact_url_removes_token_values():
    text = (
        "GET https://lab.example.test/api/contents?token=secret&content=1 failed; "
        "open https://lab.example.test/tree?token=other"
    )

    assert redact_url(text) == (
        "GET https://lab.example.test/api/contents?token=REDACTED&content=1 failed; "
        "open https://lab.example.test/tree?token=REDACTED"
    )


def test_downloader_recurses_and_saves_supported_content(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": {
            "type": "directory",
            "name": "course",
            "path": "course",
            "content": [
                {
                    "type": "file",
                    "name": "README.md",
                    "path": "course/README.md",
                    "format": "text",
                    "content": "Course notes\n",
                },
                {
                    "type": "directory",
                    "name": "notebooks",
                    "path": "course/notebooks",
                    "content": [
                        {
                            "type": "notebook",
                            "name": "demo.ipynb",
                            "path": "course/notebooks/demo.ipynb",
                            "format": "json",
                            "content": {
                                "cells": [],
                                "metadata": {},
                                "nbformat": 4,
                                "nbformat_minor": 5,
                            },
                        },
                        {
                            "type": "file",
                            "name": "data.bin",
                            "path": "course/notebooks/data.bin",
                            "format": "base64",
                            "content": b64encode(b"abc").decode("ascii"),
                        },
                    ],
                },
                {
                    "type": "directory",
                    "name": ".git",
                    "path": "course/.git",
                    "content": [
                        {
                            "type": "file",
                            "name": "config",
                            "path": "course/.git/config",
                            "format": "text",
                            "content": "ignored",
                        }
                    ],
                },
            ],
        }
    }
    client = FakeJupyterClient(responses)
    downloader = JupyterCodeDownloader(client, tmp_path, "course-slug")

    summary = downloader.download("https://lab.example.test/tree/course")

    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    assert (code_dir / "README.md").read_text(encoding="utf-8") == "Course notes\n"
    notebook = json.loads((code_dir / "notebooks" / "demo.ipynb").read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert (code_dir / "notebooks" / "data.bin").read_bytes() == b"abc"
    assert not (code_dir / ".git").exists()
    assert summary.saved == 3
    assert summary.skipped == 0
    assert summary.failed == 0
    assert summary.files[0].path == "lessons/README.md"
    assert client.primed == []
    assert client.requested[0] == "https://lab.example.test/api/contents/course?content=1"


def test_downloader_keeps_model_directories_by_default(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                jupyter_file("README.md", "course/README.md", "notes\n"),
                jupyter_dir(
                    "models",
                    "course/models",
                    [jupyter_file("weights.bin", "course/models/weights.bin", "abc")],
                ),
            ],
        )
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    assert (code_dir / "README.md").exists()
    assert (code_dir / "models" / "weights.bin").read_text(encoding="utf-8") == "abc"
    assert summary.skip_dirs == []
    assert summary.saved == 2
    assert summary.skipped == 0


def test_downloader_skips_configured_directory_names_case_insensitively(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                jupyter_dir(
                    "Models",
                    "course/nested/Models",
                    None,
                )
            ],
        )
    }
    client = FakeJupyterClient(responses)

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
        skip_code_dirs=["models"],
    ).download("https://lab.example.test/tree/course")

    assert not (tmp_path / "course-slug" / "code" / "lessons" / "nested" / "Models").exists()
    assert summary.skip_dirs == ["models"]
    assert summary.saved == 0
    assert summary.skipped == 1
    assert summary.files[0].path == "lessons/nested/Models"
    assert summary.files[0].message == "skipped by config: Models directory"
    assert client.requested == ["https://lab.example.test/api/contents/course?content=1"]


def test_downloader_executes_lesson_notebooks_when_enabled(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [jupyter_notebook("demo.ipynb", "course/demo.ipynb", "print('hello')")],
        )
    }
    executor = FakeNotebookExecutor()

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
        execute_lesson_notebooks=True,
        notebook_executor=executor,
    ).download("https://lab.example.test/tree/course?token=secret")

    notebook = json.loads((tmp_path / "course-slug" / "code" / "lessons" / "demo.ipynb").read_text(encoding="utf-8"))
    assert notebook["cells"][0]["execution_count"] == 1
    assert notebook["cells"][0]["outputs"][0]["text"] == "executed\n"
    assert executor.calls == [("https://lab.example.test/api/contents", "course/demo.ipynb", "secret")]
    assert summary.saved == 1
    assert summary.executed == 1
    assert summary.execution_failed == 0
    assert summary.files[0].message == "executed"


def test_downloader_does_not_execute_project_notebooks(tmp_path):
    responses = {
        "https://project-lab.example.test/api/contents/project": jupyter_dir(
            "project",
            "project",
            [jupyter_notebook("project.ipynb", "project/project.ipynb", "print('project')")],
        ),
        "https://manual-lab.example.test/api/contents": jupyter_dir("", "", []),
    }
    executor = FakeNotebookExecutor()
    links = [JupyterLabLink("https://project-lab.example.test/tree/project", group="project")]

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
        execute_lesson_notebooks=True,
        notebook_executor=executor,
    ).download("https://manual-lab.example.test/tree", discovered_links=links)

    notebook = json.loads(
        (tmp_path / "course-slug" / "code" / "project" / "project.ipynb").read_text(encoding="utf-8")
    )
    assert notebook["cells"][0]["execution_count"] is None
    assert notebook["cells"][0]["outputs"] == []
    assert executor.calls == []
    assert summary.saved == 1
    assert summary.executed == 0


def test_downloader_saves_partial_notebook_when_execution_fails(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [jupyter_notebook("demo.ipynb", "course/demo.ipynb", "raise RuntimeError('boom')")],
        )
    }
    executor = FakeNotebookExecutor(fail=True)

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
        execute_lesson_notebooks=True,
        notebook_executor=executor,
    ).download("https://lab.example.test/tree/course")

    notebook = json.loads((tmp_path / "course-slug" / "code" / "lessons" / "demo.ipynb").read_text(encoding="utf-8"))
    assert notebook["cells"][0]["outputs"][0]["text"] == "executed\n"
    assert summary.saved == 1
    assert summary.failed == 0
    assert summary.executed == 0
    assert summary.execution_failed == 1
    assert summary.files[0].message == "execution failed: boom"


def test_downloader_does_not_execute_skipped_existing_notebook(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [jupyter_notebook("demo.ipynb", "course/demo.ipynb", "print('new')")],
        )
    }
    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    code_dir.mkdir(parents=True)
    (code_dir / "demo.ipynb").write_text(json.dumps({"cells": [], "metadata": {}}), encoding="utf-8")
    executor = FakeNotebookExecutor()

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
        execute_lesson_notebooks=True,
        notebook_executor=executor,
    ).download("https://lab.example.test/tree/course")

    assert executor.calls == []
    assert summary.saved == 0
    assert summary.skipped == 1
    assert summary.executed == 0


def test_downloader_skips_existing_file_unless_force(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": {
            "type": "directory",
            "name": "course",
            "path": "course",
            "content": [
                {
                    "type": "file",
                    "name": "app.py",
                    "path": "course/app.py",
                    "format": "text",
                    "content": "print('new')\n",
                }
            ],
        }
    }
    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    code_dir.mkdir(parents=True)
    (code_dir / "app.py").write_text("print('old')\n", encoding="utf-8")

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    assert (code_dir / "app.py").read_text(encoding="utf-8") == "print('old')\n"
    assert summary.saved == 0
    assert summary.skipped == 1

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
        force=True,
    ).download("https://lab.example.test/tree/course")

    assert (code_dir / "app.py").read_text(encoding="utf-8") == "print('new')\n"
    assert summary.saved == 1
    assert summary.skipped == 0


def test_downloader_saves_project_links_under_project_group(tmp_path):
    responses = {
        "https://project-lab.example.test/api/contents/project": {
            "type": "directory",
            "name": "project",
            "path": "project",
            "content": [
                {
                    "type": "file",
                    "name": "app.py",
                    "path": "project/app.py",
                    "format": "text",
                    "content": "print('project')\n",
                }
            ],
        },
        "https://manual-lab.example.test/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
    }
    links = [
        JupyterLabLink(
            "https://project-lab.example.test/tree/project?token=secret",
            token="secret",
            group="project",
        )
    ]

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download(
        "https://manual-lab.example.test/tree",
        discovered_links=links,
    )

    assert (tmp_path / "course-slug" / "code" / "project" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('project')\n"
    assert summary.saved == 1
    assert summary.files[0].path == "project/app.py"


def test_downloader_saves_lesson_and_project_discovered_links(tmp_path):
    responses = {
        "https://lesson-lab.example.test/api/contents": jupyter_dir(
            "",
            "",
            [
                jupyter_file(
                    "lesson.py",
                    "lesson.py",
                    "print('lesson')\n",
                )
            ],
        ),
        "https://project-lab.example.test/api/contents": jupyter_dir(
            "",
            "",
            [
                jupyter_file(
                    "project.py",
                    "project.py",
                    "print('project')\n",
                )
            ],
        ),
    }
    links = [
        JupyterLabLink("https://lesson-lab.example.test/tree", group="lessons"),
        JupyterLabLink("https://project-lab.example.test/tree", group="project"),
    ]

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download(
        "https://manual-lab.example.test/tree",
        discovered_links=links,
    )

    assert (tmp_path / "course-slug" / "code" / "lessons" / "lesson.py").read_text(
        encoding="utf-8"
    ) == "print('lesson')\n"
    assert (tmp_path / "course-slug" / "code" / "project" / "project.py").read_text(
        encoding="utf-8"
    ) == "print('project')\n"
    assert summary.saved == 2
    assert [file.path for file in summary.files] == [
        "lessons/lesson.py",
        "project/project.py",
    ]


def test_downloader_rejects_unsafe_paths(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": {
            "type": "directory",
            "name": "course",
            "path": "course",
            "content": [
                {
                    "type": "file",
                    "name": "evil.py",
                    "path": "course/../evil.py",
                    "format": "text",
                    "content": "bad",
                }
            ],
        }
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    assert not (tmp_path / "evil.py").exists()
    assert summary.saved == 0
    assert summary.skipped == 1
    assert summary.files[0].message == "unsafe path"


def test_downloader_records_invalid_code_url_as_failure(tmp_path):
    summary = JupyterCodeDownloader(
        FakeJupyterClient({}),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/files/course.zip")

    assert summary.saved == 0
    assert summary.failed == 1
    assert "Jupyter /tree or /api/contents" in summary.errors[0]


def test_downloader_uses_token_for_api_requests(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": {
            "type": "directory",
            "name": "course",
            "path": "course",
            "content": [],
        }
    }
    client = FakeJupyterClient(responses)

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
        code_token="secret",
    ).download("https://lab.example.test/tree/course")

    assert summary.failed == 0
    assert client.requested == ["https://lab.example.test/api/contents/course?token=secret&content=1"]


def test_downloader_skips_manual_url_without_reusable_token_when_links_are_discovered(tmp_path):
    responses = {
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
        "https://manual-lab.example.test/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
    }
    links = extract_jupyter_lab_links(
        """
        <iframe src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/L2/L2.ipynb?token=secret"></iframe>
        """,
    )
    client = FakeJupyterClient(responses)

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
    ).download(
        "https://manual-lab.example.test/tree",
        discovered_links=links,
    )

    assert summary.failed == 0
    assert client.requested == [
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents?token=secret&content=1",
    ]
    assert "secret" not in summary.source_url


def test_downloader_skips_bare_manual_url_when_discovered_link_matches_tree(tmp_path):
    responses = {
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
    }
    links = extract_jupyter_lab_links(
        """
        <iframe src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/L2/L2.ipynb?token=secret"></iframe>
        """,
    )
    client = FakeJupyterClient(responses)

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
    ).download(
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/tree",
        discovered_links=links,
    )

    assert summary.failed == 0
    assert client.requested == [
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents?token=secret&content=1"
    ]


def test_downloader_reuses_discovered_host_token_for_manual_code_url(tmp_path):
    responses = {
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents/course": {
            "type": "directory",
            "name": "course",
            "path": "course",
            "content": [],
        },
    }
    links = extract_jupyter_lab_links(
        """
        <iframe src="https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/notebooks/L2/L2.ipynb?token=secret"></iframe>
        """,
    )
    client = FakeJupyterClient(responses)

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
    ).download(
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/tree/course",
        discovered_links=links,
    )

    assert summary.failed == 0
    assert client.requested == [
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents?token=secret&content=1",
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents/course?token=secret&content=1",
    ]


def test_downloader_redacts_token_from_source_and_errors(tmp_path):
    class TokenErrorClient:
        def get_json(self, url):
            raise RuntimeError("GET {} failed".format(url))

    summary = JupyterCodeDownloader(
        TokenErrorClient(),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree?token=secret")

    assert "secret" not in summary.source_url
    assert "token=REDACTED" in summary.source_url
    assert "secret" not in summary.errors[0]


def test_downloader_authenticates_after_jupyter_403(tmp_path):
    root = {
        "type": "directory",
        "name": "course",
        "path": "course",
        "content": [],
    }
    client = FakeJupyterClient(
        {"https://lab.example.test/api/contents/course": FakeHttpError(403)},
        auth_payload=root,
    )

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
        code_token="secret",
    ).download("https://lab.example.test/tree/course")

    assert summary.failed == 0
    assert client.authenticated == [
        (
            "https://lab.example.test/tree/course?token=secret",
            "https://lab.example.test/api/contents/course?token=secret&content=1",
        )
    ]


def test_downloader_primes_tree_with_token_after_api_403(tmp_path):
    root = {
        "type": "directory",
        "name": "course",
        "path": "course",
        "content": [],
    }
    client = TokenPrimingJupyterClient(
        {"https://lab.example.test/api/contents/course": root}
    )

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
        code_token="secret",
    ).download("https://lab.example.test/tree/course")

    assert summary.failed == 0
    assert client.primed == ["https://lab.example.test/tree/course?token=secret"]
    assert client.authenticated == []


def test_downloader_reports_jupyter_auth_error_without_authenticator(tmp_path):
    class NoAuthJupyterClient:
        def __init__(self, responses):
            self.responses = responses

        def get_json(self, url):
            parsed = urlparse(url)
            key = "{}://{}{}".format(parsed.scheme, parsed.netloc, parsed.path)
            raise self.responses[key]

    client = NoAuthJupyterClient({"https://lab.example.test/api/contents/course": FakeHttpError(403)})

    summary = JupyterCodeDownloader(
        client,
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    assert summary.failed == 1
    assert "Jupyter authentication or a live lab session is required" in summary.errors[0]
    assert "Safari cookies are not reused" in summary.errors[0]


def test_downloader_treats_api_timeout_as_recoverable_jupyter_auth_error(tmp_path):
    class NoAuthTimeoutClient:
        def get_json(self, url):
            raise RuntimeError("APIRequestContext.get: Timeout 30000ms exceeded.")

    summary = JupyterCodeDownloader(
        NoAuthTimeoutClient(),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    assert summary.failed == 1
    assert "live lab session" in summary.errors[0]


def test_downloader_deduplicates_identical_nested_lib_and_rewrites_references(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                shared_lib("course/lib"),
                jupyter_dir(
                    "L2",
                    "course/L2",
                    [
                        shared_lib("course/L2/lib"),
                        jupyter_file(
                            "demo.py",
                            "course/L2/demo.py",
                            "from lib.tools import run\nVALUE = run()\n",
                        ),
                        jupyter_notebook(
                            "L2.ipynb",
                            "course/L2/L2.ipynb",
                            "from lib.tools import run\nrun()",
                        ),
                    ],
                ),
            ],
        )
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    assert (code_dir / "lib" / "tools.py").exists()
    assert not (code_dir / "L2" / "lib").exists()

    demo = (code_dir / "L2" / "demo.py").read_text(encoding="utf-8")
    assert "_SCHOLARIUM_SHARED_CODE_ROOT = Path(__file__).resolve().parents[1]" in demo
    assert demo.index("_SCHOLARIUM_SHARED_CODE_ROOT") < demo.index("from lib.tools import run")

    notebook = json.loads((code_dir / "L2" / "L2.ipynb").read_text(encoding="utf-8"))
    assert "_SCHOLARIUM_SHARED_CODE_ROOT = Path.cwd().resolve().parents[0]" in notebook["cells"][0]["source"]
    assert "from lib.tools import run" in notebook["cells"][1]["source"]

    utils = (code_dir / "lib" / "utils.py").read_text(encoding="utf-8")
    assert 'open(Path(__file__).resolve().parent / "sbx_tools.py", "r")' in utils

    assert summary.saved == 6
    assert summary.deduplicated == 4
    assert summary.rewritten == 3
    assert len([file for file in summary.files if file.status == "deduplicated"]) == 4


def test_downloader_deduplicates_against_previously_rewritten_shared_lib(tmp_path):
    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    write_rewritten_shared_lib(code_dir / "lib")
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                shared_lib("course/lib"),
                jupyter_dir(
                    "L2",
                    "course/L2",
                    [
                        shared_lib("course/L2/lib"),
                    ],
                ),
            ],
        )
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    assert (code_dir / "lib" / "tools.py").exists()
    assert not (code_dir / "L2" / "lib").exists()
    assert 'Path(__file__).resolve().parent / "sbx_tools.py"' in (
        code_dir / "lib" / "utils.py"
    ).read_text(encoding="utf-8")
    assert summary.saved == 0
    assert summary.skipped == 4
    assert summary.deduplicated == 4


def test_downloader_promotes_first_identical_nested_folder_when_root_is_missing(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                jupyter_dir(
                    "L2",
                    "course/L2",
                    [
                        jupyter_dir(
                            "lib",
                            "course/L2/lib",
                            [jupyter_file("__init__.py", "course/L2/lib/__init__.py", "VALUE = 1\n")],
                        ),
                        jupyter_file(
                            "demo.py",
                            "course/L2/demo.py",
                            "from lib import VALUE\n",
                        ),
                    ],
                ),
                jupyter_dir(
                    "L3",
                    "course/L3",
                    [
                        jupyter_dir(
                            "lib",
                            "course/L3/lib",
                            [jupyter_file("__init__.py", "course/L3/lib/__init__.py", "VALUE = 1\n")],
                        ),
                        jupyter_file(
                            "demo.py",
                            "course/L3/demo.py",
                            "from lib import VALUE\n",
                        ),
                    ],
                ),
            ],
        )
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    assert (code_dir / "lib" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (code_dir / "L2" / "lib").exists()
    assert not (code_dir / "L3" / "lib").exists()
    assert "Path(__file__).resolve().parents[1]" in (code_dir / "L2" / "demo.py").read_text(
        encoding="utf-8"
    )
    assert "Path(__file__).resolve().parents[1]" in (code_dir / "L3" / "demo.py").read_text(
        encoding="utf-8"
    )
    assert summary.saved == 3
    assert summary.deduplicated == 1
    assert summary.rewritten == 2
    assert any(file.path == "lessons/lib/__init__.py" for file in summary.files)


def test_downloader_keeps_same_name_folders_when_contents_differ(tmp_path):
    responses = {
        "https://lab.example.test/api/contents/course": jupyter_dir(
            "course",
            "course",
            [
                jupyter_dir(
                    "lib",
                    "course/lib",
                    [jupyter_file("tool.py", "course/lib/tool.py", "VALUE = 'root'\n")],
                ),
                jupyter_dir(
                    "L2",
                    "course/L2",
                    [
                        jupyter_dir(
                            "lib",
                            "course/L2/lib",
                            [jupyter_file("tool.py", "course/L2/lib/tool.py", "VALUE = 'lesson'\n")],
                        )
                    ],
                ),
            ],
        )
    }

    summary = JupyterCodeDownloader(
        FakeJupyterClient(responses),
        tmp_path,
        "course-slug",
    ).download("https://lab.example.test/tree/course")

    code_dir = tmp_path / "course-slug" / "code" / "lessons"
    assert (code_dir / "lib" / "tool.py").exists()
    assert (code_dir / "L2" / "lib" / "tool.py").exists()
    assert summary.saved == 2
    assert summary.deduplicated == 0
    assert summary.rewritten == 0
