# Local Contact Hygiene Review

A small, offline Python utility that adds deterministic review flags to a UTF-8 contact CSV. It keeps every row and source column, never merges or deletes records, and makes no network requests.

## Synthetic fixture

The included 20-row sample is fictional. Completed email addresses use the reserved `.invalid` domain (including its subdomains), and phone examples use NANPA's reserved fictitious 555-0100 through 555-0199 range. A few intentionally malformed values exercise review flags.

## Requirements and run

- Python 3.10 or newer. Standard library only. No `pip install`, account, API key, server, or paid service.
- Input must have these exact column headers: `record_id`, `first_name`, `last_name`, `company`, `email`, `phone`. `record_id` values must be nonblank and unique. Other input columns are preserved. Do not use input columns named like the generated fields listed below.
- The source file is never modified. The output directory must not already exist, to prevent accidental overwrite.

Try the included synthetic example:

```powershell
py .\contact_hygiene.py .\sample_contacts.csv
```

On macOS or Linux:

```sh
python3 ./contact_hygiene.py ./sample_contacts.csv
```

For your own file, choose a new output directory:

```sh
python3 ./contact_hygiene.py ./contacts.csv --output-dir ./contacts-review-output
```

The utility reads and writes files on the machine where it runs. It has no telemetry, account login, web request, API call, or remote storage. The output contains contact data, so keep both input and output in a location you control. Do not upload contact files, screenshots, or row values to public issues, chat, or an AI service.

## What it does

- Trims and collapses whitespace in first name, last name, and company fields while preserving letter case. Original fields remain beside the suggestions.
- Trims and lowercases email text, then applies a basic syntax check. This does not test whether an address exists or can receive mail.
- Normalizes phone formatting only when the value contains permitted punctuation and exactly 10 digits, or 11 digits beginning with `1`. It is a format check, not proof that a number is assigned or reachable.
- Groups exact normalized email repeats. It distinguishes rows with matching first name, last name, and company from groups with differing identity fields, and flags both for human review.
- Flags repeated phone values for review when the match is not already represented by a repeated-email group. A phone match is never treated as identity proof.
- Flags missing email, company, or phone values and unrecognized email/phone formats.
- Preserves all rows and all original columns. It does not delete, merge, enrich, or verify contacts.

## Output files

The program creates a new output directory containing:

- `cleaned_with_review.csv`: every source row and column, plus `normalized_first_name`, `normalized_last_name`, `normalized_company`, `normalized_email`, `normalized_phone`, `email_group`, `phone_group`, `review_status`, and `review_reason`.
- `review_log.csv`: one row for each flagged condition, identified by `record_id`.
- `summary.json`: aggregate counts and scope notes only. It does not include contact values or input paths.

`NO_FLAGS_DETECTED` means only that these deterministic checks found no listed issue. It does not mean a record is accurate, complete, current, lawful to use, or ready to import. Review every row yourself before any CRM import or other action.

For spreadsheet safety, output cells whose first non-space character could start a formula (`=`, `+`, `-`, or `@`) are prefixed with an apostrophe. The original input remains unchanged. The output is a review artifact, not a drop-in CRM import file.

## Optional feedback if this candidate is publicly released

A user may voluntarily open a GitHub issue with only the result (ran successfully / attempted and failed), operating system, Python version, and a broad input-row count band. Never include names, companies, email addresses, phone numbers, CSV files, or screenshots containing contact records. Feedback requires an existing GitHub account; nobody should create one just to report usage. The utility itself sends no usage data.

## Limits

- No CRM-specific field mapping, import, merge, delete, enrichment, fuzzy name matching, address checks, consent checks, or live contact verification.
- Email checking is a simple syntax pattern only. Phone handling is limited to 10-digit US-style formatting, optionally preceded by country code `1`; it does not validate number assignment or reachability.
- Names and company names are not standardized beyond whitespace. Similar spellings, nicknames, shared inboxes, and household/business relationships require human judgment.
- A repeated email or phone can be legitimate. A review flag is not an instruction to merge.
- Input headers must use the exact required names. Duplicate or blank `record_id` values are rejected rather than guessed.

## Tests

Run the offline tests from this directory:

```sh
python3 -m unittest discover -s tests -v
```

Tests use only temporary files and synthetic records. No real contact list is included.

## License

MIT License. Copyright (c) 2026 Jack W Cone III. See `LICENSE` for the full terms.
