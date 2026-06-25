import time
from pathlib import Path


class MissingDependencyError(RuntimeError):
    pass


class LoginRequiredError(RuntimeError):
    pass


class HttpRequestError(RuntimeError):
    def __init__(self, url, status, status_text=""):
        self.url = url
        self.status = status
        self.status_text = status_text
        message = "GET {} failed with HTTP {}".format(url, status)
        if status_text:
            message = "{} {}".format(message, status_text)
        super().__init__(message)


class _RestartHeadlessAfterLogin(RuntimeError):
    pass


class BrowserFetcher:
    def __init__(
        self,
        auth_state,
        timeout_ms=30000,
        navigation_retries=2,
        retry_delay_seconds=2,
        browser_visibility="auto",
        login_timeout_ms=300000,
    ):
        self.auth_state = Path(auth_state)
        self.timeout_ms = timeout_ms
        self.navigation_retries = navigation_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.browser_visibility = browser_visibility
        self.login_timeout_ms = login_timeout_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._headless = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise MissingDependencyError(
                "Install browser support with: python3 -m pip install -e '.[dev]'"
            ) from exc

        self._playwright = sync_playwright().start()
        self._launch_browser(headless=self._initial_headless())
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._close_browser()
        if self._playwright is not None:
            self._playwright.stop()

    def fetch(self, url):
        return self._fetch(url, wait_for_course_content=True)

    def fetch_page(self, url):
        return self._fetch(url, wait_for_course_content=False)

    def fetch_json(self, url, timeout_ms=None):
        if self._context is None:
            raise RuntimeError("BrowserFetcher must be used as a context manager.")

        response = self._context.request.get(url, timeout=timeout_ms or self.timeout_ms)
        if not response.ok:
            try:
                status_text = response.status_text
            except Exception:
                status_text = ""
            raise HttpRequestError(url, response.status, status_text)

        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError("GET {} did not return JSON.".format(url)) from exc

        self._save_auth_state()
        return payload

    def authenticate_jupyter(self, login_url, check_url):
        if self._context is None:
            raise RuntimeError("BrowserFetcher must be used as a context manager.")

        if self._headless and self.browser_visibility == "auto":
            self._restart_browser(headless=False)
        if self._headless:
            raise LoginRequiredError(
                "Jupyter login is required, but the browser is hidden. Set browser_visibility "
                "to visible in dlai-transcripts.json, or set code_token if automatic token "
                "discovery is unavailable."
            )

        page = self._context.new_page()
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._wait_for_network(page)
            print("Jupyter login appears to be required.")
            print("Complete login in the opened browser; this command will continue automatically.")
            payload = self._wait_for_jupyter_api(page, check_url)
            self._save_auth_state()
            return payload
        finally:
            page.close()

    def _fetch(self, url, wait_for_course_content):
        if self._context is None:
            raise RuntimeError("BrowserFetcher must be used as a context manager.")

        last_exc = None
        for attempt in range(self.navigation_retries + 1):
            try:
                return self._fetch_once(url, wait_for_course_content=wait_for_course_content)
            except _RestartHeadlessAfterLogin:
                self._restart_browser(headless=True)
                return self._fetch(url, wait_for_course_content=wait_for_course_content)
            except LoginRequiredError:
                if self.browser_visibility == "auto" and self._headless:
                    self._restart_browser(headless=False)
                    return self._fetch(url, wait_for_course_content=wait_for_course_content)
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= self.navigation_retries or not self._is_retryable_navigation_error(exc):
                    raise
                time.sleep(self.retry_delay_seconds)

        raise last_exc

    def _fetch_once(self, url, wait_for_course_content=True):
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            self._wait_for_network(page)
            if wait_for_course_content:
                self._wait_for_course_content(page)
            content = page.content()

            if self._looks_like_login_page(content):
                if self._headless:
                    raise LoginRequiredError(
                        "Login is required, but the browser is hidden. Set browser_visibility "
                        "to auto or visible in dlai-transcripts.json."
                    )
                print("Login appears to be required.")
                print("Complete login in the opened browser; this command will continue automatically.")
                content = self._wait_for_login_completion(page)
                self._wait_for_network(page)
                if wait_for_course_content:
                    self._wait_for_course_content(page)
                self._save_auth_state()
                if self.browser_visibility == "auto":
                    raise _RestartHeadlessAfterLogin()

            self._save_auth_state()
            return content
        finally:
            page.close()

    def _initial_headless(self):
        if self.browser_visibility == "visible":
            return False
        if self.browser_visibility == "hidden":
            return True
        return self.auth_state.exists()

    def _launch_browser(self, headless):
        self._headless = headless
        self._browser = self._playwright.chromium.launch(headless=headless)
        context_options = {}
        if self.auth_state.exists():
            context_options["storage_state"] = str(self.auth_state)
        self._context = self._browser.new_context(**context_options)

    def _restart_browser(self, headless):
        self._close_browser()
        self._launch_browser(headless=headless)

    def _close_browser(self):
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    def _save_auth_state(self):
        self.auth_state.parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=str(self.auth_state))

    def _wait_for_network(self, page):
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    def _wait_for_course_content(self, page):
        try:
            page.wait_for_function(
                """
                () => {
                    const text = document.body ? document.body.innerText : "";
                    return text.includes("Show Transcript")
                        || text.includes("Hide Transcript")
                        || document.querySelector('a[href*="/lesson/"]');
                }
                """,
                timeout=10000,
            )
        except Exception:
            pass

    def _wait_for_login_completion(self, page):
        try:
            page.wait_for_function(
                """
                () => {
                    const body = document.body;
                    if (!body) return false;
                    const text = body.innerText || "";
                    const hasCourseContent = text.includes("Show Transcript")
                        || text.includes("Hide Transcript")
                        || document.querySelector('a[href*="/lesson/"]');
                    const hasPasswordInput = document.querySelector('input[type="password"]');
                    const hasLoginText = text.includes("Sign In") || text.includes("Log In");
                    return hasCourseContent || (!hasPasswordInput && !hasLoginText);
                }
                """,
                timeout=self.login_timeout_ms,
            )
        except Exception as exc:
            raise LoginRequiredError(
                "Login did not complete before the timeout. Run again and finish login in the opened browser."
            ) from exc

        content = page.content()
        if self._looks_like_login_page(content):
            raise LoginRequiredError("Login still appears to be required after waiting.")
        return content

    def _wait_for_jupyter_api(self, page, check_url):
        deadline = time.time() + (self.login_timeout_ms / 1000)
        last_exc = None

        while time.time() < deadline:
            try:
                payload = self.fetch_json(check_url, timeout_ms=5000)
                return payload
            except Exception as exc:
                last_exc = exc
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    time.sleep(1)

        raise LoginRequiredError(
            "Jupyter login did not complete before the timeout. Open the code URL "
            "with its token, or set code_token in dlai-transcripts.json."
        ) from last_exc

    def _looks_like_login_page(self, html):
        has_transcript_marker = "Show Transcript" in html or "Hide Transcript" in html
        has_lesson_link = "/lesson/" in html
        has_login_marker = "Sign In" in html or "Start Learning" in html or "Log In" in html
        return has_login_marker and not has_transcript_marker and not has_lesson_link

    def _is_retryable_navigation_error(self, exc):
        message = str(exc)
        retryable_markers = (
            "ERR_CONNECTION_CLOSED",
            "ERR_CONNECTION_RESET",
            "ERR_NETWORK_CHANGED",
            "ERR_TIMED_OUT",
            "ERR_ABORTED",
            "Timeout",
            "Target closed",
        )
        return any(marker in message for marker in retryable_markers)
