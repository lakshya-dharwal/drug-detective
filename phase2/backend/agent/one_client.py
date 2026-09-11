"""One (withone.ai) — the agent's write-back into a real external system.

This is the step that takes the loop past "produced an answer". After a round,
the agent publishes its findings and its strategy change to the user's actual
Notion workspace through One's passthrough API, so the investigation leaves a
durable artifact somewhere a human already works.

Degrades to a skipped status (never an exception) when unconfigured.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.withone.ai/v1"
TIMEOUT = float(os.getenv("ONE_TIMEOUT_SECONDS", "20"))
PLATFORM = "notion"


def is_configured() -> bool:
    return bool(os.getenv("ONE_API_KEY"))


def _headers(action_id: Optional[str] = None, connection_key: Optional[str] = None) -> dict[str, str]:
    h = {"x-one-secret": os.getenv("ONE_API_KEY", ""), "Content-Type": "application/json"}
    if action_id:
        h["x-one-action-id"] = action_id
    if connection_key:
        h["x-one-connection-key"] = connection_key
    return h


def _get_connection_key() -> Optional[str]:
    """Find the user's live Notion connection."""
    try:
        r = requests.get(f"{API_BASE}/vault/connections?page=1&limit=100",
                         headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        for row in r.json().get("rows", []):
            if row.get("platform") == PLATFORM and row.get("active"):
                return row.get("key")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("One: could not list connections: %s", exc)
    return None


def _get_action_id(method: str, path: str) -> Optional[str]:
    """Resolve a platform action to the systemId the passthrough header needs."""
    try:
        r = requests.get(f"{API_BASE}/available-actions/{PLATFORM}?limit=200",
                         headers=_headers(), timeout=TIMEOUT)
        r.raise_for_status()
        for row in r.json().get("rows", []):
            if row.get("method") == method and row.get("path") == path:
                return row.get("systemId")
    except (requests.RequestException, ValueError) as exc:
        logger.warning("One: could not list actions: %s", exc)
    return None


def _passthrough(method: str, path: str, body: dict[str, Any],
                 connection_key: str, action_id: str) -> Optional[dict[str, Any]]:
    try:
        r = requests.request(
            method, f"{API_BASE}/passthrough{path}",
            headers=_headers(action_id, connection_key), json=body, timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("One passthrough %s %s failed: %s", method, path, exc)
        return None


def _rich_text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": {"content": content[:1900]}}


def _para(content: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [_rich_text(content)]}}


def _heading(content: str) -> dict[str, Any]:
    return {"object": "block", "type": "heading_3",
            "heading_3": {"rich_text": [_rich_text(content)]}}


def publish_investigation(investigation: dict[str, Any]) -> dict[str, Any]:
    """Write one investigation's learning + strategy change into Notion.

    Returns a status dict describing what actually happened, so the API response
    can honestly report whether the external write landed.
    """
    if not is_configured():
        return {"published": False, "reason": "ONE_API_KEY not set"}

    connection_key = _get_connection_key()
    if not connection_key:
        return {"published": False, "reason": "no active Notion connection in One"}

    search_id = _get_action_id("POST", "/search")
    create_id = _get_action_id("POST", "/pages")
    if not (search_id and create_id):
        return {"published": False, "reason": "could not resolve Notion actions"}

    # A page the connection can already write under becomes the parent.
    found = _passthrough("POST", "/search", {"page_size": 5}, connection_key, search_id)
    parent_id = None
    for row in ((found or {}).get("results") or []):
        if row.get("object") == "page":
            parent_id = row.get("id")
            break
    if not parent_id:
        return {"published": False, "reason": "no writable Notion parent page found"}

    disease = investigation.get("disease", "unknown disease")
    learning = investigation.get("learning", {})
    diff = investigation.get("strategy_diff", {})
    imp = investigation.get("improvement", {})
    r1, r2 = investigation.get("round_1", {}), investigation.get("round_2", {})

    children = [
        _heading("What I learned"),
        _para(learning.get("what_i_learned", "")),
        _heading("What I changed"),
        _para(learning.get("what_i_am_changing", "")),
        _heading("Strategy change"),
        _para(f"Lever moved: {diff.get('changed_lever')} — {diff.get('rationale','')}"),
        _heading("Rounds"),
        _para(f"Round 1 ({', '.join(r1.get('candidates_investigated', []))}) "
              f"mean confidence {r1.get('mean_confidence')}"),
        _para(f"Round 2 ({', '.join(r2.get('candidates_investigated', []))}) "
              f"mean confidence {r2.get('mean_confidence')} "
              f"(delta {imp.get('delta')})"),
        _para("Research-support prototype. Candidates are repurposing hypotheses "
              "for investigation, not treatment recommendations."),
    ]

    title = f"Drug Detective — {disease} — investigation {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    created = _passthrough("POST", "/pages", {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [_rich_text(title)]}},
        "children": children,
    }, connection_key, create_id)

    if not created or not created.get("id"):
        return {"published": False, "reason": "Notion page creation failed"}

    return {
        "published": True,
        "platform": "notion",
        "page_id": created.get("id"),
        "page_url": created.get("url"),
        "title": title,
        "via": "one.passthrough",
    }
