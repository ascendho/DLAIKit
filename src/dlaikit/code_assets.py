import base64
import json
import re
import shutil
import tempfile
import uuid
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

CODE_GROUP_LESSONS = "lessons"
CODE_GROUP_PROJECT = "project"
CODE_GROUPS = {CODE_GROUP_LESSONS, CODE_GROUP_PROJECT}
CODE_LAYOUT_FLAT = "flat"
CODE_LAYOUT_GROUPED = "grouped"
CODE_LAYOUT_VERSION = 2


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
    source_urls: List[str] = field(default_factory=list)
    skip_dirs: List[str] = field(default_factory=list)
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
    group: str = CODE_GROUP_LESSONS


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
    def __init__(
        self,
        client,
        output_root,
        course_slug,
        force=False,
        code_token="",
        skip_code_dirs=None,
        state_root=None,
    ):
        self.client = client
        self.output_dir = Path(output_root) / course_slug / "code"
        self.force = force
        self.code_token = code_token
        self.skip_dirs = _normalized_names(skip_code_dirs)
        self.state_path = (
            Path(state_root) / "{}.json".format(course_slug)
            if state_root is not None
            else Path(output_root)
            / ".auth"
            / "code-downloads"
            / "{}.json".format(course_slug)
        )

    def download(self, code_url, discovered_links=None):
        discovered_links = list(discovered_links or [])
        download_sources = self._download_sources(code_url, discovered_links)
        layout = _code_layout(download_sources)
        source_url = download_sources[0][0] if download_sources else code_url
        summary = CodeAssetSummary(
            source_url=redact_url(source_url),
            output_dir=self.output_dir,
            source_urls=[redact_url(source[0]) for source in download_sources],
            skip_dirs=list(self.skip_dirs),
        )
        if not download_sources:
            return summary

        completion_fingerprint = _completion_fingerprint(code_url, discovered_links, layout)
        if not self.force and self._is_complete(completion_fingerprint):
            summary.skipped += 1
            summary.files.append(
                CodeAssetFile(
                    path=".",
                    status="skipped",
                    message="code assets already downloaded completely",
                )
            )
            return summary

        rebuild = self.state_path.exists()
        staging_dir = None
        if rebuild:
            self.output_dir.parent.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(
                tempfile.mkdtemp(prefix=".dlaikit-code-", dir=str(self.output_dir.parent))
            )
            self._active_output_dir = staging_dir
        else:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._active_output_dir = self.output_dir
        self._active_layout = layout

        for source_url, token, group in download_sources:
            try:
                location = parse_jupyter_contents_location(source_url)
                root = self._fetch_root(location, token)
                self._walk_entry(root, location, summary, token, group)
            except Exception as exc:
                summary.failed += 1
                summary.errors.append(redact_url(str(exc)))

        if summary.failed == 0:
            try:
                if staging_dir is not None:
                    self._replace_output(staging_dir)
                    staging_dir = None
                self._write_completion_marker(completion_fingerprint)
            except Exception as exc:
                summary.failed += 1
                summary.errors.append("Could not finalize code assets: {}".format(exc))
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)
        return summary

    def _is_complete(self, fingerprint):
        if not self.output_dir.is_dir():
            return False
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if payload.get("code_url") != fingerprint.get("code_url"):
            return False
        if payload.get("layout_version") != CODE_LAYOUT_VERSION:
            return False
        if payload.get("layout") != fingerprint.get("layout"):
            return False
        try:
            completed_sources = {tuple(source) for source in payload.get("sources", [])}
            requested_sources = {tuple(source) for source in fingerprint.get("sources", [])}
        except (TypeError, ValueError):
            return False
        if requested_sources:
            return requested_sources.issubset(completed_sources)
        return bool(fingerprint.get("code_url"))

    def _replace_output(self, staging_dir):
        backup_dir = self.output_dir.with_name(
            ".dlaikit-code-backup-{}".format(uuid.uuid4().hex)
        )
        had_output = self.output_dir.exists()
        if had_output:
            self.output_dir.replace(backup_dir)
        try:
            staging_dir.replace(self.output_dir)
        except Exception:
            if had_output and backup_dir.exists():
                backup_dir.replace(self.output_dir)
            raise
        if backup_dir.is_dir():
            shutil.rmtree(backup_dir)
        elif backup_dir.exists():
            backup_dir.unlink()

    def _write_completion_marker(self, fingerprint):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(fingerprint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _download_sources(self, code_url, discovered_links):
        sources = []
        host_tokens = _host_tokens(discovered_links)
        if self.code_token:
            sources.extend(
                (link.url, self.code_token, _normalize_code_group(link.group))
                for link in discovered_links
            )
            sources.append((code_url, self.code_token, CODE_GROUP_LESSONS))
        else:
            sources.extend(
                (link.url, link.token or None, _normalize_code_group(link.group))
                for link in discovered_links
            )
            manual_token = _token_from_url(code_url) or host_tokens.get(urlparse(code_url).netloc)
            if manual_token or not discovered_links:
                sources.append((code_url, manual_token, CODE_GROUP_LESSONS))

        unique_sources = {}
        for source_url, token, group in sources:
            if not source_url:
                continue
            identity = _source_identity(source_url)
            candidate = (source_url, token, group)
            current = unique_sources.get(identity)
            if current is None or (
                current[2] == CODE_GROUP_LESSONS and group == CODE_GROUP_PROJECT
            ):
                unique_sources[identity] = candidate
        return list(unique_sources.values())

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

    def _walk_entry(self, entry, location, summary, token, group):
        entry_type = entry.get("type", "")
        if entry_type == "directory":
            self._walk_directory(entry, location, summary, token, group)
            return
        if entry_type in {"file", "notebook"}:
            self._save_file(entry, location, summary, token, group)
            return

        path = _relative_remote_path(
            entry.get("path", ""),
            location.root_path,
            entry.get("name", ""),
        )
        summary.skipped += 1
        summary.files.append(
            CodeAssetFile(
                path=_asset_path(group, path, self._active_layout),
                status="skipped",
                message="unsupported Jupyter content type: {}".format(entry_type or "unknown"),
            )
        )

    def _walk_directory(self, entry, location, summary, token, group):
        name = entry.get("name", "")
        path = _clean_remote_path(entry.get("path", name))
        if _should_skip_directory(path, name):
            return

        relative_path = _relative_remote_path(path, location.root_path, name)
        matched_dir = _matching_skip_directory(relative_path, name, self.skip_dirs)
        if matched_dir:
            self._record_directory_skip(summary, group, relative_path, matched_dir)
            return

        content = entry.get("content")
        if content is None:
            entry = self.client.get_json(location.url_for(path, token=token))
            content = entry.get("content")
        if content is None:
            raise CodeDownloadError("directory listing is missing content: {}".format(path or "/"))

        for child in content:
            self._walk_entry(child, location, summary, token, group)

    def _save_file(self, entry, location, summary, token, group):
        name = entry.get("name", "")
        path = _clean_remote_path(entry.get("path", name))
        relative_path = _relative_remote_path(path, location.root_path, name)
        asset_path = _asset_path(group, relative_path, self._active_layout)

        if _should_skip_file(relative_path, name):
            return

        output_root = self._active_output_dir
        if self._active_layout == CODE_LAYOUT_GROUPED:
            output_root = output_root / _normalize_code_group(group)
        output_path = _safe_output_path(output_root, relative_path)
        if output_path is None:
            summary.skipped += 1
            summary.files.append(
                CodeAssetFile(
                    path=asset_path,
                    status="skipped",
                    message="unsafe path",
                )
            )
            return

        if output_path.exists() and not self.force:
            summary.skipped += 1
            summary.files.append(CodeAssetFile(path=asset_path, status="skipped"))
            return

        try:
            if "content" not in entry or entry.get("content") is None:
                entry = self.client.get_json(location.url_for(path, token=token))
            data = _entry_bytes(entry)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
        except Exception as exc:
            summary.failed += 1
            summary.files.append(
                CodeAssetFile(
                    path=asset_path,
                    status="failed",
                    message=str(exc),
                )
            )
            return

        summary.saved += 1
        summary.files.append(
            CodeAssetFile(
                path=asset_path,
                status="saved",
                bytes=len(data),
            )
        )

    def _record_directory_skip(self, summary, group, relative_path, directory_name):
        summary.skipped += 1
        summary.files.append(
            CodeAssetFile(
                path=_asset_path(group, relative_path, self._active_layout),
                status="skipped",
                message="skipped by config: {} directory".format(directory_name),
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


def extract_jupyter_lab_links(html, lesson_url="", group=CODE_GROUP_LESSONS):
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()
    group = _normalize_code_group(group)

    for lab_url in _jupyter_lab_urls(soup):
        if "lab-aws-production.deeplearning.ai" not in lab_url:
            continue
        if not _looks_like_jupyter_url(lab_url):
            continue
        token = _token_from_url(lab_url)
        tree_url = jupyter_tree_url_from_iframe_src(lab_url)
        key = (redact_url(tree_url), token)
        if key in seen:
            continue
        seen.add(key)
        links.append(JupyterLabLink(tree_url, token=token, lesson_url=lesson_url, group=group))

    return links


def _jupyter_lab_urls(soup):
    for iframe in soup.find_all("iframe", src=True):
        yield iframe["src"]
    for anchor in soup.find_all("a", href=True):
        yield anchor["href"]


def _looks_like_jupyter_url(url):
    path = urlparse(url).path.rstrip("/")
    return any(
        marker in path
        for marker in (
            "/notebooks/",
            "/lab/tree",
            "/tree",
            "/api/contents",
        )
    )


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


def _matching_skip_directory(relative_path, name, skip_dirs):
    parts = PurePosixPath(_clean_remote_path(relative_path) or name).parts
    return next((part for part in parts if part.lower() in skip_dirs), "")


def _normalized_names(values):
    names = []
    for value in values or []:
        name = str(value).strip().strip("/").lower()
        if name:
            names.append(name)
    return sorted(set(names))


def _host_tokens(links):
    tokens = {}
    for link in links:
        token = link.token or _token_from_url(link.url)
        if not token:
            continue
        host = urlparse(link.url).netloc
        tokens.setdefault(host, token)
    return tokens


def _source_identity(url):
    try:
        location = parse_jupyter_contents_location(url)
    except CodeDownloadError:
        parsed = urlparse(url)
        return (
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip("/"),
        )

    parsed = urlparse(location.base_url)
    return (
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip("/"),
        _clean_remote_path(location.root_path),
    )


def _completion_fingerprint(code_url, discovered_links, layout):
    sources = sorted(
        {
            (
                normalize_url_without_query(link.lesson_url)
                if link.lesson_url
                else urlparse(link.url).path.rstrip("/"),
                _normalize_code_group(link.group),
            )
            for link in discovered_links
        }
    )
    return {
        "code_url": redact_url(code_url),
        "layout": layout,
        "layout_version": CODE_LAYOUT_VERSION,
        "sources": [list(source) for source in sources],
    }


def normalize_url_without_query(url):
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _normalize_code_group(group):
    return group if group in CODE_GROUPS else CODE_GROUP_LESSONS


def _code_layout(download_sources):
    groups = {_normalize_code_group(source[2]) for source in download_sources}
    return CODE_LAYOUT_GROUPED if len(groups) > 1 else CODE_LAYOUT_FLAT


def _asset_path(group, relative_path, layout):
    relative_path = str(relative_path or "").strip("/")
    if layout == CODE_LAYOUT_FLAT:
        return relative_path or "."
    group = _normalize_code_group(group)
    return "{}/{}".format(group, relative_path) if relative_path else group


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
        "Jupyter authentication or a live lab session is required for {}. "
        "Activate the lab in the opened project Chrome profile, set code_token in "
        "dlaikit.json, or include ?token=... in code_url. Safari cookies cannot be "
        "reused by Playwright.".format(host)
    )
