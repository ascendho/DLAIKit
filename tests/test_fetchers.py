import json

import pytest

from dlaikit.fetchers import BrowserFetcher, LoginRequiredError, NavigationError


class DummyContext:
    def __init__(self):
        self.pages = []
        self.storage_paths = []

    def new_page(self):
        page = DummyPage(len(self.pages))
        self.pages.append(page)
        return page

    def storage_state(self, path):
        self.storage_paths.append(path)

    def close(self):
        pass


class DummyPage:
    def __init__(self, index):
        self.index = index
        self.closed = False

    def goto(self, url, wait_until, timeout):
        if self.index == 0:
            raise RuntimeError("Page.goto: net::ERR_CONNECTION_CLOSED at {}".format(url))

    def wait_for_load_state(self, state, timeout):
        pass

    def wait_for_function(self, script, timeout, arg=None):
        pass

    def content(self):
        return "<html><body><button>Show Transcript</button><p>Loaded lesson.</p></body></html>"

    def close(self):
        self.closed = True


class DummyLoginContext:
    def __init__(self):
        self.pages = []
        self.storage_paths = []

    def new_page(self):
        page = DummyLoginPage()
        self.pages.append(page)
        return page

    def storage_state(self, path):
        self.storage_paths.append(path)

    def close(self):
        pass


class DummyLoginPage:
    def __init__(self):
        self.logged_in = False
        self.closed = False

    def goto(self, url, wait_until, timeout):
        pass

    def wait_for_load_state(self, state, timeout):
        pass

    def wait_for_function(self, script, timeout, arg=None):
        if "hasPasswordInput" in script:
            self.logged_in = True

    def content(self):
        if self.logged_in:
            return "<html><body><button>Show Transcript</button><p>Loaded after login.</p></body></html>"
        return '<html><body><button>Sign In</button><input type="password"></body></html>'

    def close(self):
        self.closed = True


def test_browser_fetcher_retries_transient_navigation_error(tmp_path):
    context = DummyContext()
    fetcher = BrowserFetcher(
        tmp_path / ".auth" / "deeplearning_ai.json",
        navigation_retries=1,
        retry_delay_seconds=0,
    )
    fetcher._context = context

    html = fetcher.fetch("https://learn.deeplearning.ai/courses/course/lesson/id/name")

    assert "Loaded lesson" in html
    assert len(context.pages) == 2
    assert all(page.closed for page in context.pages)
    assert context.storage_paths == [str(tmp_path / ".auth" / "deeplearning_ai.json")]


def test_browser_fetcher_retries_then_raises_navigation_error(tmp_path):
    class OfflinePage(DummyPage):
        def goto(self, url, wait_until, timeout):
            raise RuntimeError("Page.goto: net::ERR_INTERNET_DISCONNECTED at {}".format(url))

    class OfflineContext(DummyContext):
        def new_page(self):
            page = OfflinePage(len(self.pages))
            self.pages.append(page)
            return page

    context = OfflineContext()
    fetcher = BrowserFetcher(
        tmp_path / ".auth" / "deeplearning_ai.json",
        navigation_retries=1,
        retry_delay_seconds=0,
    )
    fetcher._context = context

    with pytest.raises(NavigationError, match="after 2 attempts"):
        fetcher.fetch("https://learn.deeplearning.ai/courses/course/lesson/id/name")

    assert len(context.pages) == 2
    assert all(page.closed for page in context.pages)


def test_browser_fetcher_auto_visibility_uses_auth_state_presence(tmp_path):
    auth_state = tmp_path / ".auth" / "deeplearning_ai.json"

    assert BrowserFetcher(auth_state, browser_visibility="auto")._initial_headless() is False

    auth_state.parent.mkdir()
    auth_state.write_text("{}", encoding="utf-8")

    assert BrowserFetcher(auth_state, browser_visibility="auto")._initial_headless() is True
    assert BrowserFetcher(auth_state, browser_visibility="hidden")._initial_headless() is True
    assert BrowserFetcher(auth_state, browser_visibility="visible")._initial_headless() is False


def test_browser_fetcher_auto_visibility_uses_profile_ready_marker(tmp_path):
    profile_dir = tmp_path / ".auth" / "chrome-profile"
    fetcher = BrowserFetcher(
        tmp_path / ".auth" / "state.json",
        browser_visibility="auto",
        browser_profile_dir=profile_dir,
    )

    assert fetcher._initial_headless() is False

    profile_dir.mkdir(parents=True)
    (profile_dir / ".dlaikit-ready").write_text("ready\n", encoding="utf-8")

    assert fetcher._initial_headless() is True


def test_persistent_chrome_profile_is_seeded_from_legacy_auth_state(tmp_path):
    class PersistentContext:
        def __init__(self):
            self.cookies = []

        def add_cookies(self, cookies):
            self.cookies.extend(cookies)

        def close(self):
            pass

    class Chromium:
        def __init__(self, context):
            self.context = context
            self.calls = []

        def launch_persistent_context(self, user_data_dir, channel, headless):
            self.calls.append((user_data_dir, channel, headless))
            return self.context

    class Playwright:
        def __init__(self, chromium):
            self.chromium = chromium

    auth_state = tmp_path / ".auth" / "state.json"
    auth_state.parent.mkdir()
    cookie = {"name": "session", "value": "secret", "domain": ".example.test", "path": "/"}
    auth_state.write_text(json.dumps({"cookies": [cookie], "origins": []}), encoding="utf-8")
    profile_dir = tmp_path / ".auth" / "chrome-profile"
    context = PersistentContext()
    chromium = Chromium(context)
    fetcher = BrowserFetcher(
        auth_state,
        browser_channel="chrome",
        browser_profile_dir=profile_dir,
    )
    fetcher._playwright = Playwright(chromium)

    fetcher._launch_browser(headless=False)

    assert chromium.calls == [(str(profile_dir), "chrome", False)]
    assert context.cookies == [cookie]


def test_lesson_login_is_detected_even_with_sidebar_lesson_links(tmp_path):
    fetcher = BrowserFetcher(tmp_path / "state.json")
    html = """
    <a href="/courses/course/lesson/next">Next lesson</a>
    <a>Sign in here!</a>
    """

    assert fetcher._looks_like_login_page(
        html,
        "https://learn.deeplearning.ai/courses/course/lesson/id/name",
    ) is True
    assert fetcher._looks_like_login_page(
        html,
        "https://www.deeplearning.ai/courses/course",
    ) is False


def test_authenticated_lesson_wins_over_start_learning_cta(tmp_path):
    fetcher = BrowserFetcher(tmp_path / "state.json")
    html = """
    <button>Start Learning</button>
    <button>Show Transcript</button>
    <p>Authenticated lesson content.</p>
    """

    assert fetcher._looks_like_login_page(
        html,
        "https://learn.deeplearning.ai/courses/course/lesson/id/name",
    ) is False


def test_visible_browser_waits_for_login_without_enter(tmp_path):
    context = DummyLoginContext()
    fetcher = BrowserFetcher(
        tmp_path / ".auth" / "deeplearning_ai.json",
        browser_visibility="visible",
        login_timeout_ms=100,
    )
    fetcher._context = context
    fetcher._headless = False

    html = fetcher.fetch("https://learn.deeplearning.ai/courses/course/lesson/id/name")

    assert "Loaded after login" in html
    assert context.pages[0].closed is True
    assert context.storage_paths == [
        str(tmp_path / ".auth" / "deeplearning_ai.json"),
        str(tmp_path / ".auth" / "deeplearning_ai.json"),
    ]


def test_hidden_browser_fails_clearly_when_login_required(tmp_path):
    context = DummyLoginContext()
    fetcher = BrowserFetcher(
        tmp_path / ".auth" / "deeplearning_ai.json",
        browser_visibility="hidden",
    )
    fetcher._context = context
    fetcher._headless = True

    with pytest.raises(LoginRequiredError, match="browser is hidden"):
        fetcher.fetch("https://learn.deeplearning.ai/courses/course/lesson/id/name")


def test_fetch_json_removes_request_headers_from_network_error(tmp_path):
    class FailingRequest:
        def get(self, url, timeout):
            raise RuntimeError(
                "APIRequestContext.get: getaddrinfo ENOTFOUND lab.example.test\n"
                "Call log:\n  - cookie: session=secret"
            )

    class RequestContext:
        request = FailingRequest()

    fetcher = BrowserFetcher(tmp_path / "state.json")
    fetcher._context = RequestContext()

    with pytest.raises(RuntimeError) as exc_info:
        fetcher.fetch_json("https://lab.example.test/api/contents?token=secret")

    assert "ENOTFOUND" in str(exc_info.value)
    assert "cookie" not in str(exc_info.value).lower()
    assert "session=secret" not in str(exc_info.value)
