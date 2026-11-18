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


class _HealthAnswer:
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def json(self):
        return self._body


@pytest.fixture
def data_service(monkeypatch):
    """/ready (SDK >= 4.2.1, ajna-cloud-sdk#566) asks the data service's own unauthenticated
    GET /health: no token, no tenant, no data call. The probe's HTTP GET is stubbed here."""
    from ajna_cloud import health as probe

    monkeypatch.setenv("IBEX_API_URL", "https://data.example")
    probe.reset_cache()
    state = {"answer": _HealthAnswer(200, {"status": "healthy", "version": "1.0.0"})}

    def _get(url, **kw):
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        return state["answer"]

    monkeypatch.setattr(probe, "_http_get", _get)
    yield state
    probe.reset_cache()


def test_ready_when_the_data_service_answers(data_service):
    mock_db = MagicMock()
    mock_db.api_url = "https://data.example"
    result = health.ready(make_event("GET", "/ready"), make_context(db=mock_db))
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["checks"] == {"data_service": True}
    mock_db.list_tables.assert_not_called()      # token only: /ready makes no data call


def test_not_ready_when_the_data_service_is_down(data_service):
    data_service["answer"] = ConnectionError("connection refused")
    mock_db = MagicMock()
    mock_db.api_url = "https://data.example"
    result = health.ready(make_event("GET", "/ready"), make_context(db=mock_db))
    assert result["statusCode"] == 503
    assert json.loads(result["body"])["ready"] is False


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
