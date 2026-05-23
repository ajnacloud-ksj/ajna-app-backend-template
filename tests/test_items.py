"""Tests for src/handlers/items.py — CRUD and role-based access control."""

import json
import pytest

from src.handlers.items import (
    query_items, create_item, get_item, update_item, delete_item,
)
from tests.conftest import FakeIbexDB, ctx, event, as_role, ITEM_PAYLOAD


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create(db, role="admin", payload=None):
    with as_role(role):
        return create_item(
            event(body=payload or ITEM_PAYLOAD),
            ctx(db, role),
        )


def _created_id(db, role="admin", payload=None):
    resp = _create(db, role, payload)
    assert resp["statusCode"] == 201, json.loads(resp["body"])
    return json.loads(resp["body"])["id"]


# ── create_item ────────────────────────────────────────────────────────────────

def test_create_item_success_admin():
    db = FakeIbexDB()
    resp = _create(db, "admin")
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["name"] == "Widget"
    assert body["code"] == "ITM-001"
    assert "id" in body
    assert "created_at" in body


def test_create_item_success_super_admin():
    db = FakeIbexDB()
    resp = _create(db, "super_admin")
    assert resp["statusCode"] == 201


def test_create_item_forbidden_for_user():
    db = FakeIbexDB()
    resp = _create(db, "user")
    assert resp["statusCode"] == 403


def test_create_item_requires_name():
    db = FakeIbexDB()
    payload = {**ITEM_PAYLOAD, "name": ""}
    resp = _create(db, "admin", payload)
    assert resp["statusCode"] == 400
    assert "name" in json.loads(resp["body"])["error"]


def test_create_item_optional_fields_are_accepted():
    db = FakeIbexDB()
    payload = {
        **ITEM_PAYLOAD,
        "sku": "SKU-9",
        "status": "active",
        "quantity": 10,
        "price": 4.99,
    }
    resp = _create(db, "admin", payload)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["sku"] == "SKU-9"
    assert body["status"] == "active"


# ── query_items ──────────────────────────────────────────────────────────────

def test_query_items_returns_all_for_read_roles():
    db = FakeIbexDB()
    _create(db, "admin")
    _create(db, "admin", {**ITEM_PAYLOAD, "code": "ITM-002", "name": "Gadget"})

    for role in ("super_admin", "admin", "user"):
        with as_role(role):
            resp = query_items(event(method="GET"), ctx(db, role))
        assert resp["statusCode"] == 200, f"role={role} got {resp['statusCode']}"
        assert len(json.loads(resp["body"])["data"]) == 2


def test_query_items_unauthenticated_role_forbidden():
    db = FakeIbexDB()
    with as_role("unknown_role"):
        resp = query_items(event(method="GET"), ctx(db, "unknown_role"))
    assert resp["statusCode"] == 403


def test_query_items_with_filter():
    db = FakeIbexDB()
    _create(db, "admin")
    _create(db, "admin", {**ITEM_PAYLOAD, "code": "ITM-002", "name": "Gadget"})

    with as_role("admin"):
        resp = query_items(
            event(body={"filters": [{"field": "code", "operator": "eq", "value": "ITM-002"}]}),
            ctx(db, "admin"),
        )
    assert resp["statusCode"] == 200
    records = json.loads(resp["body"])["data"]
    assert len(records) == 1
    assert records[0]["code"] == "ITM-002"


def test_query_items_pagination():
    db = FakeIbexDB()
    for i in range(5):
        _create(db, "admin", {**ITEM_PAYLOAD, "code": f"ITM-{i:03d}", "name": f"Item {i}"})

    with as_role("admin"):
        resp = query_items(event(body={"limit": 2, "offset": 0}), ctx(db, "admin"))
    assert resp["statusCode"] == 200
    assert len(json.loads(resp["body"])["data"]) == 2

    with as_role("admin"):
        resp = query_items(event(body={"limit": 2, "offset": 2}), ctx(db, "admin"))
    assert resp["statusCode"] == 200
    assert len(json.loads(resp["body"])["data"]) == 2


# ── get_item ───────────────────────────────────────────────────────────────────

def test_get_item_found():
    db = FakeIbexDB()
    iid = _created_id(db)

    for role in ("super_admin", "admin", "user"):
        with as_role(role):
            resp = get_item(event(method="GET", path_params={"item_id": iid}), ctx(db, role))
        assert resp["statusCode"] == 200, f"role={role}"
        assert json.loads(resp["body"])["id"] == iid


def test_get_item_not_found():
    db = FakeIbexDB()
    with as_role("admin"):
        resp = get_item(event(method="GET", path_params={"item_id": "nonexistent-id"}), ctx(db, "admin"))
    assert resp["statusCode"] == 404


# ── update_item ─────────────────────────────────────────────────────────────────

def test_update_item_success_admin():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("admin"):
        resp = update_item(
            event(method="PUT", body={"description": "Updated"}, path_params={"item_id": iid}),
            ctx(db, "admin"),
        )
    assert resp["statusCode"] == 200


def test_update_item_success_super_admin():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("super_admin"):
        resp = update_item(
            event(method="PUT", body={"description": "SA"}, path_params={"item_id": iid}),
            ctx(db, "super_admin"),
        )
    assert resp["statusCode"] == 200


def test_update_item_forbidden_for_user():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("user"):
        resp = update_item(
            event(method="PUT", body={"description": "Hacked"}, path_params={"item_id": iid}),
            ctx(db, "user"),
        )
    assert resp["statusCode"] == 403


def test_update_item_rejects_empty_body():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("admin"):
        resp = update_item(
            event(method="PUT", body={}, path_params={"item_id": iid}),
            ctx(db, "admin"),
        )
    assert resp["statusCode"] == 400


def test_update_item_strips_id_and_created_at():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("admin"):
        resp = update_item(
            event(
                method="PUT",
                body={"description": "Safe", "id": "injected-id", "created_at": "1970-01-01"},
                path_params={"item_id": iid},
            ),
            ctx(db, "admin"),
        )
    assert resp["statusCode"] == 200
    record = db._tables["app_items"][0]
    assert record["id"] == iid


# ── delete_item ─────────────────────────────────────────────────────────────────

def test_delete_item_success_admin():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("admin"):
        resp = delete_item(
            event(method="DELETE", path_params={"item_id": iid}),
            ctx(db, "admin"),
        )
    assert resp["statusCode"] == 204


def test_delete_item_success_super_admin():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("super_admin"):
        resp = delete_item(
            event(method="DELETE", path_params={"item_id": iid}),
            ctx(db, "super_admin"),
        )
    assert resp["statusCode"] == 204


def test_delete_item_forbidden_for_user():
    db = FakeIbexDB()
    iid = _created_id(db)
    with as_role("user"):
        resp = delete_item(
            event(method="DELETE", path_params={"item_id": iid}),
            ctx(db, "user"),
        )
    assert resp["statusCode"] == 403


# ── Role permission matrix (documents RBAC contract) ─────────────────────────

RBAC_MATRIX = [
    # (role,           create, read, update, delete)
    ("super_admin",    201,    200,  200,    204),
    ("admin",          201,    200,  200,    204),
    ("user",           403,    200,  403,    403),
]


@pytest.mark.parametrize("role,exp_create,exp_read,exp_update,exp_delete", RBAC_MATRIX)
def test_item_rbac_matrix(role, exp_create, exp_read, exp_update, exp_delete):
    db = FakeIbexDB()

    with as_role(role):
        create_resp = create_item(event(body=ITEM_PAYLOAD), ctx(db, role))
    assert create_resp["statusCode"] == exp_create, f"create: role={role}"

    # Seed an item via admin for the read/update/delete tests
    iid = _created_id(db, "admin")

    with as_role(role):
        read_resp = get_item(event(method="GET", path_params={"item_id": iid}), ctx(db, role))
    assert read_resp["statusCode"] == exp_read, f"read: role={role}"

    with as_role(role):
        upd_resp = update_item(
            event(method="PUT", body={"description": "X"}, path_params={"item_id": iid}),
            ctx(db, role),
        )
    assert upd_resp["statusCode"] == exp_update, f"update: role={role}"

    with as_role(role):
        del_resp = delete_item(
            event(method="DELETE", path_params={"item_id": iid}),
            ctx(db, role),
        )
    assert del_resp["statusCode"] == exp_delete, f"delete: role={role}"
