"""Unit tests for the Self Mastery registration Lambda.

Runs without AWS credentials or a live DynamoDB — the table resource is
replaced with an in-memory fake.

    python -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import handler  # noqa: E402


class FakeTable:
    """Minimal DynamoDB stand-in covering query + put_item."""

    def __init__(self, existing_items=None, fail_conditionally=False):
        self.items = {i["pk"]: dict(i) for i in (existing_items or [])}
        self.fail_conditionally = fail_conditionally
        self.put_calls = 0

    def query(self, **kwargs):
        items = [i for i in self.items.values() if i.get("gsi1pk", "").startswith("EMAIL#")]
        # Cheap stand-in: match on the single email we seeded.
        return {"Items": list(self._matching.values()) if hasattr(self, "_matching") else items}

    def seed_email(self, item):
        self._matching = {item["pk"]: item}

    def put_item(self, Item=None, ConditionExpression=None, **kwargs):
        self.put_calls += 1
        if self.fail_conditionally:
            raise RuntimeError("ConditionalCheckFailedException")
        if Item["pk"] in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[Item["pk"]] = dict(Item)


def make_event(payload, headers=None, method="POST", path="/registrations"):
    return {
        "requestContext": {"http": {"method": method, "path": path}},
        "headers": headers or {"Content-Type": "application/json"},
        "isBase64Encoded": False,
        "body": __import__("json").dumps(payload),
    }


VALID = {
    "first_name": "Thandi",
    "surname": "Nkosi",
    "email": "thandi@example.co.za",
    "mobile": "072 123 4567",
    "pricing_plan": "once_off",
}


class RegistrationTestCase(unittest.TestCase):
    def setUp(self):
        handler._table = None

    def test_health(self):
        resp = handler.handler(
            {"requestContext": {"http": {"method": "GET", "path": "/health"}}}, None
        )
        self.assertEqual(resp["statusCode"], 200)
        body = __import__("json").loads(resp["body"])
        self.assertTrue(body["ok"])
        self.assertEqual(body["programme_code"], "SP-MASTER")

    def test_options_preflight(self):
        resp = handler.handler(
            {"requestContext": {"http": {"method": "OPTIONS", "path": "/registrations"}}}, None
        )
        self.assertEqual(resp["statusCode"], 204)

    def test_successful_registration_once_off(self):
        fake = FakeTable()
        handler._table = fake
        resp = handler.handler(make_event(VALID), None)
        self.assertEqual(resp["statusCode"], 201)
        body = __import__("json").loads(resp["body"])
        self.assertTrue(body["participant_id"].startswith("MSRI-"))
        self.assertEqual(body["programme_code"], "SP-MASTER")
        self.assertEqual(body["cohort_code"], "2026-S1")
        self.assertEqual(body["amount_due"], 500.0)
        # Mobile normalised to E.164
        self.assertEqual(body["mobile"], "+27721234567")
        stored = fake.items[f"PARTICIPANT#{body['participant_id']}"]
        self.assertEqual(stored["amount_due"], Decimal("500"))

    def test_successful_registration_monthly(self):
        fake = FakeTable()
        handler._table = fake
        event = make_event({**VALID, "email": "sipho@example.co.za", "pricing_plan": "monthly"})
        resp = handler.handler(event, None)
        self.assertEqual(resp["statusCode"], 201)
        body = __import__("json").loads(resp["body"])
        self.assertEqual(body["amount_due"], 200.0)
        self.assertEqual(body["instalments"], 3)
        self.assertEqual(body["pricing_plan"], "monthly")

    def test_missing_fields_rejected(self):
        handler._table = FakeTable()
        resp = handler.handler(make_event({"first_name": "A"}), None)
        self.assertEqual(resp["statusCode"], 400)
        body = __import__("json").loads(resp["body"])
        fields = {d["field"] for d in body["details"]}
        self.assertLessEqual({"surname", "email", "mobile", "pricing_plan"}, fields)

    def test_invalid_mobile_rejected(self):
        handler._table = FakeTable()
        event = make_event({**VALID, "mobile": "123"})
        resp = handler.handler(event, None)
        self.assertEqual(resp["statusCode"], 400)
        body = __import__("json").loads(resp["body"])
        self.assertIn("mobile", [d["field"] for d in body["details"]])

    def test_intl_mobile_accepted(self):
        fake = FakeTable()
        handler._table = fake
        event = make_event({**VALID, "mobile": "+27 82 555 9999"})
        resp = handler.handler(event, None)
        self.assertEqual(resp["statusCode"], 201)
        body = __import__("json").loads(resp["body"])
        self.assertEqual(body["mobile"], "+27825559999")

    def test_duplicate_email_conflict(self):
        existing = {
            "pk": "PARTICIPANT#MSRI-004120",
            "sk": "2026-01-01T00:00:00.000",
            "participant_id": "MSRI-004120",
            "email": "thandi@example.co.za",
            "email_normalized": "thandi@example.co.za",
            "gsi1pk": "EMAIL#thandi@example.co.za",
            "idempotency_key": "old-key",
        }
        fake = FakeTable()
        fake.seed_email(existing)
        handler._table = fake
        resp = handler.handler(make_event(VALID), None)
        self.assertEqual(resp["statusCode"], 409)
        body = __import__("json").loads(resp["body"])
        self.assertEqual(body["participant_id"], "MSRI-004120")

    def test_idempotent_retry_returns_original(self):
        existing = {
            "pk": "PARTICIPANT#MSRI-004121",
            "sk": "x",
            "participant_id": "MSRI-004121",
            "email": "sipho@example.co.za",
            "email_normalized": "sipho@example.co.za",
            "gsi1pk": "EMAIL#sipho@example.co.za",
            "idempotency_key": "key-1",
            "amount_due": Decimal("200"),
            "programme_code": "SP-MASTER",
            "cohort_code": "2026-S1",
            "pricing_plan": "monthly",
            "instalments": 3,
            "status": "pending_payment",
        }
        fake = FakeTable()
        fake.seed_email(existing)
        handler._table = fake
        headers = {"Content-Type": "application/json", "Idempotency-Key": "key-1"}
        resp = handler.handler(
            make_event(
                {
                    "first_name": "Sipho",
                    "surname": "Dlamini",
                    "email": "sipho@example.co.za",
                    "mobile": "0731234567",
                    "pricing_plan": "monthly",
                },
                headers=headers,
            ),
            None,
        )
        self.assertEqual(resp["statusCode"], 200)
        body = __import__("json").loads(resp["body"])
        self.assertEqual(body["participant_id"], "MSRI-004121")

    def test_wrong_supplied_amount_rejected(self):
        handler._table = FakeTable()
        event = make_event({**VALID, "amount_due": 600})
        resp = handler.handler(event, None)
        self.assertEqual(resp["statusCode"], 400)
        body = __import__("json").loads(resp["body"])
        self.assertIn("amount_due", [d["field"] for d in body["details"]])

    def test_id_collision_retries_new_id(self):
        fake = FakeTable(fail_conditionally=False)
        handler._table = fake
        resp = handler.handler(make_event(VALID), None)
        self.assertEqual(resp["statusCode"], 201)

    def test_function_url_root_post(self):
        fake = FakeTable()
        handler._table = fake
        resp = handler.handler(make_event(VALID, path="/"), None)
        self.assertEqual(resp["statusCode"], 201)


if __name__ == "__main__":
    unittest.main()
