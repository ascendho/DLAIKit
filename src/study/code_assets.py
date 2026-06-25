import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import List
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup


SKIP_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".ipynb_checkpoints",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    ".env",
    "node_modules",
}

SKIP_FILE_NAMES = {
    ".DS_Store",
}


class CodeDownloadError(RuntimeError):
    pass


@dataclass
class CodeAssetFile:
    path: str
    status: str
    bytes: int = 0
    message: str = ""


@dataclass
class CodeAssetSummary:
    source_url: str
    output_dir: Path
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    files: List[CodeAssetFile] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class JupyterLabLink:
    url: str
    token: str = ""
    lesson_url: str = ""


@dataclass
class ContentsApiLocation:
    base_url: str
    root_path: str = ""
    query: str = ""

    def url_for(self, contents_path, token=None):
        path = _clean_remote_path(contents_path)
        base_path = urlparse(self.base_url).path.rstrip("/")
        full_path = base_path
        if path:
            full_path = "{}/{}".format(full_path, _quote_path(path))

        parsed = urlparse(self.base_url)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                full_path,
                "",
                _query_with_content(self.query, token=token),
                "",
            )
        )

    def tree_url_for(self, tree_path=None, token=None):
        parsed = urlparse(self.base_url)
        prefix = parsed.path.rstrip("/")
        marker = "/api/contents"
        if prefix.endswith(marker):
            prefix = prefix[: -len(marker)]
        path = "{}/tree".format(prefix.rstrip("/")) if prefix else "/tree"
        remote_path = _clean_remote_path(self.root_path if tree_path is None else tree_path)
        if remote_path:
            path = "{}/{}".format(path.rstrip("/"), _quote_path(remote_path))
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                path,
                "",
                _query_without_content(self.query, token=token),
                "",
            )
        )


class BrowserJupyterClient:
    def __init__(self, browser_fetcher):
        self.browser_fetcher = browser_fetcher

    def prime(self, url):
        self.browser_fetcher.fetch_page(url)

    def get_json(self, url):
        return self.browser_fetcher.fetch_json(url)

    def authenticate(self, login_url, check_url):
        return self.browser_fetcher.authenticate_jupyter(login_url, check_url)


class JupyterCodeDownloader:
    def __init__(self, client, output_root, course_slug, force=False, code_token=""):
        self.client = client
        self.output_dir = Path(output_root) / course_slug / "code"
        self.force = force
        self.code_token = code_token

    def download(self, code_url, discovered_links=None):
        summary = CodeAssetSummary(source_url=redact_url(code_url), output_dir=self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            downloaded = False
            last_exc = None
            for source_url, token in self._download_sources(code_url, discovered_links or []):
                try:
                    location = parse_jupyter_contents_location(source_url)
                    root = self._fetch_root(location, token)
                    self._walk_entry(root, location, summary)
                    downloaded = True
                except Exception as exc:
                    last_exc = exc
                    if not discovered_links:
                        raise
            if not downloaded and last_exc is not None:
                raise last_exc
        except Exception as exc:
            summary.failed += 1
            summary.errors.append(redact_url(str(exc)))

        return summary

    def _download_sources(self, code_url, discovered_links):
        if self.code_token:
            sources = [(code_url, self.code_token)]
            sources.extend((link.url, self.code_token) for link in discovered_links)
        elif discovered_links:
            sources = [(link.url, link.token or None) for link in discovered_links]
        else:
            sources = [(code_url, None)]

        seen = set()
        unique_sources = []
        for source_url, token in sources:
            key = (redact_url(source_url), token or "")
            if key in seen:
                continue
            seen.add(key)
            unique_sources.append((source_url, token))
        return unique_sources

    def _fetch_root(self, location, token):
        api_url = location.url_for(location.root_path, token=token)
        try:
            return self.client.get_json(api_url)
        except Exception as exc:
            if not _is_jupyter_auth_error(exc):
                raise
            login_url = location.tree_url_for(token=token)
            if token and hasattr(self.client, "prime"):
                try:
                    self.client.prime(login_url)
                    return self.client.get_json(api_url)
                except Exception as prime_exc:
                    if not _is_jupyter_auth_error(prime_exc):
                        raise
            if not hasattr(self.client, "authenticate"):
                raise CodeDownloadError(_jupyter_auth_message(location)) from exc

            try:
                payload = self.client.authenticate(login_url, api_url)
                if payload is not None:
                    return payload
            except Exception as auth_exc:
                raise CodeDownloadError("{} {}".format(_jupyter_auth_message(location), auth_exc)) from exc

            return self.client.get_json(api_url)

    def _walk_entry(self, entry, location, summary):
        entry_type = entry.get("type", "")
        if entry_type == "directory":
            self._walk_directory(entry, location, summary)
            return
        if entry_type in {"file", "notebook"}:
            self._save_file(entry, location, summary)
            return

        path = _relative_remote_path(
            entry.get("path", ""),
            location.root_path,
            entry.get("name", ""),
        )
        summary.skipped += 1
        summary.files.append(
            CodeAssetFile(
                path=path,
                status="skipped",
                message="unsupported Jupyter content type: {}".format(entry_type or "unknown"),
            )
        )

    def _walk_directory(self, entry, location, summary):
        name = entry.get("name", "")
        path = _clean_remote_path(entry.get("path", name))
        if _should_skip_directory(path, name):
            return

        content = entry.get("content")
        if content is None:
            entry = self.client.get_json(location.url_for(path, token=self.code_token or None))
            content = entry.get("content")
        if content is None:
            raise CodeDownloadError("directory listing is missing content: {}".format(path or "/"))

        for child in content:
            self._walk_entry(child, location, summary)

    def _save_file(self, entry, location, summary):
        name = entry.get("name", "")
        path = _clean_remote_path(entry.get("path", name))
        relative_path = _relative_remote_path(path, location.root_path, name)

        if _should_skip_file(relative_path, name):
            return

        output_path = _safe_output_path(self.output_dir, relative_path)
        if output_path is None:
            summary.skipped += 1
            summary.files.append(
                CodeAssetFile(
                    path=relative_path,
                    status="skipped",
                    message="unsafe path",
                )
            )
            return

        if output_path.exists() and not self.force:
            summary.skipped += 1
            summary.files.append(CodeAssetFile(path=relative_path, status="skipped"))
            return

        try:
            if "content" not in entry or entry.get("content") is None:
                entry = self.client.get_json(location.url_for(path, token=self.code_token or None))
            data = _entry_bytes(entry)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
        except Exception as exc:
            summary.failed += 1
            summary.files.append(
                CodeAssetFile(
                    path=relative_path,
                    status="failed",
                    message=str(exc),
                )
            )
            return

        summary.saved += 1
        summary.files.append(
            CodeAssetFile(
                path=relative_path,
                status="saved",
                bytes=len(data),
            )
        )


def parse_jupyter_contents_location(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]

    if "api" in parts and "contents" in parts:
        contents_index = parts.index("contents")
        if contents_index == 0 or parts[contents_index - 1] != "api":
            raise CodeDownloadError("Code URL must point to a Jupyter contents API.")
        base_parts = parts[: contents_index + 1]
        root_parts = parts[contents_index + 1 :]
        return ContentsApiLocation(
            base_url=_url_with_path(parsed, base_parts),
            root_path="/".join(root_parts),
            query=parsed.query,
        )

    if "tree" not in parts:
        raise CodeDownloadError("Code URL must be a Jupyter /tree or /api/contents URL.")

    tree_index = parts.index("tree")
    if tree_index > 0 and parts[tree_index - 1] == "lab":
        prefix_parts = parts[: tree_index - 1]
    else:
        prefix_parts = parts[:tree_index]
    root_parts = parts[tree_index + 1 :]

    return ContentsApiLocation(
        base_url=_url_with_path(parsed, [*prefix_parts, "api", "contents"]),
        root_path="/".join(root_parts),
        query=parsed.query,
    )


def extract_jupyter_lab_links(html, lesson_url=""):
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()

    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "lab-aws-production.deeplearning.ai" not in src:
            continue
        token = _token_from_url(src)
        if not token:
            continue
        tree_url = jupyter_tree_url_from_iframe_src(src)
        key = (redact_url(tree_url), token)
        if key in seen:
            continue
        seen.add(key)
        links.append(JupyterLabLink(tree_url, token=token, lesson_url=lesson_url))

    return links


def jupyter_tree_url_from_iframe_src(src):
    parsed = urlparse(src)
    path = parsed.path

    if "/notebooks/" in path:
        root_path = path.split("/notebooks/", 1)[0]
    elif "/lab/tree/" in path:
        root_path = path.split("/lab/tree/", 1)[0]
    elif "/tree/" in path:
        root_path = path.split("/tree/", 1)[0]
    else:
        root_path = ""

    tree_path = "{}/tree".format(root_path.rstrip("/")) if root_path else "/tree"
    token = _token_from_url(src)
    query = urlencode({"token": token}) if token else ""
    return urlunparse((parsed.scheme, parsed.netloc, tree_path, "", query, ""))


def redact_url(text):
    return re.sub(r"([?&]token=)[^&\s\"']+", r"\1REDACTED", str(text))


def _url_with_path(parsed, parts):
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            "/" + _quote_path("/".join(parts)),
            "",
            "",
            "",
        )
    )


def _token_from_url(url):
    return parse_qs(urlparse(url).query).get("token", [""])[0]


def _query_with_content(query, token=None):
    pairs = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key not in {"content", "token"}
    ]
    if token is not None:
        pairs.append(("token", token))
    else:
        pairs.extend((key, value) for key, value in parse_qsl(query, keep_blank_values=True) if key == "token")
    pairs.append(("content", "1"))
    return urlencode(pairs)


def _query_without_content(query, token=None):
    pairs = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if key not in {"content", "token"}
    ]
    if token is not None:
        pairs.append(("token", token))
    else:
        pairs.extend((key, value) for key, value in parse_qsl(query, keep_blank_values=True) if key == "token")
    return urlencode(pairs)


def _quote_path(path):
    return "/".join(quote(part) for part in path.split("/") if part)


def _clean_remote_path(path):
    return str(path or "").strip("/")


def _relative_remote_path(remote_path, root_path, name):
    remote_path = _clean_remote_path(remote_path)
    root_path = _clean_remote_path(root_path)
    if root_path and remote_path == root_path:
        return name or PurePosixPath(remote_path).name
    if root_path and remote_path.startswith(root_path + "/"):
        return remote_path[len(root_path) + 1 :]
    return remote_path or name


def _should_skip_directory(path, name):
    parts = PurePosixPath(_clean_remote_path(path) or name).parts
    return any(part in SKIP_DIRECTORY_NAMES or part.startswith(".") for part in parts)


def _should_skip_file(relative_path, name):
    filename = name or PurePosixPath(relative_path).name
    return filename in SKIP_FILE_NAMES


def _safe_output_path(output_dir, relative_path):
    path = PurePosixPath(str(relative_path))
    if path.is_absolute():
        return None
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None

    root = Path(output_dir).resolve()
    candidate = (root / Path(*path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _entry_bytes(entry):
    content = entry.get("content")
    if content is None:
        raise CodeDownloadError("file content is missing")

    if entry.get("type") == "notebook":
        if isinstance(content, str):
            return content.encode("utf-8")
        return (json.dumps(content, ensure_ascii=False, indent=1) + "\n").encode("utf-8")

    if entry.get("format") == "base64":
        return base64.b64decode(content)

    if isinstance(content, str):
        return content.encode("utf-8")

    return (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _is_jupyter_auth_error(exc):
    status = getattr(exc, "status", None)
    if status in {401, 403}:
        return True
    message = str(exc)
    return (
        "HTTP 401" in message
        or "HTTP 403" in message
        or "Timeout" in message
        or "Token authentication is enabled" in message
    )


def _jupyter_auth_message(location):
    host = urlparse(location.base_url).netloc
    return (
        "Jupyter authentication or a live lab session is required for {}. Safari cookies "
        "are not reused by Playwright; set code_token in dlai-transcripts.json, include "
        "?token=... in code_url, or set browser_visibility to visible and log in in the "
        "opened browser.".format(host)
    )
