import pytest

from study.fetchers import BrowserFetcher, LoginRequiredError


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

    def wait_for_function(self, script, timeout):
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

    def wait_for_function(self, script, timeout):
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


def test_browser_fetcher_auto_visibility_uses_auth_state_presence(tmp_path):
    auth_state = tmp_path / ".auth" / "deeplearning_ai.json"

    assert BrowserFetcher(auth_state, browser_visibility="auto")._initial_headless() is False

    auth_state.parent.mkdir()
    auth_state.write_text("{}", encoding="utf-8")

    assert BrowserFetcher(auth_state, browser_visibility="auto")._initial_headless() is True
    assert BrowserFetcher(auth_state, browser_visibility="hidden")._initial_headless() is True
    assert BrowserFetcher(auth_state, browser_visibility="visible")._initial_headless() is False


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
