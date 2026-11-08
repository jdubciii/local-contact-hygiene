from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
REQUIRED_COLUMNS = ("record_id", "first_name", "last_name", "company", "email", "phone")
GENERATED_COLUMNS = (
    "normalized_first_name",
    "normalized_last_name",
    "normalized_company",
    "normalized_email",
    "normalized_phone",
    "email_group",
    "phone_group",
    "review_status",
    "review_reason",
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_CHARS_RE = re.compile(r"^\+?[0-9\s().-]+$")


def normalize_text(value: str | None) -> str:
    """Trim and collapse whitespace without changing name/company casing."""
    return " ".join((value or "").split())


def normalize_email(value: str | None) -> str:
    return normalize_text(value).lower()


def looks_like_email_syntax(value: str) -> bool:
    return bool(EMAIL_RE.fullmatch(value))


def normalize_us_phone(value: str | None) -> str:
    """Keep only 10 digits, or 11 digits beginning with 1, in a simple format."""
    text = normalize_text(value)
    if not text or not PHONE_CHARS_RE.fullmatch(text):
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def _is_formula_like(value: str) -> bool:
    trimmed = value.lstrip(" \t\r\n")
    return value.startswith(("\t", "\r", "\n")) or bool(trimmed and trimmed[0] in "=+-@")


def _spreadsheet_safe(value: Any) -> tuple[str, bool]:
    text = "" if value is None else str(value)
    if _is_formula_like(text):
        return "'" + text, True
    return text, False


def _read_input(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError("Input CSV is not a readable file")

    try:
        handle = path.open("r", newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise OSError("Input CSV could not be opened") from exc

    with handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if not headers:
            raise ValueError("Input CSV must have a header row")
        if any(header is None or not header.strip() for header in headers):
            raise ValueError("Input CSV contains a blank column header")
        if len(headers) != len(set(headers)):
            raise ValueError("Input CSV contains duplicate column headers")
        if any(_is_formula_like(header) for header in headers):
            raise ValueError("Input CSV contains a formula-like column header")
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            raise ValueError("Input CSV is missing required columns: " + ", ".join(missing))
        collisions = [column for column in GENERATED_COLUMNS if column in headers]
        if collisions:
            raise ValueError("Input CSV uses reserved output columns: " + ", ".join(collisions))

        rows: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for row_number, raw in enumerate(reader, start=2):
            if raw is None or None in raw:
                raise ValueError(f"Input CSV has extra cells on row {row_number}")
            row = {header: (raw.get(header) or "") for header in headers}
            record_id = normalize_text(row["record_id"])
            if not record_id:
                raise ValueError(f"record_id is blank on row {row_number}")
            key = record_id.casefold()
            if key in seen_ids:
                raise ValueError(f"record_id is duplicated on row {row_number}")
            seen_ids.add(key)
            rows.append(row)
    return list(headers), rows


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> int:
    escaped_count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            safe_row: dict[str, str] = {}
            for header in headers:
                safe_row[header], escaped = _spreadsheet_safe(row.get(header, ""))
                escaped_count += int(escaped)
            writer.writerow(safe_row)
    return escaped_count


def process_csv(input_csv: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Process a CSV locally and create review-only outputs without overwriting."""
    input_path = Path(input_csv)
    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError("Output directory already exists; choose a new directory")

    source_columns, source_rows = _read_input(input_path)
    prepared: list[dict[str, Any]] = []
    email_rows: dict[str, list[int]] = defaultdict(list)
    phone_rows: dict[str, list[int]] = defaultdict(list)

    for index, source in enumerate(source_rows):
        item: dict[str, Any] = dict(source)
        item["normalized_first_name"] = normalize_text(source["first_name"])
        item["normalized_last_name"] = normalize_text(source["last_name"])
        item["normalized_company"] = normalize_text(source["company"])
        item["normalized_email"] = normalize_email(source["email"])
        item["normalized_phone"] = normalize_us_phone(source["phone"])
        if looks_like_email_syntax(item["normalized_email"]):
            email_rows[item["normalized_email"]].append(index)
        if item["normalized_phone"]:
            phone_rows[item["normalized_phone"]].append(index)
        prepared.append(item)

    repeated_email = {key: indexes for key, indexes in sorted(email_rows.items()) if len(indexes) > 1}
    repeated_phone = {key: indexes for key, indexes in sorted(phone_rows.items()) if len(indexes) > 1}
    email_group_for: dict[int, str] = {}
    email_group_identity: dict[str, bool] = {}
    for number, (email, indexes) in enumerate(repeated_email.items(), start=1):
        group_id = f"E{number:03d}"
        identities = {
            tuple(normalize_text(prepared[index][field]).casefold() for field in ("first_name", "last_name", "company"))
            for index in indexes
        }
        email_group_identity[group_id] = len(identities) == 1
        for index in indexes:
            email_group_for[index] = group_id

    phone_group_for: dict[int, str] = {}
    phone_only_groups = 0
    for number, (phone, indexes) in enumerate(repeated_phone.items(), start=1):
        group_id = f"P{number:03d}"
        if any(index not in email_group_for for index in indexes):
            phone_only_groups += 1
        for index in indexes:
            phone_group_for[index] = group_id

    cleaned_rows: list[dict[str, Any]] = []
    review_log: list[dict[str, str]] = []
    for index, item in enumerate(prepared):
        reasons: list[str] = []
        email = item["normalized_email"]
        phone = item["normalized_phone"]
        email_group = email_group_for.get(index, "")
        phone_group = phone_group_for.get(index, "")

        if not normalize_text(item["email"]):
            reasons.append("Email missing; do not infer")
        elif not looks_like_email_syntax(email):
            reasons.append("Email syntax not recognized; do not correct or verify automatically")
        if not normalize_text(item["company"]):
            reasons.append("Company missing; do not infer")
        if not normalize_text(item["phone"]):
            reasons.append("Phone missing; do not infer")
        elif not phone:
            reasons.append("Phone format not recognized; verify manually")

        if email_group:
            if email_group_identity[email_group]:
                reasons.append(f"Repeated normalized email in {email_group}; possible duplicate, preserve both rows pending owner review")
            else:
                reasons.append(f"Repeated email in {email_group} with differing identity fields; identity conflict, do not merge")
        if phone_group and not email_group:
            reasons.append(f"Phone also appears in {phone_group}; phone-only match is not sufficient to merge")

        item["email_group"] = email_group
        item["phone_group"] = phone_group
        item["review_status"] = "FLAGGED_FOR_REVIEW" if reasons else "NO_FLAGS_DETECTED"
        item["review_reason"] = "; ".join(reasons) if reasons else "No deterministic issue detected; human review is still required"
        cleaned_rows.append(item)
        for reason in reasons:
            review_log.append({
                "record_id": normalize_text(item["record_id"]),
                "issue": reason,
                "action": "Keep source row; owner must review before any import, merge, deletion, or enrichment",
            })

    same_identity_groups = sum(email_group_identity.values())
    conflicting_groups = len(email_group_identity) - same_identity_groups
    cleaned_columns = source_columns + list(GENERATED_COLUMNS)
    log_columns = ["record_id", "issue", "action"]

    summary: dict[str, Any] = {
        "version": VERSION,
        "records_in": len(source_rows),
        "records_preserved": len(cleaned_rows),
        "rows_deleted_or_auto_merged": 0,
        "repeated_email_groups": len(repeated_email),
        "same_identity_email_groups": same_identity_groups,
        "conflicting_identity_email_groups": conflicting_groups,
        "repeated_phone_groups": len(repeated_phone),
        "phone_only_match_groups": phone_only_groups,
        "review_log_rows": len(review_log),
        "spreadsheet_cells_escaped": 0,
        "scope_limit": "local format normalization and deterministic review flags only; no live verification, CRM access, enrichment, or automatic merge",
    }

    parent = destination.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".contact-hygiene-", dir=parent) as temporary:
            staging = Path(temporary) / "output"
            staging.mkdir()
            escaped = _write_csv(staging / "cleaned_with_review.csv", cleaned_columns, cleaned_rows)
            escaped += _write_csv(staging / "review_log.csv", log_columns, review_log)
            summary["spreadsheet_cells_escaped"] = escaped
            (staging / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            if destination.exists():
                raise FileExistsError("Output directory already exists; choose a new directory")
            staging.rename(destination)
    except FileExistsError:
        raise
    except OSError as exc:
        raise OSError("Output files could not be written; check the destination and available disk space") from exc

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review a contact CSV locally. The tool never merges or deletes records."
    )
    parser.add_argument("input_csv", help="UTF-8 CSV with the required contact columns")
    parser.add_argument("--output-dir", help="new output directory; defaults to <input-name>_hygiene")
    args = parser.parse_args(argv)

    input_path = Path(args.input_csv)
    destination = Path(args.output_dir) if args.output_dir else input_path.with_name(f"{input_path.stem}_hygiene")
    try:
        summary = process_csv(input_path, destination)
    except FileNotFoundError:
        print("Error: input CSV could not be found or opened.", file=sys.stderr)
        return 2
    except UnicodeError:
        print("Error: input must be a UTF-8 CSV file.", file=sys.stderr)
        return 2
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (OSError, csv.Error):
        print("Error: unable to read or write the files; check the paths, permissions, and disk space.", file=sys.stderr)
        return 2

    print(
        f"Reviewed {summary['records_in']} rows; preserved all rows; "
        f"created {summary['review_log_rows']} review flags."
    )
    print(f"Output directory: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
