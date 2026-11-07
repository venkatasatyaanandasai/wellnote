import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
DATABASE_PATH = Path(os.environ.get("PATIENTS_DB_PATH", ROOT_DIR / "patients.db"))
DATE_PATTERN = re.compile(r"^(\d{2})[./](\d{2})[./](\d{4})$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PatientInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=120)
    dob: str
    email: str = Field(min_length=3, max_length=254)
    glucose: float
    haemoglobin: float
    cholesterol: float

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Full name is required.")
        return value

    @field_validator("dob")
    @classmethod
    def validate_dob(cls, value: str) -> str:
        return parse_dob(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Enter a valid email address, such as name@example.com.")
        return value

    @field_validator("glucose", "haemoglobin", "cholesterol")
    @classmethod
    def validate_measurement(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Enter a numeric value greater than zero.")
        return value


class ImportRequest(BaseModel):
    records: list[dict[str, Any]] = Field(max_length=100)


def parse_dob(value: str) -> str:
    match = DATE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError("Use DD/MM/YYYY (DD.MM.YYYY is also accepted for the supplied test data).")
    day, month, year = (int(part) for part in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError as exc:
        raise ValueError("Enter a real calendar date.") from exc
    if parsed > date.today():
        raise ValueError("Date of birth cannot be in the future.")
    return parsed.isoformat()


def format_dob(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                dob TEXT NOT NULL,
                email TEXT NOT NULL,
                glucose REAL NOT NULL,
                haemoglobin REAL NOT NULL,
                cholesterol REAL NOT NULL,
                remarks TEXT NOT NULL,
                remark_source TEXT NOT NULL,
                remark_notice TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def local_remark(values: PatientInput) -> str:
    glucose = values.glucose
    if glucose < 70:
        glucose_note = "below the commonly used fasting reference range"
    elif glucose < 100:
        glucose_note = "within the commonly used fasting reference range"
    elif glucose < 126:
        glucose_note = "above the commonly used fasting reference range"
    else:
        glucose_note = "high if this was a fasting measurement"

    cholesterol = values.cholesterol
    if cholesterol < 200:
        cholesterol_note = "below 200"
    elif cholesterol < 240:
        cholesterol_note = "in the 200-239 borderline-high range"
    else:
        cholesterol_note = "at or above 240, a high total-cholesterol range"

    return (
        "Informational screening only, not a diagnosis. Assuming glucose and total cholesterol "
        "are in mg/dL and haemoglobin is in g/dL: glucose is "
        f"{glucose_note}; total cholesterol is {cholesterol_note}. Haemoglobin is recorded "
        "without interpretation because reference ranges depend on personal and clinical context. "
        "A clinician can interpret these results with the correct units, fasting status, and history."
    )


def generate_remark(values: PatientInput) -> tuple[str, str, str]:
    local = local_remark(values)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return (
            local,
            "Local screening note",
            "External AI was not called: OPENAI_API_KEY is not configured.",
        )

    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Write a brief, cautious, informational health screening remark from lab "
                    "measurements only. Do not diagnose, infer missing facts, or claim certainty. "
                    "State that units and context matter and advise clinician interpretation. "
                    "Do not request or mention personal identifiers."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Glucose: {values.glucose} mg/dL; haemoglobin: "
                    f"{values.haemoglobin} g/dL; total cholesterol: {values.cholesterol} mg/dL."
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
        text = result["choices"][0]["message"]["content"].strip()
        if not text:
            raise ValueError("The external AI returned an empty remark.")
        return text[:2000], "External AI", ""
    except HTTPError as exc:
        notice = f"External AI request failed (HTTP {exc.code}); a local screening note is shown."
    except (URLError, TimeoutError) as exc:
        notice = f"External AI is unavailable ({exc.reason if isinstance(exc, URLError) else 'timeout'}); a local screening note is shown."
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        notice = "External AI returned an unusable response; a local screening note is shown."
    return local, "Local screening note", notice


def patient_from_row(row: sqlite3.Row) -> dict[str, Any]:
    patient = dict(row)
    patient["dob"] = format_dob(patient["dob"])
    return patient


def fetch_patient(patient_id: int) -> dict[str, Any] | None:
    with database() as connection:
        row = connection.execute(
            "SELECT * FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
    return patient_from_row(row) if row else None


def create_patient(values: PatientInput) -> dict[str, Any]:
    remark, source, notice = generate_remark(values)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with database() as connection:
        cursor = connection.execute(
            """
            INSERT INTO patients
                (full_name, dob, email, glucose, haemoglobin, cholesterol, remarks,
                 remark_source, remark_notice, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values.full_name,
                values.dob,
                values.email,
                values.glucose,
                values.haemoglobin,
                values.cholesterol,
                remark,
                source,
                notice,
                now,
                now,
            ),
        )
        patient_id = cursor.lastrowid
    patient = fetch_patient(patient_id)
    if patient is None:
        raise RuntimeError("The created patient record could not be retrieved.")
    return patient


def validation_messages(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors()
    ]


initialize_database()
app = FastAPI(title="Wellnote Patient Manager", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/patients")
def list_patients() -> list[dict[str, Any]]:
    with database() as connection:
        rows = connection.execute(
            "SELECT * FROM patients ORDER BY id ASC"
        ).fetchall()
    return [patient_from_row(row) for row in rows]


@app.post("/api/patients", status_code=201)
def add_patient(values: PatientInput) -> dict[str, Any]:
    return create_patient(values)


@app.put("/api/patients/{patient_id}")
def update_patient(patient_id: int, values: PatientInput) -> dict[str, Any]:
    if fetch_patient(patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient record not found.")
    remark, source, notice = generate_remark(values)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with database() as connection:
        connection.execute(
            """
            UPDATE patients
            SET full_name = ?, dob = ?, email = ?, glucose = ?, haemoglobin = ?,
                cholesterol = ?, remarks = ?, remark_source = ?, remark_notice = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                values.full_name,
                values.dob,
                values.email,
                values.glucose,
                values.haemoglobin,
                values.cholesterol,
                remark,
                source,
                notice,
                now,
                patient_id,
            ),
        )
    patient = fetch_patient(patient_id)
    if patient is None:
        raise RuntimeError("The updated patient record could not be retrieved.")
    return patient


@app.delete("/api/patients/{patient_id}", status_code=204)
def delete_patient(patient_id: int) -> None:
    with database() as connection:
        result = connection.execute(
            "DELETE FROM patients WHERE id = ?", (patient_id,)
        )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Patient record not found.")


@app.post("/api/patients/import")
def import_patients(payload: ImportRequest) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row_number, record in enumerate(payload.records, start=1):
        try:
            values = PatientInput.model_validate(record)
        except ValidationError as exc:
            rejected.append(
                {
                    "row": row_number,
                    "full_name": str(record.get("full_name", "")),
                    "errors": validation_messages(exc),
                }
            )
            continue
        imported.append(create_patient(values))
    return {"imported": imported, "rejected": rejected}
