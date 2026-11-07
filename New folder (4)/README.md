# Wellnote Patient Manager

A small local patient-record application with a Python/FastAPI backend, a browser-based HTML/CSS/JavaScript interface, and SQLite persistence.

## Run locally

1. Use Python 3.10 or newer.
2. Install dependencies: `python -m pip install -r requirements.txt`
3. Optional external remarks: set `OPENAI_API_KEY` in your local environment. The app sends only glucose, haemoglobin, and cholesterol measurements to the OpenAI API; it does not send names, dates of birth, email addresses, or record IDs. Set `OPENAI_MODEL` to override the default model.
4. Start the server: `python -m uvicorn main:app --reload`
5. Open <http://127.0.0.1:8000>.

The database is created as `patients.db` in the project directory. To store it elsewhere, set `PATIENTS_DB_PATH` before starting the server.

Without `OPENAI_API_KEY`, records still receive a clearly labeled local screening note, and the interface explains that no external AI call was made. If the external service is unavailable, the local note is shown with a visible notice. Remarks are informational and are not a diagnosis or medical advice.

## Data validation and test records

The date field accepts `DD/MM/YYYY`; `DD.MM.YYYY` is also accepted to match the supplied test table. Impossible dates, future dates of birth, malformed email addresses, and non-positive or non-numeric blood values are rejected. Numeric values are assumed to be glucose and total cholesterol in mg/dL and haemoglobin in g/dL for the screening note; confirm units with the source lab.

`POST /api/patients/import` accepts `{"records":[...]}` and returns accepted records plus row-specific validation errors. It allows up to 100 records per request and does not alter invalid entries to make them pass validation. For example, `hunter@gmail` is rejected for lacking a domain suffix, `31.11.2001` is not a real calendar date, and a future date of birth is rejected.

The browser UI supports adding, listing, editing, and deleting records. Duplicate records are permitted because the supplied table contains a repeated person.

## Tests

Run `python -m unittest discover -s tests`.

This is a local demonstration app, not production software for storing or making clinical decisions about protected health information. It has no authentication; do not expose it to a public network.
