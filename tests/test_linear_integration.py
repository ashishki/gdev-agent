"""Linear integration tests."""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from app.integrations.linear import LinearClient


@patch("app.integrations.linear.httpx.Client")
def test_create_issue_success(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_response = Mock(status_code=200)
    mock_response.json.return_value = {
        "data": {
            "issueCreate": {
                "issue": {"identifier": "ENG-42", "url": "https://linear.app/acme/issue/ENG-42"}
            }
        }
    }
    mock_response.raise_for_status.return_value = None
    mock_client.post.return_value = mock_response

    result = LinearClient("key").create_issue("t", "d", 2, "team")
    assert result["ticket_id"] == "ENG-42"
    assert result["url"].startswith("https://linear.app")


@patch("app.integrations.linear.httpx.Client")
def test_create_issue_429_raises_503(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.post.return_value = Mock(status_code=429)

    with pytest.raises(HTTPException) as exc:
        LinearClient("key").create_issue("t", "d", 2, "team")
    assert exc.value.status_code == 503


@patch("app.integrations.linear.httpx.Client")
def test_create_issue_4xx_raises_500(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    mock_client.post.return_value = Mock(status_code=400)

    with pytest.raises(HTTPException) as exc:
        LinearClient("key").create_issue("t", "d", 2, "team")
    assert exc.value.status_code == 500
