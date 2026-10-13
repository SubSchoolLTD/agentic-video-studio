from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime

import google.auth
from fastapi import FastAPI, Header, HTTPException
from google.auth.transport.requests import Request as GoogleAuthRequest

broker_secret = os.environ.get("BROKER_SECRET", "")
if len(broker_secret) < 32:
    raise RuntimeError("BROKER_SECRET must contain at least 32 characters")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/token")
def token(authorization: str = Header(default="")) -> dict[str, str | int]:
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, broker_secret):
        raise HTTPException(401, "Invalid broker credential")
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(GoogleAuthRequest())
    if not credentials.token or not credentials.expiry:
        raise HTTPException(503, "Google runtime credential is unavailable")
    expiry = credentials.expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    expires_in = max(60, int((expiry - datetime.now(UTC)).total_seconds()))
    return {"access_token": credentials.token, "expires_in": expires_in, "token_type": "Bearer"}
