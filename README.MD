# Trade Store REST API

**A version-controlled trade management service built with Python, FastAPI and PostgreSQL.**

[![CI Pipeline](https://github.com/mahen0202/dws-trade-store/actions/workflows/ci.yml/badge.svg)](https://github.com/mahen0202/dws-trade-store/actions/workflows/ci.yml)

## 1. Overview

The Trade Store REST API provides a backend service for managing financial trade records. It supports trade creation, version-based updates, validation of maturity dates, persistent storage and automated trade-expiry processing.

The solution is designed around clear separation of API, business logic, data access and scheduled processing responsibilities.

### Key capabilities

- RESTful API implementation using FastAPI.
- Persistent trade storage using PostgreSQL.
- Version-aware trade creation and update handling.
- Business-rule validation for trade maturity dates.
- Automated expiry processing using APScheduler.
- Automated regression testing using Pytest.
- Continuous integration using GitHub Actions.
- Dependency vulnerability auditing using pip-audit.

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Programming language | Python 3.12 (CI/AWS); Python 3.13 (local) |
| API framework | FastAPI |
| Data persistence | PostgreSQL 16 (CI/AWS); PostgreSQL 17 (local) |
| ORM | SQLAlchemy |
| Request validation | Pydantic |
| Automated testing | Pytest |
| API test client | FastAPI TestClient |
| Scheduled processing | APScheduler |
| CI/CD | GitHub Actions |
| Dependency security | pip-audit |

## 3. Solution Architecture

The application follows a layered architecture to separate responsibilities and improve maintainability.

```text
                  API Consumer
                       |
                       v
              FastAPI REST Layer
                       |
                       v
              Request Validation
                  (Pydantic)
                       |
                       v
              Business Service Layer
                (Trade Services)
                       |
                       v
              SQLAlchemy Data Layer
                       |
                       v
                  PostgreSQL


              Scheduled Processing
                       |
                       v
                Expiry Service
                       |
                       v
                  PostgreSQL
```


## Architecture Diagrams

The `docs/` directory contains PlantUML diagrams illustrating the
application design and trade-processing workflow.

| Diagram | Description |
|---|---|
| [Trade Processing Sequence](docs/trade-processing-sequence.puml) | Shows request validation, version checks and database persistence. |
| [Trade Store Class Diagram](docs/trade-store-class-diagram.puml) | Shows the application components and their relationships. |

The diagrams can be rendered using PlantUML.



### Component responsibilities

| Component | Responsibility |
|---|---|
| `main.py` | API endpoints and application lifecycle |
| `schemas.py` | Request and response validation |
| `services.py` | Trade business rules and persistence operations |
| `models.py` | Database entity definitions |
| `database.py` | Database engine and session management |
| `expiry.py` | Automated maturity-date processing |

## 4. Trade Data Model

Each trade contains the following attributes:

| Attribute | Type | Description |
|---|---|---|
| trade_id | String | Unique trade identifier and primary key |
| version | Integer | Trade version |
| counterparty_id | String | Counter-party identifier |
| portfolio_id | String | Portfolio identifier |
| maturity_date | Date | Trade maturity date |
| created_date | Date | Trade creation date |
| expired | Boolean | Indicates whether the trade has expired |

## 5. Business Rules

The service enforces the following business rules:

| Rule | Expected behaviour |
|---|---|
| New trade | Create a trade if the identifier does not exist |
| Lower version | Reject an incoming trade with a lower version |
| Same version | Replace the existing trade record |
| Higher version | Replace the existing trade record |
| Past maturity | Reject a trade whose maturity date is earlier than today |
| Trade expiry | Mark matured trades as expired |
| Record retention | Retain expired trades; do not delete them |

Trade updates are handled through database transactions to maintain data consistency.

### Concurrency Handling

Trade creation and version updates use PostgreSQL atomic UPSERT
(`INSERT ... ON CONFLICT DO UPDATE`).

The database applies the version condition atomically, preventing
a lower-version request from overwriting a higher-version record
during concurrent requests.

Equal versions are permitted to replace existing records.

## 6. REST API Specification

### Available endpoints

| HTTP method | Endpoint | Purpose |
|---|---|---|
| POST | `/trades` | Create or update a trade |
| GET | `/trades` | Retrieve trades with pagination and expiry filtering |
| GET | `/trades/{trade_id}` | Retrieve an active trade |
| GET | `/health` | Application health check |

### Trade retrieval parameters

The `GET /trades` endpoint supports:

- `skip`: Number of records to skip (default: 0).
- `limit`: Maximum records to return (default: 10, maximum: 100).
- `include_expired`: Include expired trades when true (default: false).

Example:

`GET /trades?skip=0&limit=10&include_expired=true`


### Sample request

**POST `/trades`**

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

### Validation and error handling

The API uses request validation and HTTP exceptions to communicate invalid requests and business-rule violations.

| HTTP status | Scenario |
|---|---|
| 400 | Trade maturity date is in the past |
| 409 | Incoming trade version is lower than the stored version |
| 422 | Request validation failure |

Interactive API documentation is available through FastAPI Swagger UI at `/docs`.

## 7. Automated Trade Expiry

The application uses APScheduler to identify and update matured trades.

**Scheduling configuration:**

- Execution frequency: Daily.
- Scheduled time: 00:01.
- Time zone: Asia/Kolkata.
- Startup behaviour: An expiry catch-up check runs when the application starts.

The expiry operation updates the `expired` status for matured trades without deleting historical records.

**Deployment consideration:** The current scheduler runs within the application lifecycle and assumes a single application instance. A multi-instance deployment should use a dedicated scheduler or distributed job coordination mechanism.

## 8. Testing Strategy and TDD

The project uses Pytest and FastAPI TestClient to validate trade-processing functionality. Tests cover API behavior, business rules, persistence, scheduled expiry, and optional Kafka ingestion.

### Test Coverage

The automated test suite verifies:

- Trade creation and retrieval.
- Same-version and higher-version updates.
- Rejection of lower trade versions.
- Rejection of past-maturity trades.
- Atomic PostgreSQL UPSERT behavior.
- Automated trade-expiry processing.
- Application lifecycle and scheduler behavior.
- Database error handling.
- Kafka producer delivery acknowledgment, failures and timeouts.
- Kafka API feature-flag behavior.
- Kafka consumer processing, retry and offset commits.
- Dead-letter queue publishing for rejected trades.
- Kafka consumer launcher behavior.

### TDD-Oriented Development

The implementation is organized around independently testable business rules and automated regression tests.

The tests provide executable specifications for expected behavior, including successful trade updates and rejection scenarios.

The repository demonstrates automated testing and regression verification. Historical test-first development would require supporting commit history or other evidence.

### Test Database Isolation

Automated tests use a dedicated PostgreSQL database named `trade_store_test`.

A safety guard prevents the test suite from running against the development database.

### Run Automated Tests

```powershell
python -m pytest -q --cov=app --cov-report=term-missing
```

### Latest Local Verification

| Metric | Result |
|---|---|
| Tests executed | 61 |
| Tests passed | 61 |
| Tests failed | 0 |
| Overall statement coverage | 96% |
| Statements analyzed | 309 |
| Uncovered statements | 11 |
| Python version | 3.13.14 |
| Execution environment | Windows |

All REST API business-rule modules achieved 100% statement coverage. Kafka producer coverage was 83%, Kafka consumer coverage was 99%, and Kafka launcher coverage was 96%.

These measurements reflect the latest local test execution and may differ from CI results.

## 9. Continuous Integration and Security Scanning

GitHub Actions automates the build verification process.

### Pipeline stages

1. Source checkout.
2. Python environment setup.
3. Dependency installation.
4. PostgreSQL test service initialization.
5. Database schema initialization.
6. Automated regression testing.
7. Dependency vulnerability scanning.

### Automated AWS EC2 Deployment

The GitHub Actions workflow contains two dependent jobs:

1. **test-and-scan:** Installs dependencies, initializes PostgreSQL, executes automated regression tests, and performs dependency vulnerability scanning using `pip-audit`.
2. **deploy-to-ec2:** Runs after successful completion of `test-and-scan`, for pushes to the `master` branch. The self-hosted runner updates the application source, installs dependencies, initializes the database schema, restarts the `trade-store` systemd service, and verifies the `/health` endpoint.

The latest reported GitHub Actions execution completed both jobs successfully.

The optional Kafka implementation is maintained separately on `feature/kafka-ingestion` and should not be described as deployed to EC2 until merged and deployed.

**Security note:** `pip-audit --strict` is not a critical-severity-only threshold. The pipeline fails on reported vulnerabilities under the tool's normal exit behavior; `--strict` additionally treats certain audit warnings as failures.

### Dependency audit

The pipeline executes:

```bash
pip-audit --strict
```

The latest verified pipeline execution reported:

`No known vulnerabilities found.`

This result applies to the dependencies scanned at that execution time; it is not a guarantee that the application is free from all security vulnerabilities.


## 10. Security Scope and Limitations

The current implementation focuses on trade-management functionality and the specified assignment requirements.

The following security capabilities are not currently implemented:

- User authentication.
- JWT or OAuth2 token validation.
- Role-based access control.
- Fine-grained API permissions.
- User-level audit trails.

Consequently, the current API should be considered an assignment-level implementation, not a production-ready banking service.

### Recommended enterprise enhancements

- OAuth2 / JWT-based authentication.
- Role-based authorization for trade read and write operations.
- Secure secret and signing-key management.
- API rate limiting and abuse protection.
- Structured security and audit logging.
- Database migration management using Alembic.
- Distributed scheduling for multi-instance deployments.

## 11. Local Development Setup

### Prerequisites

- Python 3.12 or later (Python 3.12 used in CI/AWS).
- PostgreSQL 16 or later.
- Git.

### Clone the repository

```bash
git clone https://github.com/mahen0202/dws-trade-store.git
cd dws-trade-store
```

### Create a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure database connectivity

Create a local `.env` file:

```env
DATABASE_URL=postgresql+psycopg://trade_app:<your-password>@localhost:5432/trade_store
```

Create the PostgreSQL database and configure the application database user before starting the application.

Use `.env.example` as the configuration reference. Never commit local credentials or environment files.

### Start the application

```powershell
uvicorn app.main:app --reload
```

Application:

`http://127.0.0.1:8000`

Swagger UI:

`http://127.0.0.1:8000/docs`

## 12. Repository

**Source code:**  
https://github.com/mahen0202/dws-trade-store

**CI/CD executions:**  
https://github.com/mahen0202/dws-trade-store/actions

---

**Project:** Trade Store REST API  
**Implementation:** Python / FastAPI / PostgreSQL  
**Automation:** Pytest / GitHub Actions / pip-audit


## Optional Kafka-Based Trade Ingestion

Kafka ingestion is an optional enhancement developed on the
`feature/kafka-ingestion` branch. The original REST API remains available.

### Architecture

```text
POST /trades/kafka
        |
        v
FastAPI + Kafka Producer
        |
        v
Kafka: trades.incoming (6 partitions)
        |
        v
Consumer group: trade-store-consumers
(up to 6 consumer processes)
        |
        +---- Valid trade ----> PostgreSQL atomic UPSERT
        |
        +---- Invalid trade --> trades.rejected (DLQ)
        |
        v
Commit Kafka offset after successful processing
```

### Configuration

| Variable | Default |
|---|---|
| `KAFKA_ENABLED` | `false` |
| `KAFKA_BOOTSTRAP_SERVERS` | `127.0.0.1:9092` |
| `KAFKA_TOPIC` | `trades.incoming` |
| `KAFKA_DLQ_TOPIC` | `trades.rejected` |
| `KAFKA_CONSUMER_COUNT` | `1` (maximum 6) |

### Start Kafka Locally

Install the optional dependency:

```powershell
pip install -r requirements-kafka.txt
```

Start Kafka:

```powershell
docker compose up -d kafka
```

Create both topics (automatic topic creation is disabled):

```powershell
docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.incoming --partitions 6 --replication-factor 1

docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.rejected --partitions 6 --replication-factor 1
```

Start FastAPI in one terminal:

```powershell
$env:KAFKA_ENABLED="true"
uvicorn app.main:app --reload
```

Start six consumers in another terminal:

```powershell
$env:KAFKA_CONSUMER_COUNT="6"
python -m app.kafka.launcher
```

### Kafka API

`POST /trades/kafka` accepts the same trade payload as `POST /trades`.

- **202 Accepted:** Kafka acknowledged the message. PostgreSQL persistence occurs asynchronously.
- **503 Service Unavailable:** Kafka ingestion is disabled or publishing failed.
- **422 Unprocessable Entity:** Request validation failed.

The producer uses `acks=all`, idempotence, and delivery callbacks.

Consumers manually commit offsets after successful database persistence
or confirmed DLQ delivery. Database and DLQ delivery failures are retried
without committing the failed offset.

The design provides at-least-once processing, not end-to-end exactly-once
execution. The single-node Kafka broker uses PLAINTEXT and is intended
for local development and testing.
