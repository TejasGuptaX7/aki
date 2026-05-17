"""Linear native OAuth handler.

Linear's GraphQL API + OAuth2. Tokens are workspace-scoped and refreshable.

Setup (founder):
  1. linear.app/settings/api → OAuth applications → New.
  2. Redirect URI: ${WEB_BASE_URL}/connect/oauth/callback
  3. Scopes: `read,write,issues:create,comments:create`. Tick "Public"
     so non-workspace-members can install.
  4. Copy client_id + secret into LINEAR_CLIENT_ID / LINEAR_CLIENT_SECRET.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Connection
from app.oauth.base import (
    NativeOAuthError,
    NativeToolSpec,
    OAuthHandler,
    _register,
)


log = logging.getLogger(__name__)


LINEAR_SCOPES = ["read", "write", "issues:create", "comments:create"]


async def _linear_graphql(token: str, query: str, variables: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as c:
        r = await c.post(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables or {}},
        )
    if r.status_code >= 400:
        raise NativeOAuthError(
            "linear graphql failed", status=r.status_code, body=r.text[:500]
        )
    body = r.json()
    if body.get("errors"):
        raise NativeOAuthError(
            f"linear graphql errors: {body['errors']}",
            body=str(body)[:500],
        )
    return body.get("data") or {}


# ── Tool callables ──────────────────────────────────────────────────────────


_LIST_ISSUES_QUERY = """
query ListIssues($first: Int!, $filter: IssueFilter) {
  issues(first: $first, filter: $filter) {
    nodes {
      id identifier title state { name } priority assignee { name }
      url updatedAt
    }
  }
}
"""


_CREATE_COMMENT_QUERY = """
mutation CreateComment($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
    comment { id url }
  }
}
"""


async def _list_issues(args: dict, conn: Connection, db: AsyncSession) -> Any:
    token = (conn.config or {}).get("access_token")
    flt: dict[str, Any] = {}
    if args.get("assignee_email"):
        flt["assignee"] = {"email": {"eq": args["assignee_email"]}}
    if args.get("state"):
        flt["state"] = {"name": {"eq": args["state"]}}
    return await _linear_graphql(
        token,
        _LIST_ISSUES_QUERY,
        {"first": min(int(args.get("limit") or 25), 100), "filter": flt or None},
    )


async def _create_comment(args: dict, conn: Connection, db: AsyncSession) -> Any:
    """TIER-2: posting a comment is user-visible."""
    token = (conn.config or {}).get("access_token")
    issue_id = (args.get("issue_id") or "").strip()
    body = args.get("body") or ""
    if not issue_id or not body:
        raise NativeOAuthError("issue_id and body required")
    return await _linear_graphql(
        token,
        _CREATE_COMMENT_QUERY,
        {"issueId": issue_id, "body": body},
    )


# ── Handler ─────────────────────────────────────────────────────────────────


class LinearHandler(OAuthHandler):
    provider_slug = "linear"
    display_provider = "linear"
    authorize_url = "https://linear.app/oauth/authorize"
    token_url = "https://api.linear.app/oauth/token"
    default_scopes = LINEAR_SCOPES
    scope_delimiter = ","
    # Linear's OAuth requires explicit `actor=app` for installs that act
    # on behalf of the integration itself rather than a user.
    extra_auth_params = {"actor": "app"}

    def client_id(self) -> str | None:
        return get_settings().linear_client_id

    def client_secret(self) -> str | None:
        return get_settings().linear_client_secret

    def tools(self) -> list[NativeToolSpec]:
        return [
            NativeToolSpec(
                name="linear_list_issues",
                description=(
                    "List Linear issues, optionally filtered by assignee email "
                    "or state name. Default: 25 most-recently-updated issues "
                    "across the workspace."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "assignee_email": {"type": "string"},
                        "state": {
                            "type": "string",
                            "description": "Workflow state name (e.g. 'In Progress', 'Done').",
                        },
                        "limit": {"type": "integer", "default": 25},
                    },
                },
                caller=_list_issues,
            ),
            NativeToolSpec(
                name="linear_create_comment",
                description=(
                    "Post a comment on a Linear issue. TIER-2: "
                    "request_approval before sending."
                ),
                input_schema={
                    "type": "object",
                    "required": ["issue_id", "body"],
                    "properties": {
                        "issue_id": {
                            "type": "string",
                            "description": "Linear issue UUID (not the 'PRO-123' identifier).",
                        },
                        "body": {"type": "string"},
                    },
                },
                caller=_create_comment,
            ),
        ]


_register(LinearHandler())
