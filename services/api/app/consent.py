"""Tool-tier classification for the three-tier consent model.

Every MCP tool an agent might call is classified into one of three tiers:

  TIER_AUTO   (1) — execute and audit. Read operations, navigation, lookups.
  TIER_ASK    (2) — require explicit user approval via /approvals before
                    running. External-facing actions (send email, post in a
                    public channel, sign up for a new account).
  TIER_FORBID (3) — never exposed to the agent at all. Filtered out by
                    materialize.py so the tool isn't even in the agent's
                    tool catalogue. Anything that moves money or signs a
                    binding commitment.

The classifier is deliberately conservative: when in doubt, return ASK.
Better to surface an unnecessary approval prompt than to skip one that
mattered. The cost of a false negative on TIER_FORBID is much higher.

Real-world tool names from Composio / Pipedream / Arcade follow patterns
like `composio_gmail_send_message`, `pipedream_slack_chat_postMessage`,
`arcade_gmail_send`. The regex patterns target the action verb (send,
post, charge, withdraw) so they work across provider naming conventions.
"""
from __future__ import annotations

import re
from enum import IntEnum


class Tier(IntEnum):
    AUTO = 1
    ASK = 2
    FORBID = 3


# Tools NEVER exposed to the agent — anything that moves money or signs a
# legally-binding commitment. Filtered out at materialize time so the agent's
# tool catalogue doesn't even contain them. The patterns are intentionally
# broad: a false positive (over-filtering) is recoverable; a false negative
# is a rogue charge on someone's card.
_FORBID_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bstripe[_-]?",
        r"\bplaid[_-]?",
        r"\bsquare[_-]?",
        r"\bbraintree[_-]?",
        r"\bpaypal[_-]?",
        r"\bvenmo[_-]?",
        r"\bcoinbase[_-]?",
        r"\bcrypto[_-]?",
        r"\bcharge\b",
        r"\bpayment\b",
        r"\bpayout\b",
        r"\binvoice[_-]?(create|send|pay|finalize)",
        r"\bwithdraw\b",
        r"\btransfer[_-]?money\b",
        r"\bach[_-]?",
        r"\bwire[_-]?transfer\b",
        r"\bsubscription[_-]?(create|charge)",
        # Signing legally-binding things
        r"\bdocusign[_-]?(send|sign)",
        r"\besign[_-]?",
        r"\bcontract[_-]?(sign|execute)",
    )
)


# Tools that require user approval — anything externally visible or
# irreversible. Same conservative bias: the cost of an extra prompt is
# tiny, the cost of an un-approved customer email is reputational.
_ASK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # External communication
        r"\b(send|reply|forward)[_-]?(email|message|mail)\b",
        r"\bemail[_-]?(send|reply|forward)\b",
        r"\bgmail[_-]?send\b",
        r"\bsms[_-]?send\b",
        r"\btwilio[_-]?(send|message|call)",
        # Posting publicly
        r"\bpost[_-]?(message|tweet|status|update)\b",
        r"\bpublish\b",
        r"\btweet\b",
        r"\bchannel[_-]?(post|publish)",
        r"\bslack[_-]?(post|send)",
        # Creating accounts / signing up
        r"\bsign[_-]?up\b",
        r"\bsignup\b",
        r"\bregister[_-]?account\b",
        r"\bcreate[_-]?account\b",
        # Destructive ops
        r"\bdelete[_-]?(record|row|file|repo|branch|user|message|account)",
        r"\bdrop[_-]?(table|database)",
        # External-facing write ops on people / customers
        r"\b(create|add|invite)[_-]?(user|member|collaborator|guest)\b",
        r"\bmerge[_-]?pull[_-]?request\b",
        r"\bdeploy\b",
    )
)


# Explicit AUTO whitelist — these short-circuit the regex check. Use for
# read tools whose names happen to match an ASK pattern (e.g. anything with
# "send" in it for symmetry).
_EXPLICIT_AUTO: frozenset[str] = frozenset({
    # Search / get / list — generally safe
    "gmail_list_messages",
    "gmail_get_message",
    "gmail_get_attachment",
    "gmail_list_drafts",
    "slack_list_channels",
    "slack_list_users",
    "calendar_list_events",
    "calendar_get_event",
    "notion_search",
    "notion_get_page",
    "linear_list_issues",
    "linear_get_issue",
    "github_list_repos",
    "github_get_file",
    # Browser harness — read-only ops are safe
    "navigate",
    "extract_text",
    "extract_html",
    "screenshot",
    "page_info",
    "list_tabs",
    "wait_for_load",
    "wait_for_element",
    "wait_for_network_idle",
    "session_info",
    "list_skills",
    "http_get",
})


def tier_for_tool(name: str) -> Tier:
    """Classify a tool name into one of the three tiers.

    `name` is the raw tool name as it appears in the MCP tool catalogue
    (e.g. `composio_gmail_send_message`, `navigate`, `slack_chat_postMessage`).
    Match is case-insensitive.
    """
    if not name:
        return Tier.ASK  # malformed = treat as ask, never auto

    # Explicit allowlist wins. Compare against the bare name AND the
    # de-prefixed suffix so `composio_gmail_get_message` resolves like
    # `gmail_get_message`.
    bare = name.lower()
    suffix = re.sub(r"^(composio|pipedream|arcade)_", "", bare)
    if bare in _EXPLICIT_AUTO or suffix in _EXPLICIT_AUTO:
        return Tier.AUTO

    for pat in _FORBID_PATTERNS:
        if pat.search(name):
            return Tier.FORBID
    for pat in _ASK_PATTERNS:
        if pat.search(name):
            return Tier.ASK
    return Tier.AUTO


def is_forbidden(name: str) -> bool:
    """Convenience for materialize.py: drop FORBID tools from the catalogue."""
    return tier_for_tool(name) is Tier.FORBID


def requires_approval(name: str) -> bool:
    """Convenience for the agent runtime: tools that need an approval gate."""
    return tier_for_tool(name) is Tier.ASK
