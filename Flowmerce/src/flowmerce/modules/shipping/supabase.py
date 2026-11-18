"""A small, safe client for Supabase's REST API (PostgREST), using httpx (already a project dependency).

* Server-side only: the service-role key never leaves this process and is never logged or returned.
* Every request targets one Postgres schema (default `ops`) through the Accept-Profile/Content-Profile headers.
* Errors become `SupabaseError` with a plain `state` the UI can show (not_configured, schema_missing,
  permission_denied, connection_failed, bad_request, error). Error text never contains the URL or the key.
* Reads retry twice on network errors / 5xx / 429; writes and RPC calls are never retried automatically.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import ShippingConfig


class SupabaseError(Exception):
    def __init__(self, state: str, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.state = state
        self.message = message
        self.status = status
        self.code = code


@dataclass
class Page:
    rows: list[dict[str, Any]]
    total: int | None


def _classify(status: int, body: Any) -> SupabaseError:
    code = ""
    msg = ""
    if isinstance(body, dict):
        code = str(body.get("code") or "")
        msg = str(body.get("message") or "")[:300]
    if code == "PGRST106" or code == "42P01" or code == "PGRST202" or code == "PGRST205":
        return SupabaseError("schema_missing", "The Flowmerce tables are not set up in Supabase yet, or the "
                             "`ops` schema is not exposed in the Supabase API settings.", status, code)
    if status in (401, 403) or code == "42501":
        return SupabaseError("permission_denied", "Supabase refused access. Check that the service-role key is correct.",
                             status, code)
    if status == 400 or code.startswith("22") or code.startswith("PGRST1"):
        return SupabaseError("bad_request", f"Supabase rejected the request: {msg or code or status}", status, code)
    if status == 409 or code == "23505":
        return SupabaseError("conflict", "Another run is already in progress, or the row already exists.", status, code)
    if code == "P0002":
        return SupabaseError("not_found", msg or "Not found.", status, code)
    return SupabaseError("error", f"Supabase error {status}{(': ' + msg) if msg else ''}", status, code)


class SupabaseClient:
    def __init__(self, cfg: ShippingConfig, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if not self.cfg.configured:
            raise SupabaseError("not_configured", "Supabase is not configured. Set SUPABASE_URL and "
                                "SUPABASE_SERVICE_ROLE_KEY in .env or .env.shipping.")
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.cfg.url + "/rest/v1",
                headers={"apikey": self.cfg.key, "Authorization": f"Bearer {self.cfg.key}"},
                timeout=self.cfg.timeout,
                transport=self._transport,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------ low level
    def _send(self, method: str, path: str, *, params: Any = None, json: Any = None,
              headers: dict[str, str] | None = None, retry: bool = False) -> httpx.Response:
        h = {"Accept-Profile": self.cfg.schema, "Content-Profile": self.cfg.schema, "Accept": "application/json"}
        if headers:
            h.update(headers)
        attempts = 3 if retry else 1
        last: Exception | None = None
        for i in range(attempts):
            try:
                r = self._http().request(method, path, params=params, json=json, headers=h)
            except httpx.HTTPError as e:
                last = e
                if i + 1 < attempts:
                    time.sleep(0.5 * (i + 1))
                    continue
                raise SupabaseError("connection_failed", f"Could not reach Supabase ({type(e).__name__}).") from None
            if r.status_code in (429, 500, 502, 503, 504) and i + 1 < attempts:
                time.sleep(0.5 * (i + 1))
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                except ValueError:
                    body = None
                raise _classify(r.status_code, body)
            return r
        raise SupabaseError("connection_failed", f"Could not reach Supabase ({type(last).__name__}).")

    # ------------------------------------------------------------------ helpers
    def select(self, table: str, params: dict[str, str] | list[tuple[str, str]] | None = None, *,
               count: bool = False, offset: int = 0, limit: int = 1000) -> Page:
        headers = {"Range-Unit": "items", "Range": f"{offset}-{offset + max(limit, 1) - 1}"}
        if count:
            headers["Prefer"] = "count=exact"
        r = self._send("GET", f"/{table}", params=params or {}, headers=headers, retry=True)
        total = None
        if count:
            cr = r.headers.get("content-range", "")
            tail = cr.split("/")[-1] if "/" in cr else ""
            total = int(tail) if tail.isdigit() else None
        return Page(rows=r.json(), total=total)

    def rpc(self, fn: str, args: dict[str, Any]) -> Any:
        r = self._send("POST", f"/rpc/{fn}", json=args)
        return r.json() if r.content else None

    def insert(self, table: str, row: dict[str, Any]) -> None:
        self._send("POST", f"/{table}", json=row, headers={"Prefer": "return=minimal"})

    def insert_returning(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        r = self._send("POST", f"/{table}", json=row, headers={"Prefer": "return=representation"})
        return r.json()[0]

    def upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        """Insert or update on the given unique column(s). Every row must carry the same keys."""
        if rows:
            self._send("POST", f"/{table}", params={"on_conflict": on_conflict}, json=rows,
                       headers={"Prefer": "resolution=merge-duplicates,return=minimal"})

    def update(self, table: str, filters: list[tuple[str, str]], values: dict[str, Any]) -> None:
        if not filters:
            raise SupabaseError("bad_request", "Refusing an update without a filter.")
        self._send("PATCH", f"/{table}", params=filters, json=values, headers={"Prefer": "return=minimal"})


_shared: SupabaseClient | None = None


def client() -> SupabaseClient:
    """One shared client per process (connection pooling inside httpx)."""
    global _shared
    from .config import shipping_config
    if _shared is None:
        _shared = SupabaseClient(shipping_config())
    return _shared


_public: SupabaseClient | None = None


def public_client() -> SupabaseClient:
    """Reads the hub's own tables (schema `public`). Flowmerce only ever SELECTs there: never a write."""
    global _public
    import dataclasses
    from .config import shipping_config
    if _public is None:
        _public = SupabaseClient(dataclasses.replace(shipping_config(), schema="public"))
    return _public


def set_client(c: SupabaseClient | None) -> None:
    """Tests swap in a client with a fake transport."""
    global _shared
    if _shared is not None and _shared is not c:
        _shared.close()
    _shared = c
