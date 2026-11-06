# Trade Store REST API

**A version-controlled financial trade management service using FastAPI, PostgreSQL, and optional Kafka ingestion.**

[![CI Pipeline](https://github.com/mahen0202/dws-trade-store/actions/workflows/ci.yml/badge.svg)](https://github.com/mahen0202/dws-trade-store/actions/workflows/ci.yml)

> **DWS evaluators:** Start with the [DWS Quick Start Guide](docs/DWS-QUICK-START.md). For the complete Kafka implementation, use the [`feature/kafka-ingestion` branch](https://github.com/mahen0202/dws-trade-store/tree/feature/kafka-ingestion). The `master` branch contains the original REST API implementation.

## Table of contents

1. [Overview](#1-overview)
2. [Quick start and evaluation options](#2-quick-start-and-evaluation-options)
3. [Technology stack](#3-technology-stack)
4. [Architecture and components](#4-architecture-and-components)
5. [Trade data model and business rules](#5-trade-data-model-and-business-rules)
6. [REST API](#6-rest-api)
7. [Kafka ingestion](#7-kafka-ingestion)
8. [Automated trade expiry](#8-automated-trade-expiry)
9. [Local installation](#9-local-installation)
10. [Testing and TDD](#10-testing-and-tdd)
11. [CI/CD and security scanning](#11-cicd-and-security-scanning)
12. [AWS EC2 deployment](#12-aws-ec2-deployment)
13. [Security scope and limitations](#13-security-scope-and-limitations)
14. [PlantUML diagrams](#14-plantuml-diagrams)
15. [Repository and documentation](#15-repository-and-documentation)

---


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

## 2. Quick start and evaluation options

| Evaluation method | What to do | Instructions |
|---|---|---|
| REST API locally | Install Python and PostgreSQL, initialize tables, run FastAPI, and open Swagger UI. | [Local installation](#9-local-installation) |
| REST API + Kafka locally | Complete local setup, start the Kafka Docker service, create topics, and start 3 consumers. | [Kafka ingestion](#7-kafka-ingestion) |
| Existing AWS deployment | Connect using **authorized** SSH port forwarding and open Swagger UI locally. | [AWS EC2 deployment](#12-aws-ec2-deployment) |

**Swagger UI:** `http://127.0.0.1:8000/docs` (when running locally or through an active SSH tunnel).  
**Health endpoint:** `http://127.0.0.1:8000/health`.

For a guided setup and troubleshooting, see **[DWS-QUICK-START.md](docs/DWS-QUICK-START.md)**.


## 3. Technology stack

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

## 4. Architecture and components

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

### Component responsibilities

| Component | Responsibility |
|---|---|
| `main.py` | API endpoints and application lifecycle |
| `schemas.py` | Request and response validation |
| `services.py` | Trade business rules and persistence operations |
| `models.py` | Database entity definitions |
| `database.py` | Database engine and session management |
| `expiry.py` | Automated maturity-date processing |

## 5. Trade data model and business rules

### Trade data model

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

### Business rules

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

## 6. REST API

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

## 7. Kafka ingestion

Kafka ingestion is an optional enhancement developed on the
`feature/kafka-ingestion` branch. The original REST API remains available.

### Message flow

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

Start three consumers in another terminal (the launcher supports 1–6):

```powershell
$env:KAFKA_CONSUMER_COUNT="3"
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
for development and demonstration, not production use.

## 8. Automated trade expiry

The application uses APScheduler to identify and update matured trades.

**Scheduling configuration:**

- Execution frequency: Daily.
- Scheduled time: 00:01.
- Time zone: Asia/Kolkata.
- Startup behaviour: An expiry catch-up check runs when the application starts.

The expiry operation updates the `expired` status for matured trades without deleting historical records.

**Deployment consideration:** The current scheduler runs within the application lifecycle and assumes a single application instance. A multi-instance deployment should use a dedicated scheduler or distributed job coordination mechanism.

## 9. Local installation

### Prerequisites

- Python 3.12 or later (Python 3.12 used in CI/AWS).
- PostgreSQL 16 or later.
- Git.

### Clone the repository

```bash
git clone https://github.com/mahen0202/dws-trade-store.git
cd dws-trade-store
git checkout feature/kafka-ingestion
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

Create the PostgreSQL role and database using a PostgreSQL administrator account:

```sql
CREATE USER trade_app WITH PASSWORD 'choose_a_secure_local_password';
CREATE DATABASE trade_store OWNER trade_app;
```

Replace the placeholder password in `.env` with the actual password. URL-encode special characters when necessary.

Use `.env.example` as the configuration reference. Never commit local credentials or environment files.

### Initialize database tables

After activating the virtual environment and configuring `.env`, initialize the schema once:

```powershell
python -c "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine); print('Database tables initialized successfully')"
```

`create_all()` creates missing tables; it does not manage future schema migrations.

### Start the application

```powershell
uvicorn app.main:app --reload
```

Application:

`http://127.0.0.1:8000`

Swagger UI:

`http://127.0.0.1:8000/docs`

For the full local and Kafka walkthrough, see [DWS Quick Start Guide](docs/DWS-QUICK-START.md).

## 10. Testing and TDD

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

## 11. CI/CD and security scanning

GitHub Actions automates the build verification process.

### Pipeline stages

1. Source checkout.
2. Python environment setup.
3. Dependency installation.
4. PostgreSQL test service initialization.
5. Database schema initialization.
6. Automated regression testing.
7. Dependency vulnerability scanning.

**Security note:** `pip-audit --strict` is not a critical-severity-only threshold. The pipeline fails on reported vulnerabilities under the tool's normal exit behavior; `--strict` additionally treats certain audit warnings as failures.

### Dependency audit

The pipeline executes:

```bash
pip-audit --strict
```

The latest verified pipeline execution reported:

`No known vulnerabilities found.`

This result applies to the dependencies scanned at that execution time; it is not a guarantee that the application is free from all security vulnerabilities.

## 12. AWS EC2 deployment

### Deployment workflow

The GitHub Actions workflow performs automated regression testing and dependency vulnerability scanning before deploying the application to AWS EC2.

The pipeline contains three jobs:

1. **test-and-scan:** Runs on GitHub-hosted Ubuntu. Installs dependencies, initializes a PostgreSQL test database, executes automated tests, and performs dependency vulnerability scanning using `pip-audit --strict`.
2. **deploy-to-ec2:** Runs on successful pushes to `master`, after `test-and-scan` passes. Uses a self-hosted GitHub Actions runner to deploy the original REST API implementation.
3. **deploy-kafka-to-ec2:** Runs on successful pushes to `feature/kafka-ingestion`, after `test-and-scan` passes. Uses the dedicated `dws-kafka-backup` self-hosted runner to deploy the Kafka-enabled application to a separate AWS EC2 instance.

The Kafka deployment performs the following operations:

- Fetches the latest Kafka branch from GitHub.
- Resets the EC2 working copy to the fetched commit using `git reset --hard FETCH_HEAD`.
- Installs Python application and Kafka dependencies.
- Initializes the database schema if required.
- Restarts the FastAPI and Kafka consumer systemd services.
- Verifies FastAPI health, Kafka consumer activity, and Kafka container status.

### Verified deployment

The Kafka implementation was successfully deployed to an Ubuntu EC2 instance in the AWS Sydney region.

An end-to-end deployment was verified at commit `3226bce` (`Fix Kafka EC2 deployment to use fetched commit`). Subsequent documentation commits do not change this historical test record.

The following checks passed:

| Verification | Result |
|---|---|
| GitHub Actions deployment | Successful |
| Deployed Git commit | `3226bce` |
| FastAPI `/health` | HTTP 200 |
| Kafka broker | Running |
| Kafka consumer | Active |
| Kafka message ingestion | Successful |
| PostgreSQL persistence | Successful |
| REST API trade retrieval | HTTP 200 |

### End-to-end Kafka verification

A test trade with identifier `DWS-CICD-001` was published directly to the Kafka topic `trades.incoming`.

The Kafka consumer processed the message and persisted the trade in PostgreSQL.

The following REST API request was then executed:

```bash
curl -i http://127.0.0.1:8000/trades/DWS-CICD-001
```

The API returned HTTP 200 with the persisted trade, version `1`, and `expired: false`.

This verified the complete processing flow:

`Kafka Producer → Kafka Broker → Kafka Consumer → PostgreSQL → FastAPI REST API`

The implementation uses a single-node Kafka broker for development and demonstration purposes. It is not a production-grade highly available Kafka cluster.

### Kafka consumer configuration on AWS

The EC2 Kafka deployment has been verified with **3 consumer processes** in the `trade-store-consumers` group across **6 partitions** of `trades.incoming` (2 partitions per consumer). The consumer count is configured in the enabled `trade-store-consumer` systemd service using `KAFKA_CONSUMER_COUNT=3`.


### Access the existing AWS application

The Kafka-enabled EC2 instance is associated with Elastic IP **`15.135.206.84`**. FastAPI listens on `127.0.0.1:8000` on the instance, so it is **not directly exposed publicly**.

An authorized SSH user can create a local tunnel:

```bash
ssh -i /path/to/authorized-key.pem -L 8000:127.0.0.1:8000 ubuntu@15.135.206.84
```

Keep the SSH session open and visit `http://localhost:8000/docs` in a browser. The SSH key is **not** included in the public repository and must not be shared. The Elastic IP remains stable across Stop/Start while associated with the instance.

A new AWS deployment requires environment-specific EC2, PostgreSQL, Docker, systemd, runner, and secret configuration; cloning this repository does not provision AWS infrastructure automatically.


## 13. Security scope and limitations

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

## 14. PlantUML diagrams

The `docs/` directory contains PlantUML diagrams illustrating the
application design and trade-processing workflow.

| Diagram | Description |
|---|---|
| [Trade Processing Sequence](docs/trade-processing-sequence.puml) | Shows request validation, version checks and database persistence. |
| [Trade Store Class Diagram](docs/trade-store-class-diagram.puml) | Shows the application components and their relationships. |

The diagrams can be rendered using PlantUML.

## 15. Repository and documentation

- **Source:** https://github.com/mahen0202/dws-trade-store
- **Complete Kafka branch:** https://github.com/mahen0202/dws-trade-store/tree/feature/kafka-ingestion
- **DWS evaluator guide:** [docs/DWS-QUICK-START.md](docs/DWS-QUICK-START.md)
- **GitHub Actions:** https://github.com/mahen0202/dws-trade-store/actions

---

*Trade Store REST API · FastAPI · PostgreSQL · Kafka · Pytest · GitHub Actions*
