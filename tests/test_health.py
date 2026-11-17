"""Tests for SDK-provided health handlers."""
import json
import pytest
from unittest.mock import MagicMock
from ajna_cloud import make_health_handlers


def make_event(method="GET", path="/health", body=None):
    return {
        "httpMethod": method,
        "resource": path,
        "path": path,
        "headers": {},
        "queryStringParameters": None,
        "pathParameters": None,
        "body": body,
    }


def make_context(db=None):
    return {"db": db or MagicMock(), "schemas": {}, "settings": MagicMock()}


health = make_health_handlers(service_name='{{app-name}}')


def test_health_check():
    result = health.check(make_event(), make_context())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "healthy"


def test_ready_db_ok():
    mock_db = MagicMock()
    mock_db.list_tables.return_value = {"success": True}
    result = health.ready(make_event("GET", "/ready"), make_context(db=mock_db))
    assert result["statusCode"] == 200


def test_ready_db_fail():
    mock_db = MagicMock()
    mock_db.list_tables.side_effect = Exception("connection refused")
    result = health.ready(make_event("GET", "/ready"), make_context(db=mock_db))
    assert result["statusCode"] == 503


def test_status():
    # /status reports cache metrics from db.get_stats(). The IbexDB client returns a
    # dict there (ajna_cloud/ibex.py IbexClient.get_stats), so the stub must return
    # one too; a bare MagicMock returns a MagicMock that cannot be %-formatted.
    mock_db = MagicMock()
    mock_db.get_stats.return_value = {"cache_hit_rate": 0.25, "total_requests": 8}
    result = health.status(make_event("GET", "/status"), make_context(db=mock_db))
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "operational"
    assert body["cache"] == {"hit_rate": "25.0%", "total_requests": 8}


def test_status_without_db_stats():
    # A db without get_stats (e.g. a non-IbexDB storage adapter) gets no cache block.
    result = health.status(make_event("GET", "/status"), make_context(db=object()))
    assert result["statusCode"] == 200
    assert "cache" not in json.loads(result["body"])
