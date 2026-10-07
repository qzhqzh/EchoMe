"""Browser regression checks for login; all Hub responses use synthetic fixtures.

Requires Python Playwright and its Chromium browser. Run against a running Web
Console with --base-url. No real credentials or backend writes are used.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import Browser, Page, Route, expect, sync_playwright

TOKEN = "synthetic-login-regression-token"
USER = {
    "id": "00000000-0000-0000-0000-000000000001",
    "github_id": 1,
    "username": "login-regression",
    "email": None,
    "avatar_url": None,
    "role": "user",
    "created_at": "2026-01-01T00:00:00Z",
    "last_login_at": None,
}


@contextmanager
def session(browser: Browser, base: str) -> Iterator[tuple[Page, dict[str, Any]]]:
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    context.add_init_script("localStorage.setItem('echome_locale', 'zh')")
    state: dict[str, Any] = {"failure": None, "expired": False, "requests": []}
    page_errors: list[str] = []

    def respond(route: Route) -> None:
        path = urlsplit(route.request.url).path
        state["requests"].append(path)
        payload: Any = {"items": [], "total": 0, "offset": 0, "next_offset": None}
        status = 200
        if path == "/api/v1/auth/me":
            failure = state["failure"]
            if failure == "network":
                route.abort("failed")
                return
            if failure == "malformed":
                payload = {"status": "ok"}
            elif failure or route.request.headers.get("authorization") != f"Bearer {TOKEN}":
                status, payload = failure or 401, {"detail": "Invalid or expired token"}
            else:
                payload = USER
        elif path == "/api/v1/auth/github":
            payload = {"url": f"{base}/login?code=synthetic-callback"}
        elif path in ("/api/v1/auth/github/callback", "/api/v1/auth/refresh"):
            payload = {"access_token": TOKEN, "token_type": "bearer", "user": USER}
        elif path == "/health":
            payload = {"status": "ok"}
        elif state["expired"]:
            status, payload = 401, {"detail": "Invalid or expired token"}
        route.fulfill(status=status, json=payload)

    context.route("**/api/v1/**", respond)
    context.route("**/health", respond)
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        yield page, state
        assert not page_errors, page_errors
    finally:
        context.close()


def submit(page: Page, token: str = TOKEN) -> None:
    if not page.locator("#login-token").count():
        page.get_by_role("button", name="或使用 API Token", exact=True).click()
    page.get_by_label("API Token", exact=True).fill(token)
    page.get_by_role("button", name="使用 Token 连接", exact=True).click()


def verify_failure(page: Page) -> None:
    expect(page.get_by_role("alert")).to_be_visible()
    assert urlsplit(page.url).path == "/login"
    assert not page.evaluate("localStorage.getItem('echome_token')")
    expect(page.get_by_text("Connected to EchoMe Hub", exact=True)).to_have_count(0)
    expect(page.get_by_text("登录成功！", exact=True)).to_have_count(0)


def run(base: str) -> list[str]:
    passed: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            target = "/knowledge/review?issue=synthetic-issue#review"
            with session(browser, base) as (page, state):
                page.goto(base + target)
                page.wait_for_url("**/login?**")
                assert parse_qs(urlsplit(page.url).query)["redirect"] == [target]
                submit(page, "invalid-synthetic-token")
                verify_failure(page)
                expect(page.get_by_role("alert")).to_contain_text("Token 无效或已过期")
                assert "/health" not in state["requests"]
                submit(page)
                page.wait_for_url(base + target)
                expect(page.locator("main")).to_be_visible()
                assert (
                    page.evaluate("JSON.parse(localStorage.getItem('echome_user')).username")
                    == USER["username"]
                )
                passed.append(
                    "invalid token stays on form; valid retry restores knowledge path/query/hash"
                )

            for failure in (403, 503, "network", "malformed"):
                with session(browser, base) as (page, state):
                    state["failure"] = failure
                    page.goto(base + "/login")
                    submit(page)
                    verify_failure(page)
                    expected = "Token 无效或已过期" if failure == 403 else "暂时无法验证登录"
                    expect(page.get_by_role("alert")).to_contain_text(expected)
                    assert "/health" not in state["requests"]
                    passed.append(f"login failure {failure} never establishes a session")

            with session(browser, base) as (page, _):
                page.goto(base + "/cards/memories")
                submit(page)
                page.wait_for_url(base + "/cards/memories")
                expect(page.get_by_role("heading", name="逐张核对记忆")).to_be_visible()
                passed.append("successful token login returns to memory cards")

            for redirect in (
                None,
                "https://example.invalid/",
                "//example.invalid/",
                "/\\example.invalid/",
                "/login",
                "/unknown-route",
            ):
                with session(browser, base) as (page, _):
                    query = "?" + urlencode({"redirect": redirect}) if redirect else ""
                    page.goto(base + "/login" + query)
                    submit(page)
                    page.wait_for_url(base + "/")
                    expect(page.locator("main")).to_be_visible()
                    passed.append(f"safe default for redirect {redirect!r}")

            with session(browser, base) as (page, state):
                page.goto(base + "/help")
                submit(page)
                page.wait_for_url(base + "/help")
                state["expired"] = True
                page.goto(base + "/cards/memories")
                page.wait_for_url("**/login?**")
                assert parse_qs(urlsplit(page.url).query)["redirect"] == ["/cards/memories"]
                assert not page.evaluate("localStorage.getItem('echome_token')")
                assert state["requests"].count("/api/v1/auth/refresh") == 1
                state["expired"] = False
                submit(page)
                page.wait_for_url(base + "/cards/memories")
                passed.append("401 after refresh returns to login and preserves destination")

            with session(browser, base) as (page, _):
                page.goto(base + target)
                page.get_by_role("button", name="使用 GitHub 登录", exact=True).click()
                page.wait_for_url(base + target)
                assert not page.evaluate("sessionStorage.getItem('echome_login_redirect')")
                passed.append("OAuth callback restores destination across navigation")

            with session(browser, base) as (page, _):
                page.goto(base + "/login?source=cli")
                page.get_by_role("button", name="使用 GitHub 登录", exact=True).click()
                expect(page.get_by_role("heading", name="登录成功！")).to_be_visible()
                expect(page.get_by_role("button", name="复制 Token")).to_be_visible()
                assert urlsplit(page.url).path == "/login"
                passed.append("CLI OAuth callback still displays its token")
        finally:
            browser.close()
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    print(json.dumps({"passed": run(args.base_url.rstrip("/"))}, ensure_ascii=False, indent=2))
