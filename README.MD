
# Deutsche Bank Trade Store REST API

A RESTful Trade Store application built with **Python, FastAPI, SQLAlchemy and PostgreSQL**. The application manages trade records, enforces trade-versioning and maturity-date business rules, and automatically marks matured trades as expired.

## 1. Technology Stack

- Python 3.13
- FastAPI
- SQLAlchemy
- PostgreSQL 17
- Pydantic
- Pytest
- APScheduler
- GitHub Actions
- pip-audit

## 2. Functional Requirements

Each trade contains the following attributes:

| Field | Description |
|---|---|
| trade_id | Unique trade identifier |
| version | Trade version |
| counterparty_id | Counter-party identifier |
| portfolio_id | Portfolio identifier |
| maturity_date | Trade maturity date |
| created_date | Trade creation date |
| expired | Expiry status |

### Business Rules

1. A trade with a lower version than the existing stored version is rejected.
2. A trade with the same version replaces the existing record.
3. A trade with a higher version replaces the existing record.
4. Trades with maturity dates earlier than the current date are rejected.
5. Matured trades are automatically marked as expired.
6. Expired trades are retained in the database and are not deleted.

## 3. REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/trades` | Create or update a trade |
| GET | `/trades/{trade_id}` | Retrieve a trade by ID |
| GET | `/health` | Application health check |

### Sample Request

`POST /trades`

```json
{
  "trade_id": "T1001",
  "version": 1,
  "counterparty_id": "CP001",
  "portfolio_id": "PORT001",
  "maturity_date": "2027-12-31",
  "created_date": "2026-11-01"
}
```

The application validates the request and applies the trade-versioning and maturity-date rules before persisting the trade.

## 4. Project Structure

```text
dws-trade-store/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── services.py
│   └── expiry.py
│
├── tests/
│   └── test_trades.py
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── .env.example
├── .gitignore
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 5. Local Setup

### Prerequisites

- Python 3.13
- PostgreSQL 17
- Git

### Clone the repository

```bash
git clone https://github.com/mahen0202/dws-trade-store.git
cd dws-trade-store
```

### Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure the database

Create a PostgreSQL database named `trade_store` and configure the database connection in a local `.env` file.

Example:

```env
DATABASE_URL=postgresql+psycopg://trade_app:<your-password>@localhost:5432/trade_store
```

Use `.env.example` as the configuration template. Do not commit passwords or other secrets.

### Start the application

```powershell
uvicorn app.main:app --reload
```

Application URL:

`http://127.0.0.1:8000`

Interactive API documentation:

`http://127.0.0.1:8000/docs`

## 6. Automated Testing

The project uses Pytest and FastAPI TestClient for automated testing.

A separate PostgreSQL database named `trade_store_test` is used for tests to prevent test execution from affecting development data.

Configure `.env.test` locally with:

```env
TEST_DATABASE_URL=postgresql+psycopg://trade_app:<your-test-password>@localhost:5432/trade_store_test
```

Run the tests:

```powershell
python -m pytest -v
```

The test configuration includes a safety guard that prevents automated tests from running against the development database.

**Current CI result:** 22 automated tests passed.

## 7. Trade Expiry Scheduler

The application uses APScheduler to automatically identify and expire matured trades.

- Expiry job is scheduled daily at 00:01 Asia/Kolkata.
- A catch-up expiry check runs when the application starts.
- Matured trades are updated using a database operation.
- Existing trade records are retained.

The current scheduler implementation assumes a single application instance. A multi-instance production deployment should use a dedicated scheduler or distributed job coordination.

## 8. CI/CD and Security

GitHub Actions provides an automated CI pipeline.

The pipeline performs the following steps:

1. Checks out the source code.
2. Sets up Python 3.13.
3. Installs application dependencies.
4. Starts a PostgreSQL 17 test database.
5. Initializes the database schema.
6. Runs automated tests with coverage reporting.
7. Scans dependencies using pip-audit.

The vulnerability scan uses:

```bash
pip-audit --strict
```

The pipeline fails if the dependency audit detects vulnerabilities under the configured strict policy.

### Latest verified pipeline result

- Database schema initialization: Passed
- Automated tests: Passed
- Dependency vulnerability scan: Passed
- pip-audit output: No known vulnerabilities found

## 9. Repository

Source code:

https://github.com/mahen0202/dws-trade-store

## 10. Future Enhancements

- Database schema migrations using Alembic.
- Centralized structured logging and monitoring.
- Authentication and authorization.
- Dedicated distributed scheduler for multi-instance deployments.
- Containerized deployment and cloud infrastructure integration.

---

**Project:** Deutsche Bank Trade Store REST API  
**Language:** Python  
**Database:** PostgreSQL  
**Framework:** FastAPI
