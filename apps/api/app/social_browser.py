from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import Settings

SocialProvider = Literal["instagram", "tiktok"]


class SocialBrowserError(RuntimeError):
    """A log-safe browser automation failure.

    The exception deliberately never includes page HTML, credentials, cookies, or a
    provider response body because those can contain account data.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool = False,
        remote_state_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.remote_state_unknown = remote_state_unknown


@dataclass(frozen=True)
class BrowserLoginResult:
    status: Literal["active", "verification_required"]
    display_name: str
    external_account_id: str
    storage_state: dict[str, Any]
    page_url: str
    challenge_kind: str | None = None


def _provider_base_url(settings: Settings, provider: SocialProvider) -> str:
    value = (
        settings.social_browser_instagram_base_url
        if provider == "instagram"
        else settings.social_browser_tiktok_base_url
    )
    return value.rstrip("/")


def _login_url(settings: Settings, provider: SocialProvider) -> str:
    base = _provider_base_url(settings, provider)
    if provider == "instagram":
        return f"{base}/accounts/login/"
    return f"{base}/login/phone-or-email/email"


def _upload_url(settings: Settings, provider: SocialProvider) -> str:
    base = _provider_base_url(settings, provider)
    if provider == "instagram":
        return base
    return f"{base}/tiktokstudio/upload?from=webapp"


def _browser_context(
    settings: Settings,
    browser: Browser,
    *,
    storage_state: dict[str, Any] | None = None,
) -> BrowserContext:
    return browser.new_context(
        storage_state=storage_state or None,
        viewport={"width": 1440, "height": 1000},
        locale="en-US",
        timezone_id="UTC",
        reduced_motion="reduce",
    )


def _launch(settings: Settings, playwright: Any) -> Browser:
    return playwright.chromium.launch(
        headless=settings.social_browser_headless,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
    )


def _storage_state(context: BrowserContext) -> dict[str, Any]:
    try:
        return context.storage_state(indexed_db=True)
    except TypeError:  # pragma: no cover - compatibility with older local Playwright
        return context.storage_state()


def _visible(page: Page, selectors: list[str], *, timeout_ms: int = 0) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=timeout_ms):
                return True
        except Exception:  # noqa: S110 - provider UIs require selector fallbacks
            pass
    return False


def _fill(page: Page, selectors: list[str], value: str, *, field: str) -> None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1_500):
                locator.fill(value)
                return
        except Exception:  # noqa: S110 - provider UIs require selector fallbacks
            pass
    raise SocialBrowserError(
        f"{field} field is unavailable on the provider sign-in page",
        code="provider_ui_changed",
        retryable=True,
    )


def _click(page: Page, selectors: list[str], *, action: str, required: bool = True) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1_500):
                locator.click()
                return True
        except Exception:  # noqa: S110 - provider UIs require selector fallbacks
            pass
    if required:
        raise SocialBrowserError(
            f"{action} control is unavailable on the provider page",
            code="provider_ui_changed",
            retryable=True,
        )
    return False


def _wait_after_navigation(page: Page, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_200)


def _wait_for_any(page: Page, selectors: list[str], *, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1_000
    while time.monotonic() < deadline:
        if _visible(page, selectors, timeout_ms=100):
            return True
        page.wait_for_timeout(250)
    return False


def _dismiss_optional_prompts(page: Page) -> None:
    for label in ("Not now", "Not Now", "Decline optional cookies", "Only allow essential cookies"):
        try:
            button = page.get_by_role("button", name=label, exact=True)
            if button.is_visible(timeout=250):
                button.click()
        except Exception:  # noqa: S110 - optional provider prompts are best-effort
            pass


def _verification_visible(page: Page) -> bool:
    return _visible(
        page,
        [
            '[data-testid="verification-code"]',
            'input[autocomplete="one-time-code"]',
            'input[name="verificationCode"]',
            'input[name="code"]',
            'input[aria-label*="security code" i]',
            'input[placeholder*="verification code" i]',
        ],
        timeout_ms=500,
    )


def _captcha_visible(page: Page) -> bool:
    return _visible(
        page,
        [
            'iframe[src*="captcha"]',
            '[data-testid*="captcha"]',
            'text=/captcha|verify you are human|unusual activity/i',
        ],
        timeout_ms=250,
    )


def _login_error_visible(page: Page) -> bool:
    return _visible(
        page,
        [
            '[data-testid="login-error"]',
            'text=/incorrect password|invalid password|couldn.t log in|credentials don.t match/i',
            'text=/maximum number of attempts|too many attempts/i',
        ],
        timeout_ms=250,
    )


def _logged_in(page: Page, provider: SocialProvider) -> bool:
    if _visible(page, ['[data-testid="account-ready"]'], timeout_ms=250):
        return True
    if provider == "instagram":
        if "/accounts/login" in page.url or "/challenge" in page.url:
            return False
        return _visible(
            page,
            [
                'svg[aria-label="New post"]',
                'svg[aria-label="Home"]',
                'a[href^="/direct/inbox"]',
                'text=/create/i',
            ],
            timeout_ms=500,
        )
    if "/login" in page.url:
        return False
    return _visible(
        page,
        [
            '[data-e2e="profile-icon"]',
            '[data-e2e="top-login-button"]',
            'a[href*="/tiktokstudio/upload"]',
            'text=/upload/i',
        ],
        timeout_ms=500,
    ) and not _visible(page, ['button:has-text("Log in")'], timeout_ms=100)


def _login_result(
    context: BrowserContext,
    page: Page,
    *,
    provider: SocialProvider,
    username: str,
) -> BrowserLoginResult:
    safe_username = username.strip().lstrip("@")
    account_hash = hashlib.sha256(f"{provider}:{safe_username.lower()}".encode()).hexdigest()[:20]
    return BrowserLoginResult(
        status="active",
        display_name=f"@{safe_username}",
        external_account_id=f"browser_{account_hash}",
        storage_state=_storage_state(context),
        page_url=page.url,
    )


def connect_social_account(
    settings: Settings,
    *,
    provider: SocialProvider,
    username: str,
    password: str,
) -> BrowserLoginResult:
    """Authenticate with a transient password and return only reusable session state."""

    timeout_ms = settings.social_browser_timeout_seconds * 1_000
    with sync_playwright() as playwright:
        browser = _launch(settings, playwright)
        try:
            context = _browser_context(settings, browser)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(_login_url(settings, provider), wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_prompts(page)
            _fill(
                page,
                [
                    '[data-testid="username"]',
                    'input[name="username"]',
                    'input[name="email"]',
                    'input[autocomplete="username"]',
                    'input[placeholder*="email" i]',
                ],
                username,
                field="Username",
            )
            _fill(
                page,
                [
                    '[data-testid="password"]',
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[autocomplete="current-password"]',
                ],
                password,
                field="Password",
            )
            _click(
                page,
                [
                    '[data-testid="login-submit"]',
                    'button[type="submit"]',
                    'button:has-text("Log in")',
                    'button:has-text("Log In")',
                ],
                action="Sign in",
            )
            _wait_after_navigation(page, timeout_ms)
            _dismiss_optional_prompts(page)
            if _verification_visible(page):
                safe_username = username.strip().lstrip("@")
                account_hash = hashlib.sha256(f"{provider}:{safe_username.lower()}".encode()).hexdigest()[:20]
                return BrowserLoginResult(
                    status="verification_required",
                    display_name=f"@{safe_username}",
                    external_account_id=f"browser_{account_hash}",
                    storage_state=_storage_state(context),
                    page_url=page.url,
                    challenge_kind="one_time_code",
                )
            if _captcha_visible(page):
                raise SocialBrowserError(
                    "The provider requested a human verification. Retry the connection after completing the provider check.",
                    code="human_verification_required",
                )
            if _login_error_visible(page):
                raise SocialBrowserError(
                    "The provider rejected the supplied sign-in details",
                    code="invalid_credentials",
                )
            if not _logged_in(page, provider):
                raise SocialBrowserError(
                    "The provider did not confirm the sign-in",
                    code="login_not_confirmed",
                    retryable=True,
                )
            return _login_result(context, page, provider=provider, username=username)
        except PlaywrightTimeoutError as exc:
            raise SocialBrowserError(
                "The provider sign-in page timed out",
                code="provider_timeout",
                retryable=True,
            ) from exc
        finally:
            browser.close()


def verify_social_account(
    settings: Settings,
    *,
    provider: SocialProvider,
    username: str,
    code: str,
    storage_state: dict[str, Any],
    page_url: str,
) -> BrowserLoginResult:
    timeout_ms = settings.social_browser_timeout_seconds * 1_000
    with sync_playwright() as playwright:
        browser = _launch(settings, playwright)
        try:
            context = _browser_context(settings, browser, storage_state=storage_state)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(page_url or _login_url(settings, provider), wait_until="domcontentloaded", timeout=timeout_ms)
            _fill(
                page,
                [
                    '[data-testid="verification-code"]',
                    'input[autocomplete="one-time-code"]',
                    'input[name="verificationCode"]',
                    'input[name="code"]',
                    'input[aria-label*="security code" i]',
                    'input[placeholder*="verification code" i]',
                ],
                code,
                field="Verification code",
            )
            _click(
                page,
                [
                    '[data-testid="verification-submit"]',
                    'button[type="submit"]',
                    'button:has-text("Confirm")',
                    'button:has-text("Next")',
                ],
                action="Verify",
            )
            _wait_after_navigation(page, timeout_ms)
            if _verification_visible(page) or _login_error_visible(page):
                raise SocialBrowserError(
                    "The provider rejected the verification code",
                    code="invalid_verification_code",
                )
            if _captcha_visible(page):
                raise SocialBrowserError(
                    "The provider requested a human verification",
                    code="human_verification_required",
                )
            if not _logged_in(page, provider):
                raise SocialBrowserError(
                    "The provider did not confirm the account after verification",
                    code="verification_not_confirmed",
                    retryable=True,
                )
            return _login_result(context, page, provider=provider, username=username)
        except PlaywrightTimeoutError as exc:
            raise SocialBrowserError(
                "The verification page timed out",
                code="provider_timeout",
                retryable=True,
            ) from exc
        finally:
            browser.close()


def _set_files(page: Page, selectors: list[str], file_path: Path) -> None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.set_input_files(str(file_path), timeout=4_000)
            return
        except Exception:  # noqa: S110 - provider UIs require selector fallbacks
            pass
    raise SocialBrowserError(
        "The provider upload control is unavailable",
        code="provider_ui_changed",
        retryable=True,
    )


def _fill_caption(page: Page, caption: str) -> None:
    selectors = [
        '[data-testid="caption"]',
        'textarea[aria-label*="caption" i]',
        'textarea[placeholder*="caption" i]',
        '[contenteditable="true"][aria-label*="caption" i]',
        '[contenteditable="true"][data-e2e*="caption"]',
        '[contenteditable="true"]',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if not locator.is_visible(timeout=1_000):
                continue
            if locator.get_attribute("contenteditable") == "true":
                locator.click()
                locator.press("ControlOrMeta+A")
                locator.fill(caption)
            else:
                locator.fill(caption)
            return
        except Exception:  # noqa: S110 - provider UIs require selector fallbacks
            pass
    raise SocialBrowserError(
        "The provider caption field is unavailable",
        code="provider_ui_changed",
        retryable=True,
    )


def _publish_instagram(page: Page, file_path: Path, caption: str, timeout_ms: int) -> None:
    if not _visible(page, ['input[type="file"]'], timeout_ms=400):
        _click(
            page,
            [
                '[data-testid="create-post"]',
                'a:has-text("Create")',
                'div[role="button"]:has-text("Create")',
                'svg[aria-label="New post"]',
            ],
            action="Create post",
        )
    _set_files(page, ['[data-testid="video-file"]', 'input[type="file"]'], file_path)
    page.wait_for_timeout(1_000)
    for _ in range(2):
        if _visible(page, ['[data-testid="caption"]', 'textarea[aria-label*="caption" i]'], timeout_ms=300):
            break
        if not _click(
            page,
            ['[data-testid="next"]', 'button:has-text("Next")', 'div[role="button"]:has-text("Next")'],
            action="Next",
            required=False,
        ):
            break
        page.wait_for_timeout(800)
    _fill_caption(page, caption)
    _click(
        page,
        [
            '[data-testid="publish-submit"]',
            'button:has-text("Share")',
            'div[role="button"]:has-text("Share")',
        ],
        action="Share",
    )
    page.wait_for_timeout(1_200)
    if not _wait_for_any(
        page,
        ['[data-testid="publish-success"]', 'text=/your reel has been shared|your post has been shared/i'],
        timeout_ms=timeout_ms,
    ):
        raise SocialBrowserError(
            "Instagram did not confirm whether the post was shared",
            code="remote_outcome_unknown",
            remote_state_unknown=True,
        )


def _set_tiktok_privacy(page: Page, privacy: str) -> None:
    if not privacy:
        return
    if not _click(
        page,
        ['[data-testid="privacy-select"]', '[data-e2e*="privacy"]', 'button:has-text("Who can watch")'],
        action="Privacy",
        required=False,
    ):
        return
    label = privacy.replace("_", " ").title()
    _click(
        page,
        [f'[data-value="{privacy}"]', f'text="{label}"', f'text="{privacy}"'],
        action="Privacy option",
        required=False,
    )


def _set_checkbox(page: Page, selectors: list[str], checked: bool) -> None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if not locator.is_visible(timeout=400):
                continue
            if checked:
                locator.check()
            else:
                locator.uncheck()
            return
        except Exception:  # noqa: S110 - controls vary by provider account and region
            pass


def _publish_tiktok(
    page: Page,
    file_path: Path,
    caption: str,
    privacy: str,
    allow_comments: bool,
    allow_duet: bool,
    allow_stitch: bool,
    synthetic_media_disclosure: bool,
    timeout_ms: int,
) -> None:
    _set_files(page, ['[data-testid="video-file"]', 'input[type="file"]'], file_path)
    page.wait_for_timeout(1_000)
    _fill_caption(page, caption)
    _set_tiktok_privacy(page, privacy)
    _set_checkbox(
        page,
        ['[data-testid="allow-comments"]', 'label:has-text("Allow comments") input[type="checkbox"]'],
        allow_comments,
    )
    _set_checkbox(
        page,
        ['[data-testid="allow-duet"]', 'label:has-text("Duet") input[type="checkbox"]'],
        allow_duet,
    )
    _set_checkbox(
        page,
        ['[data-testid="allow-stitch"]', 'label:has-text("Stitch") input[type="checkbox"]'],
        allow_stitch,
    )
    _set_checkbox(
        page,
        [
            '[data-testid="synthetic-media-disclosure"]',
            'label:has-text("AI-generated content") input[type="checkbox"]',
        ],
        synthetic_media_disclosure,
    )
    _click(
        page,
        ['[data-testid="publish-submit"]', '[data-e2e="post_video_button"]', 'button:has-text("Post")'],
        action="Post",
    )
    page.wait_for_timeout(1_200)
    if not _wait_for_any(
        page,
        ['[data-testid="publish-success"]', 'text=/uploaded|posted|being processed|manage your posts/i'],
        timeout_ms=timeout_ms,
    ):
        raise SocialBrowserError(
            "TikTok did not confirm whether the video was posted",
            code="remote_outcome_unknown",
            remote_state_unknown=True,
        )


def publish_social_video(
    settings: Settings,
    *,
    provider: SocialProvider,
    storage_state: dict[str, Any],
    file_path: Path,
    caption: str,
    privacy: str,
    allow_comments: bool = True,
    allow_duet: bool = False,
    allow_stitch: bool = False,
    synthetic_media_disclosure: bool = True,
) -> dict[str, Any]:
    """Upload a video through the same web composer a signed-in user would use."""

    if not file_path.is_file():
        raise SocialBrowserError("Publication media is unavailable", code="media_unavailable")
    timeout_ms = settings.social_browser_timeout_seconds * 1_000
    with sync_playwright() as playwright:
        browser = _launch(settings, playwright)
        try:
            context = _browser_context(settings, browser, storage_state=storage_state)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(_upload_url(settings, provider), wait_until="domcontentloaded", timeout=timeout_ms)
            _dismiss_optional_prompts(page)
            if "/login" in page.url or _visible(page, ['button:has-text("Log in")'], timeout_ms=500):
                raise SocialBrowserError(
                    "The saved provider session has expired",
                    code="session_expired",
                )
            if _captcha_visible(page):
                raise SocialBrowserError(
                    "The provider requested a human verification",
                    code="human_verification_required",
                )
            if provider == "instagram":
                _publish_instagram(page, file_path, caption, timeout_ms)
            else:
                _publish_tiktok(
                    page,
                    file_path,
                    caption,
                    privacy,
                    allow_comments,
                    allow_duet,
                    allow_stitch,
                    synthetic_media_disclosure,
                    timeout_ms,
                )
            return {
                "external_post_id": f"browser_{secrets.token_hex(10)}",
                "external_url": page.url,
                "published_via": "playwright_web",
            }
        except PlaywrightTimeoutError as exc:
            raise SocialBrowserError(
                "The provider upload page timed out",
                code="provider_timeout",
                retryable=True,
            ) from exc
        finally:
            browser.close()
