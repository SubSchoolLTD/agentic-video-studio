from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import httpx

from .config import Settings


class PayPalError(RuntimeError):
    def __init__(self, code: str, *, status_code: int = 502):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _cents(value: object) -> int:
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayPalError("paypal_amount_invalid") from exc


def _payload(response: httpx.Response, fallback: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise PayPalError(fallback) from exc
    if response.status_code >= 300:
        raise PayPalError(fallback)
    if not isinstance(body, dict):
        raise PayPalError(fallback)
    return body


@dataclass(frozen=True)
class PayPalOrderState:
    order_id: str
    status: str
    currency: str
    amount_cents: int
    capture_id: str | None
    raw: dict[str, Any]


class PayPalClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = (
            "https://api-m.paypal.com"
            if settings.paypal_env.lower() == "live"
            else "https://api-m.sandbox.paypal.com"
        )

    def _token(self) -> str:
        if not self.settings.paypal_client_id or not self.settings.paypal_secret:
            raise PayPalError("paypal_credentials_missing", status_code=503)
        response = httpx.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=(self.settings.paypal_client_id, self.settings.paypal_secret),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        token = str(_payload(response, "paypal_auth_failed").get("access_token") or "")
        if not token:
            raise PayPalError("paypal_auth_failed")
        return token

    def _headers(self, *, request_id: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Content-Type": "application/json",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id[:38]
        return headers

    @staticmethod
    def state(payload: dict[str, Any]) -> PayPalOrderState:
        purchase = (payload.get("purchase_units") or [{}])[0]
        payments = purchase.get("payments") or {}
        capture = (payments.get("captures") or [{}])[0]
        amount = capture.get("amount") or purchase.get("amount") or {}
        return PayPalOrderState(
            order_id=str(payload.get("id") or ""),
            status=str(capture.get("status") or payload.get("status") or "").upper(),
            currency=str(amount.get("currency_code") or "").upper(),
            amount_cents=_cents(amount.get("value") or 0),
            capture_id=str(capture.get("id")) if capture.get("id") else None,
            raw=payload,
        )

    def create_order(
        self,
        *,
        merchant_reference: str,
        amount_cents: int,
        return_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": merchant_reference,
                    "invoice_id": merchant_reference,
                    "custom_id": merchant_reference,
                    "description": "Framewise AI balance top-up",
                    "amount": {"currency_code": "USD", "value": f"{amount_cents / 100:.2f}"},
                }
            ],
            "application_context": {
                "brand_name": "Framewise",
                "landing_page": "BILLING",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        response = httpx.post(
            f"{self.base_url}/v2/checkout/orders",
            headers=self._headers(request_id=merchant_reference),
            json=body,
            timeout=20,
        )
        payload = _payload(response, "paypal_create_order_failed")
        order_id = str(payload.get("id") or "")
        approval_url = next(
            (str(item.get("href")) for item in payload.get("links", []) if item.get("rel") == "approve"),
            "",
        )
        if not order_id or not approval_url:
            raise PayPalError("paypal_order_response_invalid")
        return order_id, approval_url

    def get_order(self, order_id: str) -> PayPalOrderState:
        response = httpx.get(
            f"{self.base_url}/v2/checkout/orders/{order_id}",
            headers=self._headers(),
            timeout=15,
        )
        return self.state(_payload(response, "paypal_order_lookup_failed"))

    def capture_order(self, order_id: str) -> PayPalOrderState:
        response = httpx.post(
            f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
            headers=self._headers(request_id=f"capture-{order_id}"),
            json={},
            timeout=20,
        )
        if response.status_code == 422:
            return self.get_order(order_id)
        return self.state(_payload(response, "paypal_capture_failed"))

    def verify_webhook(self, payload: dict[str, Any], headers: dict[str, str]) -> bool:
        if not self.settings.paypal_webhook_id:
            raise PayPalError("paypal_webhook_not_configured", status_code=503)
        required = {
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
        }
        if any(not value for value in required.values()):
            raise PayPalError("paypal_webhook_headers_missing", status_code=400)
        response = httpx.post(
            f"{self.base_url}/v1/notifications/verify-webhook-signature",
            headers=self._headers(),
            json={**required, "webhook_id": self.settings.paypal_webhook_id, "webhook_event": payload},
            timeout=15,
        )
        result = _payload(response, "paypal_webhook_verification_failed")
        return str(result.get("verification_status") or "").upper() == "SUCCESS"
