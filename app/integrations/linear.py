"""Linear GraphQL integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import HTTPException

LOGGER = logging.getLogger(__name__)

_MUTATION = """
mutation CreateIssue($title: String!, $description: String, $priority: Int, $teamId: String!) {
  issueCreate(input: {
    title: $title, description: $description, priority: $priority, teamId: $teamId
  }) {
    success
    issue { id identifier url }
  }
}
"""


class LinearClient:
    """Tiny client for creating Linear issues."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def create_issue(
        self,
        title: str,
        description: str,
        priority: int,
        team_id: str,
    ) -> dict[str, Any]:
        """Create issue in Linear and return normalized ticket payload."""
        headers = {"Authorization": self.api_key, "Content-Type": "application/json"}
        body = {
            "query": _MUTATION,
            "variables": {
                "title": title,
                "description": description,
                "priority": priority,
                "teamId": team_id,
            },
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post("https://api.linear.app/graphql", json=body, headers=headers)

        if response.status_code == 429:
            LOGGER.warning("linear throttled", extra={"event": "linear_throttled", "context": {}})
            raise HTTPException(status_code=503, detail="Linear temporarily unavailable")
        if 400 <= response.status_code < 500:
            LOGGER.error(
                "linear client error",
                extra={"event": "linear_client_error", "context": {"status_code": response.status_code}},
            )
            raise HTTPException(status_code=500, detail="Internal: ticketing provider rejected request")
        response.raise_for_status()

        payload = response.json()
        issue = (
            payload.get("data", {})
            .get("issueCreate", {})
            .get("issue", {})
        )
        return {
            "ticket_id": issue.get("identifier"),
            "url": issue.get("url"),
            "status": "created",
        }

