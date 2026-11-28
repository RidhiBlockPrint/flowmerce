"""A read-only client for the Meta Marketing API (Graph API), using httpx (already a project
dependency).

* Only GET requests: nothing here can change a budget, a status or anything else in an ad account.
* The access token is sent in the Authorization header, never in a URL, and never appears in a log
  line, an error message or a return value (`_scrub` removes it from Meta's own error text too).
* Errors become `MetaError` with a plain `state` the page can explain: token_expired, rate_limited,
  permission, bad_request, connection_failed, error.
* Meta's request limits: every answer carries the account's usage; at 90% or more the client stops
  with rate_limited instead of being blocked, and the next round carries on.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from .config import META_API_VERSION, META_BASE_URL, MetaAccount

log = logging.getLogger(__name__)

# Insights fields read per ad per day. Purchases are Meta's `purchase` action and add-to-cart /
# checkout started its combined website + app counts (`omni_*`): these are the ones that reproduce
# the Daily sheet (checked 2026-11-24).
INSIGHT_FIELDS = (
    "ad_id,date_start,spend,impressions,inline_link_clicks,outbound_clicks,actions,action_values,"
    "video_play_actions,video_p25_watched_actions,video_p50_watched_actions,video_p75_watched_actions,"
    "video_p95_watched_actions,video_avg_time_watched_actions"
)
MIN_PAGE = 25
# Seconds to wait before asking again after a network failure or a Meta server error (the last
# value is not used: the request has failed by then). Rides out a short outage of this computer's
# internet connection (seen 2026-11-24, about 6 minutes) together with the job's 5-minute retry.
RETRY_PAUSES = (5, 15, 45, 0)
RATE_LIMIT_CODES = {4, 17, 32, 613, *range(80000, 80015)}
USAGE_LIMIT_PCT = 90


class MetaError(Exception):
    """A Meta request that failed, with a `state` the page can explain and a message without
    secrets."""

    def __init__(self, state: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.state = state
        self.message = message
        self.status = status


@dataclass(frozen=True)
class TokenInfo:
    """When the access token stops working (None: never, or Meta did not say)."""

    valid: bool
    expires_at: datetime | None


class MetaClient:
    """Read-only access to one brand's Meta ad account."""

    def __init__(
        self,
        account: MetaAccount,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 90.0,
    ) -> None:
        self.account = account
        self._http = httpx.Client(
            base_url=f"{META_BASE_URL}/{META_API_VERSION}",
            headers={"Authorization": f"Bearer {account.token}", "User-Agent": "flowmerce-ads/1.0"},
            # A connection that cannot be opened in 15 s is retried (see get) rather than waited on.
            timeout=httpx.Timeout(timeout, connect=15.0),
            transport=transport,
        )

    def close(self) -> None:
        """Close the connection pool."""
        self._http.close()

    def __enter__(self) -> MetaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ low level
    def _scrub(self, text: str) -> str:
        return text.replace(self.account.token, "<hidden>") if self.account.token else text

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """One GET. `path` is relative to the pinned API version, or a full `paging.next` URL from
        Meta."""
        last: Exception | None = None
        for attempt, pause in enumerate(RETRY_PAUSES):
            final = attempt == len(RETRY_PAUSES) - 1
            try:
                r = self._http.get(path, params=params)
            except httpx.HTTPError as e:  # a network blip: wait a little longer each time
                last = e
                if not final:
                    time.sleep(pause)
                    continue
                raise MetaError(
                    "connection_failed", f"Could not reach Meta ({type(e).__name__})."
                ) from None
            # A server error is asked again, except "too much data", which asking again the same
            # way cannot fix (rows() and daily() split the request instead).
            if r.status_code >= 500 and not final and b"reduce the amount of data" not in r.content:
                time.sleep(pause)
                continue
            return self._answer(r)
        raise MetaError("connection_failed", f"Could not reach Meta ({type(last).__name__}).")

    def _answer(self, r: httpx.Response) -> dict[str, Any]:
        try:
            body = r.json()
        except ValueError:
            raise MetaError(
                "error", f"Meta answered HTTP {r.status_code} without JSON.", r.status_code
            ) from None
        if not isinstance(body, dict):
            raise MetaError("error", "Meta answered with an unexpected shape.", r.status_code)
        if "error" in body:
            raise self._error(r.status_code, body["error"])
        self._check_usage(r.headers.get("x-business-use-case-usage"))
        return body

    def _error(self, status: int, err: Any) -> MetaError:
        e = err if isinstance(err, dict) else {}
        code = e.get("code")
        msg = self._scrub(str(e.get("message") or "")[:300])
        if code == 190:
            return MetaError(
                "token_expired",
                "The Meta access token has expired or was revoked. Create a new "
                "token and put it in .env (RIDHI_/CPC_META_ACCESS_TOKEN).",
                status,
            )
        if code in RATE_LIMIT_CODES:
            return MetaError(
                "rate_limited",
                "Meta's request limit for this ad account is reached for now. The "
                "next round tries again.",
                status,
            )
        if code in (10, 200, 294) or (code == 100 and "permission" in msg.lower()):
            return MetaError("permission", f"Meta refused access: {msg}", status)
        if "reduce the amount of data" in msg.lower():
            return MetaError("too_much", f"Meta asked for smaller requests: {msg}", status)
        if code == 2635:
            return MetaError(
                "error", f"Meta no longer accepts API {META_API_VERSION}: {msg}", status
            )
        if status == 400:
            return MetaError("bad_request", f"Meta rejected the request: {msg}", status)
        return MetaError("error", f"Meta error {status}: {msg}", status)

    def _check_usage(self, header: str | None) -> None:
        """Stop before Meta blocks the account: any usage figure at USAGE_LIMIT_PCT or more."""
        if not header:
            return
        try:
            usage = json.loads(header)
        except ValueError:
            return
        for entries in usage.values() if isinstance(usage, dict) else []:
            for u in entries if isinstance(entries, list) else []:
                worst = max(
                    float(u.get(k) or 0) for k in ("call_count", "total_cputime", "total_time")
                )
                if (
                    worst >= USAGE_LIMIT_PCT
                    or float(u.get("estimated_time_to_regain_access") or 0) > 0
                ):
                    raise MetaError(
                        "rate_limited",
                        f"Meta's request limit for this ad account is {worst:.0f}% "
                        "used. The sync stops here and carries on next round.",
                    )

    def rows(self, path: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """Every row of a list answer, following Meta's `paging.next` links. When Meta asks for
        smaller requests, the page size is halved (down to MIN_PAGE) and the same page asked
        again."""
        body = self._page(path, params)
        while True:
            yield from body.get("data") or []
            nxt = (body.get("paging") or {}).get("next")
            if not nxt:
                return
            body = self._page(str(nxt), None)

    def _page(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        while True:
            try:
                return self.get(path, params)
            except MetaError as e:
                if e.state != "too_much":
                    raise
                if params is not None and int(params.get("limit") or 0) > MIN_PAGE:
                    params = {**params, "limit": int(params["limit"]) // 2}
                    continue
                m = re.search(r"([?&]limit=)(\d+)", path)
                if params is None and m and int(m.group(2)) > MIN_PAGE:
                    path = path[: m.start(2)] + str(int(m.group(2)) // 2) + path[m.end(2) :]
                    continue
                raise

    # ------------------------------------------------------------------ reads
    def account_info(self) -> dict[str, Any]:
        """Name, currency, time zone and status of the ad account."""
        return self.get(
            self.account.account_id,
            {"fields": "account_id,name,currency,timezone_name,account_status"},
        )

    def token_info(self) -> TokenInfo:
        """When the token stops working. A token that cannot be inspected counts as valid, expiry
        unknown."""
        try:
            d = self.get("debug_token", {"input_token": self.account.token}).get("data") or {}
        except MetaError as e:
            if e.state == "token_expired":
                return TokenInfo(False, None)
            return TokenInfo(True, None)
        ts = d.get("expires_at")
        expires = datetime.fromtimestamp(int(ts), UTC) if isinstance(ts, int) and ts > 0 else None
        return TokenInfo(bool(d.get("is_valid", True)), expires)

    def campaigns(self) -> list[dict[str, Any]]:
        """Every campaign with its status and budget."""
        return list(
            self.rows(
                f"{self.account.account_id}/campaigns",
                {
                    "fields": "id,name,objective,effective_status,daily_budget,lifetime_budget,"
                    "bid_strategy,created_time",
                    "limit": 200,
                },
            )
        )

    def ad_sets(self) -> list[dict[str, Any]]:
        """Every ad set with its campaign, status and budget."""
        return list(
            self.rows(
                f"{self.account.account_id}/adsets",
                {
                    "fields": "id,name,campaign_id,effective_status,daily_budget,optimization_goal",
                    "limit": 500,
                },
            )
        )

    def ads(self) -> list[dict[str, Any]]:
        """Every ad with its campaign, ad set, status and creative (post, video, thumbnail, and
        the copy and link that `ad_copy` reads)."""
        return list(
            self.rows(
                f"{self.account.account_id}/ads",
                {
                    "fields": "id,name,campaign_id,adset_id,effective_status,created_time,"
                    "creative{id,object_type,video_id,effective_object_story_id,thumbnail_url,"
                    "body,title,object_story_spec,asset_feed_spec}",
                    "limit": 100,
                },
            )
        )

    def daily(self, since: date, until: date) -> list[dict[str, Any]]:
        """One row per ad per account day with delivery between `since` and `until`, as ads.daily
        rows. When Meta asks for smaller requests, the days are read in two halves."""
        try:
            return [
                daily_row(r)
                for r in self.rows(
                    f"{self.account.account_id}/insights",
                    {
                        "level": "ad",
                        "time_increment": 1,
                        "fields": INSIGHT_FIELDS,
                        "limit": 500,
                        "time_range": json.dumps(
                            {"since": since.isoformat(), "until": until.isoformat()}
                        ),
                    },
                )
            ]
        except MetaError as e:
            if e.state != "too_much" or since >= until:
                raise
            mid = since + (until - since) // 2
            return self.daily(since, mid) + self.daily(mid + timedelta(days=1), until)

    def lifetime(self) -> list[dict[str, Any]]:
        """Each ad's totals since it started: {ad_id, spend, purchases, value}."""
        out = []
        for r in self.rows(
            f"{self.account.account_id}/insights",
            {
                "level": "ad",
                "date_preset": "maximum",
                "fields": "ad_id,spend,actions,action_values",
                "limit": 500,
            },
        ):
            acts, vals = _by_type(r.get("actions")), _by_type(r.get("action_values"))
            out.append(
                {
                    "ad_id": str(r.get("ad_id")),
                    "spend": _num(r.get("spend")),
                    "purchases": acts.get("purchase", 0.0),
                    "value": vals.get("purchase", 0.0),
                }
            )
        return out

    def budget_changes(self, since: datetime) -> dict[str, datetime]:
        """Campaigns whose budget changed since `since`, from the account's activity log: {campaign
        id: when}."""
        out: dict[str, datetime] = {}
        for r in self.rows(
            f"{self.account.account_id}/activities",
            {
                "fields": "event_type,event_time,object_id",
                "since": int(since.timestamp()),
                "limit": 200,
            },
        ):
            if "budget" not in str(r.get("event_type") or ""):
                continue
            at = _when(r.get("event_time"))
            oid = str(r.get("object_id") or "")
            if at and oid and (oid not in out or at > out[oid]):
                out[oid] = at
        return out


# ------------------------------------------------------------------ parsing (pure)
def _num(v: Any) -> float:
    try:
        return float(v)
    except TypeError, ValueError:
        return 0.0


def _by_type(items: Any) -> dict[str, float]:
    """Meta's [{action_type, value}, ...] lists as {action_type: value}."""
    return {
        str(a.get("action_type")): _num(a.get("value")) for a in items or [] if isinstance(a, dict)
    }


def _when(v: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("+0000", "+00:00"))
    except ValueError:
        return None


def daily_row(r: dict[str, Any]) -> dict[str, Any]:
    """One Meta insights row (level=ad, one day) as an ads.daily row (amounts in the account's
    currency)."""
    acts, vals = _by_type(r.get("actions")), _by_type(r.get("action_values"))
    plays = _by_type(r.get("video_play_actions")).get("video_view", 0.0)
    avg_watch = _by_type(r.get("video_avg_time_watched_actions")).get("video_view", 0.0)

    def video(field: str) -> int:
        return int(_by_type(r.get(field)).get("video_view", 0.0))

    return {
        "ad_id": str(r.get("ad_id")),
        "day": str(r.get("date_start")),
        "spend": round(_num(r.get("spend")), 2),
        "impressions": int(_num(r.get("impressions"))),
        "clicks": int(_by_type(r.get("outbound_clicks")).get("outbound_click", 0.0)),
        "link_clicks": int(_num(r.get("inline_link_clicks"))),
        "lpv": int(acts.get("landing_page_view", 0.0)),
        "atc": int(acts.get("omni_add_to_cart", acts.get("add_to_cart", 0.0))),
        "ic": int(acts.get("omni_initiated_checkout", acts.get("initiate_checkout", 0.0))),
        "purchases": acts.get("purchase", 0.0),
        "value": round(vals.get("purchase", 0.0), 2),
        "v3": int(acts.get("video_view", 0.0)),
        "p25": video("video_p25_watched_actions"),
        "p50": video("video_p50_watched_actions"),
        "p75": video("video_p75_watched_actions"),
        "p95": video("video_p95_watched_actions"),
        "plays": int(plays),
        "watch_s": round(avg_watch * plays, 1),
    }


def minor_to_major(v: Any) -> float | None:
    """Meta's budgets are in the currency's smallest unit (cents, paise): '2000000' -> 20000.0. None
    when unset."""
    if v in (None, "", "0", 0):
        return None
    return round(_num(v) / 100, 2)


def ad_row(account_key: str, a: dict[str, Any]) -> dict[str, Any]:
    """One Meta ad as an ads.ads row (structure only; lifetime totals and video length are kept
    separately)."""
    cr = a.get("creative") or {}
    video_id = cr.get("video_id")
    return {
        "id": str(a["id"]),
        "account_key": account_key,
        "campaign_id": str(a.get("campaign_id") or ""),
        "ad_set_id": str(a.get("adset_id") or ""),
        "name": str(a.get("name") or ""),
        "status": str(a.get("effective_status") or ""),
        "created_time": a.get("created_time"),
        "post_id": cr.get("effective_object_story_id"),
        "format": "video"
        if video_id or str(cr.get("object_type") or "").upper() == "VIDEO"
        else "image",
        "video_id": str(video_id) if video_id else None,
        "thumbnail_url": cr.get("thumbnail_url"),
    }


def _first(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _feed_text(feed: dict[str, Any], key: str) -> str | None:
    for entry in feed.get(key) or []:
        if isinstance(entry, dict) and str(entry.get("text") or "").strip():
            return str(entry["text"]).strip()
    return None


def ad_copy(a: dict[str, Any]) -> dict[str, str | None]:
    """The ad's own words and link, wherever this kind of creative keeps them: primary text,
    headline and destination URL. Kept apart from `ad_row` so the sync can still save an ad when
    the database does not have these columns yet (before 118_creative_tags.sql is run)."""
    cr = a.get("creative") or {}
    spec = cr.get("object_story_spec") or {}
    link_data = spec.get("link_data") or {}
    video_data = spec.get("video_data") or {}
    feed = cr.get("asset_feed_spec") or {}
    children = [c for c in link_data.get("child_attachments") or [] if isinstance(c, dict)]
    cta = ((video_data.get("call_to_action") or {}).get("value") or {}).get("link")
    feed_link = next(
        (
            str(e["website_url"])
            for e in feed.get("link_urls") or []
            if isinstance(e, dict) and e.get("website_url")
        ),
        None,
    )
    return {
        "primary_text": _first(
            cr.get("body"), link_data.get("message"), video_data.get("message"),
            _feed_text(feed, "bodies"),
        ),
        "headline": _first(
            cr.get("title"), link_data.get("name"), video_data.get("title"),
            _feed_text(feed, "titles"), *(c.get("name") for c in children),
        ),
        "link_url": _first(
            link_data.get("link"), *(c.get("link") for c in children), cta, feed_link
        ),
    }
