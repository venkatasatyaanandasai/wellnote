import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


TEST_DATABASE = tempfile.TemporaryDirectory()
os.environ["PATIENTS_DB_PATH"] = str(Path(TEST_DATABASE.name) / "test.sqlite3")

from fastapi.testclient import TestClient  # noqa: E402

from main import app, parse_dob  # noqa: E402


class PatientAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.delete("/api/patients/1")
        for patient in self.client.get("/api/patients").json():
            self.client.delete(f"/api/patients/{patient['id']}")

    def valid_record(self) -> dict[str, object]:
        return {
            "full_name": "Robyn Pears",
            "dob": "28.01.1960",
            "email": "robyn@gmail.com",
            "glucose": 232,
            "haemoglobin": 13.5,
            "cholesterol": 180,
        }

    def test_date_validation_accepts_table_format_and_rejects_bad_or_future_dates(self) -> None:
        self.assertEqual(parse_dob("28.01.1960"), "1960-01-28")
        self.assertEqual(parse_dob("28/01/1960"), "1960-01-28")
        with self.assertRaises(ValueError):
            parse_dob("31.11.2001")
        future = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        with self.assertRaises(ValueError):
            parse_dob(future)
        with self.assertRaises(ValueError):
            parse_dob("1960-01-28")

    def test_crud_persists_and_validates_email(self) -> None:
        response = self.client.post("/api/patients", json=self.valid_record())
        self.assertEqual(response.status_code, 201)
        patient = response.json()
        self.assertEqual(patient["dob"], "28/01/1960")
        self.assertIn("not a diagnosis", patient["remarks"])
        self.assertEqual(patient["remark_source"], "Local screening note")

        changed = self.valid_record()
        changed["email"] = "gokul@infocare.com"
        response = self.client.put(f"/api/patients/{patient['id']}", json=changed)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "gokul@infocare.com")
        self.assertEqual(self.client.get("/api/patients").json()[0]["email"], "gokul@infocare.com")

        self.assertEqual(self.client.delete(f"/api/patients/{patient['id']}").status_code, 204)
        self.assertEqual(self.client.get("/api/patients").json(), [])

    def test_invalid_email_and_measurements_are_rejected(self) -> None:
        for email in ("hunter@gmail", "Kris.wu.gmail.com"):
            record = self.valid_record()
            record["email"] = email
            self.assertEqual(self.client.post("/api/patients", json=record).status_code, 422)

        record = self.valid_record()
        record["glucose"] = "not numeric"
        self.assertEqual(self.client.post("/api/patients", json=record).status_code, 422)

    def test_batch_import_keeps_valid_rows_and_reports_invalid_rows(self) -> None:
        invalid_email = self.valid_record()
        invalid_email["email"] = "hunter@gmail"
        impossible_date = self.valid_record()
        impossible_date["dob"] = "31.11.2001"
        future_date = self.valid_record()
        future_date["dob"] = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")

        response = self.client.post(
            "/api/patients/import",
            json={"records": [self.valid_record(), invalid_email, impossible_date, future_date]},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual([item["row"] for item in result["rejected"]], [2, 3, 4])
        self.assertEqual(len(self.client.get("/api/patients").json()), 1)

    def test_external_ai_request_contains_measurements_not_personal_information(self) -> None:
        import main

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"choices":[{"message":{"content":"Informational result."}}]}'

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch.object(main, "urlopen", return_value=FakeResponse()) as mock_urlopen:
                record = self.valid_record()
                response = self.client.post("/api/patients", json=record)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["remark_source"], "External AI")
        request = mock_urlopen.call_args.args[0]
        self.assertNotIn("Robyn", request.data.decode("utf-8"))
        self.assertNotIn("robyn@gmail.com", request.data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
