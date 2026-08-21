from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from apps.api.app.config import Settings
from apps.api.app.social_browser import (
    connect_social_account,
    publish_social_video,
    verify_social_account,
)

LOGIN_PAGE = b"""<!doctype html><html><body>
<form id="login">
  <input data-testid="username">
  <input data-testid="password" type="password">
  <button data-testid="login-submit" type="submit">Log in</button>
</form>
<script>
document.querySelector('#login').addEventListener('submit', event => {
  event.preventDefault();
  const username = document.querySelector('[data-testid=username]').value;
  if (username === 'twofactor') {
    document.cookie = 'pending=1; path=/';
    location.href = '/challenge';
  } else {
    document.cookie = 'session=ready; path=/';
    location.href = '/';
  }
});
</script></body></html>"""

CHALLENGE_PAGE = b"""<!doctype html><html><body>
<form id="verify">
  <input data-testid="verification-code" autocomplete="one-time-code">
  <button data-testid="verification-submit" type="submit">Confirm</button>
</form>
<script>
document.querySelector('#verify').addEventListener('submit', event => {
  event.preventDefault();
  if (document.querySelector('[data-testid=verification-code]').value === '123456') {
    document.cookie = 'session=ready; path=/';
    location.href = '/';
  }
});
</script></body></html>"""

UPLOAD_PAGE = b"""<!doctype html><html><body>
<div data-testid="account-ready">Signed in</div>
<input data-testid="video-file" type="file" accept="video/mp4">
<textarea data-testid="caption"></textarea>
<button data-testid="publish-submit">Post</button>
<script>
document.querySelector('[data-testid=publish-submit]').addEventListener('click', () => {
  const done = document.createElement('div');
  done.dataset.testid = 'publish-success';
  done.textContent = 'Posted';
  document.body.appendChild(done);
});
</script></body></html>"""


class FakeSocialHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/accounts/login/", "/login/phone-or-email/email"}:
            payload = LOGIN_PAGE
        elif self.path == "/challenge":
            payload = CHALLENGE_PAGE
        elif "session=ready" in (self.headers.get("Cookie") or ""):
            payload = UPLOAD_PAGE
        else:
            payload = LOGIN_PAGE
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def fake_social_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSocialHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def browser_settings(base_url: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        social_browser_headless=True,
        social_browser_timeout_seconds=5,
        social_browser_instagram_base_url=base_url,
        social_browser_tiktok_base_url=base_url,
    )


@pytest.mark.parametrize("provider", ["instagram", "tiktok"])
def test_real_playwright_login_and_web_upload(provider: str, tmp_path: Path) -> None:
    with fake_social_server() as base_url:
        settings = browser_settings(base_url)
        login = connect_social_account(
            settings,
            provider=provider,
            username="creator",
            password="transient-password",
        )
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake-mp4-for-browser-upload")

        result = publish_social_video(
            settings,
            provider=provider,
            storage_state=login.storage_state,
            file_path=video,
            caption="A browser-uploaded test",
            privacy="SELF_ONLY" if provider == "tiktok" else "public",
        )

    assert login.status == "active"
    assert result["published_via"] == "playwright_web"
    assert result["external_post_id"].startswith("browser_")


def test_real_playwright_two_factor_session_resume() -> None:
    with fake_social_server() as base_url:
        settings = browser_settings(base_url)
        pending = connect_social_account(
            settings,
            provider="instagram",
            username="twofactor",
            password="transient-password",
        )
        verified = verify_social_account(
            settings,
            provider="instagram",
            username="twofactor",
            code="123456",
            storage_state=pending.storage_state,
            page_url=pending.page_url,
        )

    assert pending.status == "verification_required"
    assert pending.challenge_kind == "one_time_code"
    assert verified.status == "active"
