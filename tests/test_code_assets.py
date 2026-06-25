import json
from base64 import b64encode
from urllib.parse import parse_qs, urlparse

from study.code_assets import (
    extract_jupyter_lab_links,
    JupyterCodeDownloader,
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

    code_dir = tmp_path / "course-slug" / "code"
    assert (code_dir / "README.md").read_text(encoding="utf-8") == "Course notes\n"
    notebook = json.loads((code_dir / "notebooks" / "demo.ipynb").read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert (code_dir / "notebooks" / "data.bin").read_bytes() == b"abc"
    assert not (code_dir / ".git").exists()
    assert summary.saved == 3
    assert summary.skipped == 0
    assert summary.failed == 0
    assert client.primed == []
    assert client.requested[0] == "https://lab.example.test/api/contents/course?content=1"


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
    code_dir = tmp_path / "course-slug" / "code"
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


def test_downloader_uses_discovered_lab_link_before_manual_url(tmp_path):
    responses = {
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents": {
            "type": "directory",
            "name": "",
            "path": "",
            "content": [],
        },
        "https://manual-lab.example.test/api/contents": FakeHttpError(403),
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
        "https://s172-29-2-142p8888.lab-aws-production.deeplearning.ai/api/contents?token=secret&content=1"
    ]
    assert "secret" not in summary.source_url


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
