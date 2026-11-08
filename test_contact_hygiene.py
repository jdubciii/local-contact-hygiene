import csv
import json
import tempfile
import unittest
from pathlib import Path

from contact_hygiene import process_csv


HEADER = ["record_id", "first_name", "last_name", "company", "email", "phone", "extra_note"]


class ContactHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.input_path = self.root / "contacts.csv"
        self.output_dir = self.root / "review-output"

    def tearDown(self):
        self.temp.cleanup()

    def write_rows(self, rows, header=HEADER):
        with self.input_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

    def fixture_rows(self):
        return [
            {"record_id": "R1", "first_name": "  Test", "last_name": " Person ", "company": " Acme LLC ", "email": " User@Example.invalid ", "phone": "(480) 555-0101", "extra_note": "source-one"},
            {"record_id": "R2", "first_name": "Test", "last_name": "Person", "company": "Acme LLC", "email": "user@example.invalid", "phone": "4805550101", "extra_note": "source-two"},
            {"record_id": "R3", "first_name": "Other", "last_name": "Person", "company": "Other LLC", "email": "other@example.invalid", "phone": "602.555.0103", "extra_note": "identity-conflict"},
            {"record_id": "R4", "first_name": "Phone", "last_name": "Only", "company": "Example Org", "email": "", "phone": "1 (480) 555-0101", "extra_note": "phone-only"},
            {"record_id": "R5", "first_name": "Different", "last_name": "Person", "company": "Different LLC", "email": "OTHER@example.invalid", "phone": "6025550103", "extra_note": "identity-conflict-two"},
        ]

    def test_processes_without_deleting_or_merging_and_preserves_extra_columns(self):
        rows = self.fixture_rows()
        self.write_rows(rows)
        summary = process_csv(self.input_path, self.output_dir)

        self.assertEqual(summary["records_in"], 5)
        self.assertEqual(summary["records_preserved"], 5)
        self.assertEqual(summary["rows_deleted_or_auto_merged"], 0)
        with (self.output_dir / "cleaned_with_review.csv").open(newline="", encoding="utf-8-sig") as handle:
            output = list(csv.DictReader(handle))
        self.assertEqual(len(output), 5)
        self.assertIn("extra_note", output[0])
        self.assertEqual(output[0]["extra_note"], "source-one")

    def test_normalization_preserves_name_and_company_case(self):
        self.write_rows(self.fixture_rows())
        process_csv(self.input_path, self.output_dir)
        with (self.output_dir / "cleaned_with_review.csv").open(newline="", encoding="utf-8-sig") as handle:
            output = list(csv.DictReader(handle))
        self.assertEqual(output[0]["normalized_first_name"], "Test")
        self.assertEqual(output[0]["normalized_company"], "Acme LLC")
        self.assertEqual(output[0]["normalized_email"], "user@example.invalid")
        self.assertEqual(output[0]["normalized_phone"], "4805550101")

    def test_duplicate_email_conflict_and_phone_only_are_review_flags(self):
        self.write_rows(self.fixture_rows())
        summary = process_csv(self.input_path, self.output_dir)
        with (self.output_dir / "cleaned_with_review.csv").open(newline="", encoding="utf-8-sig") as handle:
            output = {row["record_id"]: row for row in csv.DictReader(handle)}
        self.assertEqual(output["R1"]["review_status"], "FLAGGED_FOR_REVIEW")
        self.assertIn("possible duplicate", output["R1"]["review_reason"].lower())
        self.assertIn("identity conflict", output["R3"]["review_reason"].lower())
        self.assertIn("phone-only", output["R4"]["review_reason"].lower())
        self.assertEqual(summary["repeated_email_groups"], 2)
        self.assertEqual(summary["same_identity_email_groups"], 1)
        self.assertEqual(summary["conflicting_identity_email_groups"], 1)
        self.assertEqual(summary["phone_only_match_groups"], 1)

    def test_formula_like_cells_are_escaped_in_spreadsheet_outputs(self):
        rows = self.fixture_rows()
        rows[0]["company"] = "=HYPERLINK(\"https://example.invalid\",\"click\")"
        rows[0]["extra_note"] = "  @SUM(1,1)"
        self.write_rows(rows)
        summary = process_csv(self.input_path, self.output_dir)
        with (self.output_dir / "cleaned_with_review.csv").open(newline="", encoding="utf-8-sig") as handle:
            output = list(csv.DictReader(handle))
        self.assertTrue(output[0]["company"].startswith("'="))
        self.assertTrue(output[0]["extra_note"].startswith("'"))
        self.assertGreaterEqual(summary["spreadsheet_cells_escaped"], 2)
        self.assertNotIn("HYPERLINK", json.dumps(summary))

    def test_missing_required_header_fails_before_creating_output(self):
        self.input_path.write_text("record_id,email\nR1,user@example.invalid\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "required columns"):
            process_csv(self.input_path, self.output_dir)
        self.assertFalse(self.output_dir.exists())

    def test_duplicate_or_blank_record_id_fails_before_creating_output(self):
        rows = self.fixture_rows()
        rows[1]["record_id"] = "R1"
        self.write_rows(rows)
        with self.assertRaisesRegex(ValueError, "record_id"):
            process_csv(self.input_path, self.output_dir)
        self.assertFalse(self.output_dir.exists())

    def test_existing_output_directory_is_never_overwritten(self):
        self.write_rows(self.fixture_rows())
        self.output_dir.mkdir()
        sentinel = self.output_dir / "keep.txt"
        sentinel.write_text("do not overwrite", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            process_csv(self.input_path, self.output_dir)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "do not overwrite")

    def test_summary_contains_counts_not_contact_values(self):
        self.write_rows(self.fixture_rows())
        summary = process_csv(self.input_path, self.output_dir)
        summary_text = json.dumps(summary)
        self.assertNotIn("user@example.invalid", summary_text)
        self.assertNotIn("4805550101", summary_text)
        self.assertTrue((self.output_dir / "summary.json").is_file())


if __name__ == "__main__":
    unittest.main()
