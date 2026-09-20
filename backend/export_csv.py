#!/usr/bin/env python3
"""Export Self Mastery registrations from DynamoDB to the PoP system CSV format.

Produces exactly:

    participant_id,first_name,surname,email,mobile,programme_code,cohort_code,amount_due

Usage:
    python export_csv.py --output registrations.csv
    python export_csv.py --table sm-registrations-prod --region af-south-1
    python export_csv.py --start-after MSRI-004100        # incremental export
"""

from __future__ import annotations

import argparse
import csv
import sys

import boto3

COLUMNS = [
    "participant_id",
    "first_name",
    "surname",
    "email",
    "mobile",
    "programme_code",
    "cohort_code",
    "amount_due",
]


def _amount(value):
    """Format the amount without trailing zeros: 200 not 200.0."""
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default="sm-registrations-prod")
    parser.add_argument("--region", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--output", default="registrations.csv")
    parser.add_argument(
        "--start-after",
        default=None,
        help="Only export participant IDs greater than this (for incremental exports).",
    )
    args = parser.parse_args(argv)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    table = session.resource("dynamodb").Table(args.table)

    rows = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        rows.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs = {"ExclusiveStartKey": resp["LastEvaluatedKey"]}

    if args.start_after:
        rows = [r for r in rows if r.get("participant_id", "") > args.start_after]

    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("participant_id") or ""))

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.get("participant_id", ""),
                    row.get("first_name", ""),
                    row.get("surname", ""),
                    row.get("email", ""),
                    row.get("mobile", ""),
                    row.get("programme_code", ""),
                    row.get("cohort_code", ""),
                    _amount(row.get("amount_due", "")),
                ]
            )

    print(f"Exported {len(rows)} registrations -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
