"""Self Mastery Programme — Registration API (AWS Lambda)

Receives programme registrations from the public Self Mastery registration
site, validates them, applies the programme code / cohort code in the
background, auto-assigns a participant ID and stores the registration in
DynamoDB.

Records are shaped so they can be exported directly into the PoP / payments
system CSV format:

    participant_id,first_name,surname,email,mobile,programme_code,cohort_code,amount_due

Works with API Gateway (HTTP API v1 + v2 payloads) and Lambda Function URLs.
Deploy with the included ``template.yaml`` (AWS SAM).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from decimal import Decimal

try:  # pragma: no cover - boto3 is always present in the Lambda runtime
    import boto3
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import ClientError
except ImportError:  # allows unit tests to run without AWS dependencies
    boto3 = None
    Key = None
    ClientError = Exception

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# --------------------------------------------------------------------------
# Configuration (overridable via environment variables / SAM parameters)
# --------------------------------------------------------------------------
PROGRAMME_NAME = os.environ.get("PROGRAMME_NAME", "Self Mastery Programme")
PROGRAMME_CODE = os.environ.get("PROGRAMME_CODE", "SP-MASTER")
COHORT_CODE = os.environ.get("COHORT_CODE", "2026-S1")
PARTICIPANT_ID_PREFIX = os.environ.get("PARTICIPANT_ID_PREFIX", "MSRI")
TABLE_NAME = os.environ.get("TABLE_NAME", "sm-registrations")
EMAIL_INDEX_NAME = os.environ.get("EMAIL_INDEX_NAME", "gsi1")
CURRENCY = os.environ.get("CURRENCY", "ZAR")

PRICING = {
    "once_off": Decimal(os.environ.get("PRICE_ONCE_OFF", "500")),
    "monthly": Decimal(os.environ.get("PRICE_MONTHLY", "200")),
}
MONTHLY_INSTALMENTS = int(os.environ.get("MONTHLY_INSTALMENTS", "3"))

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# Letters, spaces, hyphens, apostrophes and periods (no digits/symbols).
NAME_RE = re.compile(r"^[^\d!@#$%^&*()_+=\[\]{};:\"\\|<>/?~`]*$")
FIELD_LIMITS = {"first_name": (2, 80), "surname": (2, 80)}

_table = None


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _get_table():
    """Lazily create the DynamoDB table resource."""
    global _table
    if _table is None:
        if boto3 is None:
            raise RuntimeError("boto3 is not available")
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _request_info(event):
    """Return (method, path) for API Gateway v1/v2 and Function URL events."""
    req = event.get("requestContext", {})
    http = req.get("http", {}) or {}
    method = http.get("method") or event.get("httpMethod") or ""
    path = http.get("path") or event.get("path") or req.get("path", "") or ""
    return method.upper(), path.lower()


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "isBase64Encoded": False,
        "body": json.dumps(payload, default=str),
    }


def _parse_body(event):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8", "replace")
        except Exception:
            return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _validate_name(value, field, errors):
    value = _clean_text(value)
    low, high = FIELD_LIMITS[field]
    if len(value) < low:
        errors.append(
            {"field": field, "message": f"Must be at least {low} characters."}
        )
        return ""
    if len(value) > high:
        errors.append(
            {"field": field, "message": f"Must be at most {high} characters."}
        )
        return ""
    if not NAME_RE.match(value):
        errors.append(
            {"field": field, "message": "Letters, spaces, hyphens and apostrophes only."}
        )
        return ""
    return value


def _validate_email(value, errors):
    value = _clean_text(value).lower()
    if not EMAIL_RE.match(value):
        errors.append({"field": "email", "message": "Enter a valid email address."})
        return ""
    return value


def normalize_mobile(raw):
    """Normalise a South African mobile number to +27XXXXXXXXX.

    Accepts formats such as 0721234567, +27 72 123 4567, 27721234567.
    Other international formats (+ followed by 7-15 digits) are kept as-is.
    Raises ValueError when the number cannot be interpreted.
    """
    digits = re.sub(r"[^\d+]", "", _clean_text(raw))
    if digits.startswith("+"):
        intl = "+" + re.sub(r"\D", "", digits[1:])
    elif digits.startswith("27") and len(digits) == 11:
        intl = "+" + digits
    elif digits.startswith("0") and len(digits) == 10:
        intl = "+27" + digits[1:]
    else:
        intl = "+" + re.sub(r"\D", "", digits)
    rest = intl[1:]
    if not rest.isdigit() or not (7 <= len(rest) <= 15):
        raise ValueError("Enter a valid mobile number.")
    if intl.startswith("+27") and not re.match(r"^\+27[1-9]\d{8}$", intl):
        raise ValueError("Enter a valid South African mobile number (e.g. 072 123 4567).")
    return intl


def _resolve_amount(plan):
    """Amount currently due for the chosen payment plan (in ZAR)."""
    return PRICING[plan]


def _new_participant_id(seed):
    digest = hashlib.sha256(
        f"{PARTICIPANT_ID_PREFIX}|{seed}|{time.time_ns()}|{os.urandom(8).hex()}".encode()
    ).hexdigest()
    number = int(digest[:8], 16) % 1_000_000
    return f"{PARTICIPANT_ID_PREFIX}-{number:06d}"


# --------------------------------------------------------------------------
# Registration flow
# --------------------------------------------------------------------------
def _find_by_email(table, email_norm):
    try:
        resp = table.query(
            IndexName=EMAIL_INDEX_NAME,
            KeyConditionExpression=Key("gsi1pk").eq(f"EMAIL#{email_norm}"),
        )
        return (resp.get("Items") or [None])[0]
    except ClientError:
        logger.exception("Email lookup failed")
        return None


def _create_registration(event):
    data = _parse_body(event)

    errors = []
    first_name = _validate_name(data.get("first_name"), "first_name", errors)
    surname = _validate_name(data.get("surname"), "surname", errors)
    email = _validate_email(data.get("email"), errors)

    mobile_raw = _clean_text(data.get("mobile"))
    try:
        mobile = normalize_mobile(mobile_raw)
    except ValueError as exc:
        mobile = ""
        errors.append({"field": "mobile", "message": str(exc)})

    plan = str(data.get("pricing_plan", data.get("plan", ""))).strip().lower()
    plan = plan.replace("-", "_").replace(" ", "_")
    if plan not in PRICING:
        errors.append(
            {
                "field": "pricing_plan",
                "message": "Choose a payment plan: once-off or monthly.",
            }
        )

    if errors:
        return _response(400, {"error": "validation_error", "details": errors})

    amount_due = _resolve_amount(plan)

    # If the caller insists on an amount, it must match the plan's price.
    supplied = data.get("amount_due")
    if supplied not in (None, ""):
        try:
            if Decimal(str(supplied)) != amount_due:
                return _response(
                    400,
                    {
                        "error": "validation_error",
                        "details": [
                            {
                                "field": "amount_due",
                                "message": (
                                    f"Amount for the {plan.replace('_', '-')} plan is "
                                    f"R{amount_due:g}."
                                ),
                            }
                        ],
                    },
                )
        except Exception:
            return _response(
                400,
                {
                    "error": "validation_error",
                    "details": [{"field": "amount_due", "message": "Invalid amount."}],
                },
            )

    email_norm = email
    table = _get_table()

    headers = event.get("headers") or {}
    lower = {str(k).lower(): v for k, v in headers.items()}
    idem_key = _clean_text(lower.get("idempotency-key"))

    existing = _find_by_email(table, email_norm)
    if existing:
        if idem_key and existing.get("idempotency_key") == idem_key:
            # Retry of the same submission — return the original result.
            return _response(200, _public_view(existing))
        return _response(
            409,
            {
                "error": "duplicate_registration",
                "participant_id": existing.get("participant_id"),
                "message": (
                    "This email address is already registered for the "
                    f"{PROGRAMME_NAME}."
                ),
            },
        )

    now = datetime.now(timezone.utc)
    item = {
        "pk": "PENDING",
        "sk": now.isoformat(timespec="milliseconds"),
        "participant_id": "",
        "first_name": first_name,
        "surname": surname,
        "email": email,
        "email_normalized": email_norm,
        "mobile": mobile,
        "mobile_raw": mobile_raw,
        "programme": PROGRAMME_NAME,
        "programme_code": PROGRAMME_CODE,
        "cohort_code": COHORT_CODE,
        "amount_due": amount_due,
        "currency": CURRENCY,
        "pricing_plan": plan,
        "instalments": 1 if plan == "once_off" else MONTHLY_INSTALMENTS,
        "status": "pending_payment",
        "idempotency_key": idem_key or None,
        "created_at": now.isoformat(timespec="seconds"),
        "created_at_epoch": now.timestamp(),
        "gsi1pk": f"EMAIL#{email_norm}",
        "gsi1sk": now.isoformat(timespec="milliseconds"),
    }

    last_error = None
    for _ in range(6):
        participant_id = _new_participant_id(email_norm)
        item["participant_id"] = participant_id
        item["pk"] = f"PARTICIPANT#{participant_id}"
        item["reference"] = participant_id
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
            logger.info("Registered %s (%s %s) plan=%s", participant_id, first_name, surname, plan)
            return _response(201, _public_view(item))
        except ClientError as exc:  # pragma: no cover - depends on botocore
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code == "ConditionalCheckFailedException":
                last_error = exc
                continue  # extremely unlikely ID collision — draw a new one
            logger.exception("DynamoDB write failed")
            return _response(503, {"error": "storage_unavailable"})
        except Exception:  # unit-test fake tables raise bare collisions
            last_error = None
            break

    logger.error("Could not allocate a participant ID: %s", last_error)
    return _response(500, {"error": "id_allocation_failed"})


def _public_view(item):
    return {
        "status": item.get("status", "pending_payment"),
        "participant_id": item.get("participant_id"),
        "reference": item.get("reference", item.get("participant_id")),
        "first_name": item.get("first_name"),
        "surname": item.get("surname"),
        "email": item.get("email"),
        "mobile": item.get("mobile"),
        "programme": item.get("programme"),
        "programme_code": item.get("programme_code"),
        "cohort_code": item.get("cohort_code"),
        "amount_due": float(item.get("amount_due", 0)),
        "currency": item.get("currency", CURRENCY),
        "pricing_plan": item.get("pricing_plan"),
        "instalments": item.get("instalments", 1),
        "created_at": item.get("created_at"),
    }


# --------------------------------------------------------------------------
# Lambda entry point
# --------------------------------------------------------------------------
def handler(event, context):
    method, path = _request_info(event)

    if method == "OPTIONS":
        return _response(204, {})

    if method == "GET" and (path.endswith("/health") or path in ("", "/")):
        return _response(
            200,
            {
                "ok": True,
                "service": "self-mastery-registration",
                "programme": PROGRAMME_NAME,
                "programme_code": PROGRAMME_CODE,
                "cohort_code": COHORT_CODE,
            },
        )

    if method == "POST" and "registrations" in path:
        return _create_registration(event)

    if method == "POST" and path in ("", "/"):
        # Function URL posts arrive at "/" — treat them as registrations.
        return _create_registration(event)

    return _response(404, {"error": "not_found"})
