"""One JSON over HTTP helper for every provider adapter.

Standard library only. Retries on 429 and 5xx with backoff, honours
Retry-After, and never logs an Authorization header.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import ProviderError

USER_AGENT = "sunbird-outbound/0.1 (+internal recruiting tool)"
DEFAULT_TIMEOUT = 45
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


class HttpError(ProviderError):
    def __init__(self, status: int, url: str, body: str):
        self.status = status
        self.url = url
        self.body = body[:800]
        super().__init__(f"HTTP {status} from {url}: {self.body}")


def _redact(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "api-key", "x-api-key", "api_key", "cal-secret"}:
            out[key] = "***"
        else:
            out[key] = value
    return out


def request_json(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 3,
    backoff: float = 2.0,
    sleep=time.sleep,
) -> Any:
    """Call a JSON API. Returns the decoded body, or raises HttpError."""
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(clean, doseq=True)

    payload: bytes | None = None
    send_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    send_headers.update(headers or {})
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        send_headers.setdefault("Content-Type", "application/json")

    # A test that reaches the network is a test that hangs, costs money, or
    # passes for the wrong reason. Setting OUTBOUND_OFFLINE turns an unmocked
    # call into an immediate, obvious failure.
    if os.environ.get("OUTBOUND_OFFLINE", "").strip() not in ("", "0", "false"):
        raise ProviderError(
            f"OUTBOUND_OFFLINE is set and something tried to call {url}. "
            f"In a test, mock outbound.httpjson.get or .post. In a real run, "
            f"unset OUTBOUND_OFFLINE."
        )

    attempt = 0
    while True:
        attempt += 1
        request = urllib.request.Request(
            url, data=payload, headers=send_headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                text = raw.decode("utf-8", "replace")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            if exc.code in RETRY_STATUS and attempt <= retries:
                # Retry-After is delay-seconds OR an HTTP-date (RFC 7231), and
                # CDNs send both. float() on a date raises, which would crash
                # the whole call on a 429, so parse tolerantly and fall back to
                # exponential backoff.
                retry_after = (exc.headers.get("Retry-After") or "").strip()
                try:
                    wait = float(retry_after)
                except ValueError:
                    try:
                        import email.utils as _eu

                        when = _eu.parsedate_to_datetime(retry_after)
                        import datetime as _dt

                        wait = max(0.0, (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds())
                    except (TypeError, ValueError):
                        wait = 0.0
                wait = wait or backoff ** attempt
                sleep(min(wait, 60))
                continue
            raise HttpError(exc.code, url, raw) from exc
        except urllib.error.URLError as exc:
            if attempt <= retries:
                sleep(backoff ** attempt)
                continue
            raise ProviderError(
                f"network error calling {url}: {exc.reason}. "
                f"headers={_redact(send_headers)}"
            ) from exc


def get(url: str, **kwargs: Any) -> Any:
    return request_json("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> Any:
    return request_json("POST", url, **kwargs)


def delete(url: str, **kwargs: Any) -> Any:
    return request_json("DELETE", url, **kwargs)
