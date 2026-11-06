# DWS Trade Store — Quick Start & Evaluation Guide

**For DWS evaluators:** The deployed APIs are accessible directly through a web browser. No SSH key, terminal, or local installation is required to review Swagger UI.

**Repository:** [DWS Trade Store](https://github.com/mahen0202/dws-trade-store)  
**Full implementation:** [`feature/kafka-ingestion`](https://github.com/mahen0202/dws-trade-store/tree/feature/kafka-ingestion)

## Table of Contents

- [1. AWS API Verification — Start Here](#1-aws-api-verification--start-here)
- [2. Measured Performance Results](#2-measured-performance-results)
- [3. Run the REST API Locally (Windows)](#3-run-the-rest-api-locally-windows)
- [4. Run Kafka Locally](#4-run-kafka-locally)
- [5. Verify the API Operations](#5-verify-the-api-operations)
- [6. Application Overview](#6-application-overview)
- [7. Automated Tests and CI/CD](#7-automated-tests-and-cicd)
- [8. Troubleshooting](#8-troubleshooting)
- [9. Deployment Notes](#9-deployment-notes)
- [10. Further Documentation](#10-further-documentation)

---

## 1. AWS API Verification — Start Here

The two implementations are hosted separately on AWS EC2. Open the Swagger UI links below to inspect the available API operations and submit test trades.

| Implementation | Live Swagger UI | Architecture |
| --- | --- | --- |
| **Core FastAPI REST API** | **[https://32.236.203.17/docs](https://32.236.203.17/docs)** | FastAPI → PostgreSQL |
| **Kafka-enabled API** | **[https://15.135.206.84/docs](https://15.135.206.84/docs)** | FastAPI → Kafka → consumer → PostgreSQL; direct REST endpoints also available |

**No SSH key or port forwarding is needed for evaluator access.** The URLs are provided by the project owner; availability and TLS certificate trust have not been independently verified. If the browser reports a certificate warning, contact the project owner rather than entering sensitive data or bypassing security warnings.

### Suggested verification flow

1. Open the **core FastAPI Swagger UI** and call `GET /health`.
2. Use `POST /trades` to create a trade, then `GET /trades/{trade_id}` to retrieve it.
3. Open the **Kafka-enabled Swagger UI** and call `GET /health`.
4. Submit a trade with `POST /trades/kafka`; HTTP **202 Accepted** confirms Kafka accepted the message.
5. After asynchronous processing, retrieve that trade using `GET /trades/{trade_id}`.

The Kafka deployment uses **one broker**, **six incoming-topic partitions**, and **three consumer processes** in the `trade-store-consumers` group. Its Elastic IP is `15.135.206.84`.

---

## 2. Measured Performance Results

These figures come from previous trade-ingestion benchmark runs. They are **observed measurements**, not projected capacity or production service-level guarantees. The three paths use different ingestion mechanisms; their timings should not be interpreted as an apples-to-apples infrastructure comparison without matching the test setup, concurrency, and completion criteria.

### 2.1 Trade-volume results (100 / 1,000 / 10,000)

| Ingestion path / run | Trades | Elapsed time | Throughput | Result |
| --- | ---: | ---: | ---: | --- |
| FastAPI REST (`POST /trades`) | 100 | 1.81 s | 55.31 trades/s | Measured |
| FastAPI REST (`POST /trades`) | 1,000 | — | — | Exact prior measurement not recovered |
| FastAPI REST (`POST /trades`) | 10,000 | 108.77 s | 91.94 trades/s | Measured; concurrency 20 |
| FastAPI → Kafka API (`POST /trades/kafka`) | 100 | 4.05 s | 24.72 requests/s | 100 accepted; 0 failures |
| FastAPI → Kafka API (`POST /trades/kafka`) | 1,000 | 5.41 s | 184.96 requests/s | 1,000 accepted; 0 failures |
| FastAPI → Kafka API (`POST /trades/kafka`) | 10,000 | 49.17 s | 203.39 requests/s | 10,000 accepted; 0 failures |
| Direct Kafka → PostgreSQL | 100 | — | — | Exact prior measurement not recovered |
| Direct Kafka → PostgreSQL | 1,000 | — | — | Exact prior measurement not recovered |
| Direct Kafka → PostgreSQL | 10,000 | 31.38 s | 318.69 trades/s | 10,000 persisted; 0 failures |

**Important:** The FastAPI → Kafka API rows above report **HTTP request acceptance throughput**, not necessarily the time for all messages to be persisted. Direct Kafka throughput reflects a different producer-to-consumer path. The measurements are from earlier runs and should be presented with their differing completion criteria.

### 2.2 HTTP latency measurements

| Test | Median (p50) | p95 | p99 |
| --- | ---: | ---: | ---: |
| FastAPI REST — 100 trades | 36.21 ms | 773.60 ms | 1,304.66 ms |
| FastAPI → Kafka API — 100 trades | 54.57 ms | 3,402.93 ms | 3,412.94 ms |
| FastAPI → Kafka API — 1,000 trades | 46.54 ms | 111.45 ms | 180.66 ms |
| FastAPI → Kafka API — 10,000 trades | 43.24 ms | 94.74 ms | 173.98 ms |

### 2.3 Separate 10,000-trade end-to-end comparison

A separate comparison measured the complete persistence flow. These results should **not** be combined with the HTTP acceptance timings above.

| Processing path | 10,000-trade elapsed time | Throughput | Outcome |
| --- | ---: | ---: | --- |
| Direct FastAPI REST → PostgreSQL | 108.77 s | 91.94 trades/s | Completed |
| Direct Kafka → PostgreSQL | 31.38 s | 318.69 trades/s | 10,000 persisted; 0 failures |
| FastAPI → Kafka → PostgreSQL (earlier run) | 127.04 s | 78.72 trades/s | 10,000 persisted; 0 failures |
| FastAPI → Kafka → PostgreSQL (optimized run) | 57.50 s | 173.90 trades/s | 10,000 persisted; 0 HTTP failures |

The optimized end-to-end FastAPI → Kafka run reported **p95 HTTP latency of 261.18 ms**. A later concurrency-50 run reported **78.12 s**, **128.01 trades/s**, and **p95 1,032.02 ms**, with **10,000 successful requests and zero failures**. These are distinct test conditions, not contradictory measurements.

**Benchmark scope:** These are historical local test observations, not independently reproduced AWS benchmarks. Hardware, exact load-generator configuration, and database conditions should be recorded before treating them as formal performance acceptance criteria.

---

## 3. Run the REST API Locally (Windows)

### Prerequisites

Install and start the following as applicable:

- Python 3.12
- PostgreSQL 16 or later
- Git

Run the commands below in **Windows PowerShell**, unless another terminal is specified.

### Step 1 — Clone the repository

```powershell
git clone https://github.com/mahen0202/dws-trade-store.git
cd dws-trade-store
git checkout feature/kafka-ingestion
```

### Step 2 — Create the PostgreSQL database

Start PostgreSQL and connect using **pgAdmin** or **psql** with an administrator account. Execute:

```sql
CREATE USER trade_app WITH PASSWORD 'choose_a_secure_local_password';
CREATE DATABASE trade_store OWNER trade_app;
```

Use a unique password instead of the example value.

### Step 3 — Configure the environment

Create a `.env` file in the repository root, using `.env.example` as a reference:

```env
DATABASE_URL=postgresql+psycopg://trade_app:YOUR_PASSWORD@localhost:5432/trade_store
```

Replace `YOUR_PASSWORD` with the PostgreSQL password from Step 2. URL-encode special characters when necessary.

> **Security:** Do not commit `.env` or local credentials to Git.

### Step 4 — Create a virtual environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5 — Initialize the database tables

With the virtual environment activated, run from the project root:

```powershell
python -c "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine); print('Database tables initialized successfully')"
```

This command imports the SQLAlchemy models and creates missing tables. It does **not** delete existing trade records or recreate tables that already exist.

> `create_all()` is suitable for initializing this demonstration application; it does not manage migrations for existing tables.

### Step 6 — Start FastAPI

```powershell
uvicorn app.main:app --reload
```

Open the following URLs:

| Resource | URL |
| --- | --- |
| Swagger UI | http://127.0.0.1:8000/docs |
| Health check | http://127.0.0.1:8000/health |

Use Swagger UI to explore and execute the REST API operations.

---

## 4. Run Kafka Locally

This option **extends Option A**. Complete the REST API setup first, then install and start **Docker Desktop**.

### Step 1 — Install Kafka dependencies

In PowerShell, with the virtual environment activated:

```powershell
pip install -r requirements-kafka.txt
```

### Step 2 — Start Kafka

From the project root:

```powershell
docker compose up -d kafka
docker ps
```

The Kafka container should be named `dws-trade-kafka`.

> PostgreSQL remains installed locally; this Docker Compose configuration does not start PostgreSQL.

### Step 3 — Create Kafka topics

Automatic topic creation is disabled. Create both topics explicitly:

**Incoming trades — six partitions:**

```powershell
docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.incoming --partitions 6 --replication-factor 1
```

**Rejected trades / dead-letter queue — six partitions:**

```powershell
docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.rejected --partitions 6 --replication-factor 1
```

### Step 4 — Start FastAPI with Kafka enabled

Open a **new PowerShell terminal** in the project directory:

```powershell
.\.venv\Scripts\Activate.ps1
$env:KAFKA_ENABLED="true"
uvicorn app.main:app --reload
```

If FastAPI is already running from Option A, stop that instance before starting this one to avoid a port conflict.

### Step 5 — Start three Kafka consumers

Open **another PowerShell terminal** in the project directory:

```powershell
.\.venv\Scripts\Activate.ps1
$env:KAFKA_CONSUMER_COUNT="3"
python -m app.kafka.launcher
```

The launcher starts **three consumer processes**, all in the consumer group `trade-store-consumers`. Kafka distributes the **six partitions** across those consumers.

### Step 6 — Verify partition assignments

In a separate PowerShell terminal:

```powershell
docker exec dws-trade-kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group trade-store-consumers --members --verbose
```

Under normal operation, each of the three consumers should have **two partitions** assigned.

### Step 7 — Test Kafka ingestion

1. Open [Swagger UI](http://127.0.0.1:8000/docs).
2. Locate **`POST /trades/kafka`**.
3. Submit a valid trade using the request schema displayed in Swagger.
4. Confirm the API returns **HTTP 202 Accepted**.
5. Retrieve the trade using **`GET /trades/{trade_id}`** after the consumer processes the message.

Kafka ingestion is asynchronous: HTTP 202 confirms acceptance by Kafka, not immediate PostgreSQL persistence.

---

## 5. Verify the API Operations

Open one of the [hosted Swagger UIs](#1-aws-api-verification--start-here), or your locally running Swagger UI, and execute these operations:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Verify application health |
| `POST` | `/trades` | Create or update a trade |
| `GET` | `/trades` | List stored trades |
| `GET` | `/trades/{trade_id}` | Retrieve a trade |
| `POST` | `/trades/kafka` | Submit a trade asynchronously through Kafka (when enabled) |

Use the request schemas displayed in Swagger UI. The application enforces trade version validation and maturity-date rules.

---

## 6. Application Overview

The Trade Store application manages financial trade records with Python FastAPI and PostgreSQL, with optional Apache Kafka asynchronous ingestion.

| Option | Purpose | Prerequisites |
| --- | --- | --- |
| Hosted AWS | Verify both implementations immediately | Browser |
| Local REST API | Run FastAPI and PostgreSQL locally | Python 3.12, PostgreSQL 16+, Git |
| Local Kafka | Add Kafka producer and consumers to the local API | Local REST API, Docker Desktop |

**Key features:** trade creation and retrieval, version-aware updates, maturity-date validation, scheduled expiry, regression testing, dependency vulnerability scanning, and branch-specific CI/CD deployment.

---

## 7. Automated Tests and CI/CD

### Run regression tests

Activate the virtual environment and execute:

```powershell
python -m pytest
```

### Run tests with coverage

```powershell
python -m pytest --cov=app --cov-report=term-missing
```

The test suite requires the configured test database; consult the main README for test-database isolation details.

### GitHub Actions pipeline

GitHub Actions runs automated regression tests and dependency vulnerability scanning, followed by branch-specific AWS deployment jobs when applicable.

**[View CI/CD workflow runs](https://github.com/mahen0202/dws-trade-store/actions)**

---

## 8. Troubleshooting

| Issue | What to check |
| --- | --- |
| **Database connection failure** | PostgreSQL is running, the database exists, and `.env` has the correct credentials. |
| **Port 8000 already in use** | Stop the existing FastAPI process or choose another Uvicorn port. |
| **Kafka connection failure** | Docker Desktop is running and the `dws-trade-kafka` container is healthy. |
| **Kafka consumers are not processing** | Topics exist, consumer logs show no errors, and group partition assignments are present. |
| **Hosted Swagger URL unavailable** | Confirm the EC2 instance and HTTPS reverse proxy are running, and the instance security group permits HTTPS traffic. Contact the project owner. |

---

## 9. Deployment Notes

| Branch | Deployment purpose |
| --- | --- |
| `master` | Original REST API implementation |
| `feature/kafka-ingestion` | Kafka enhancement and its separate AWS deployment configuration |

The GitHub Actions workflow includes automated testing, vulnerability scanning, and branch-specific AWS deployment jobs.

**Cloning the repository does not automatically provision AWS infrastructure.** A new AWS account requires configuration of EC2, PostgreSQL, Docker, systemd services, a GitHub Actions runner, and environment-specific secrets.

---

## 10. Further Documentation

- [Main README](../README.md) — architecture, business rules, API specification, tests, security scope, and deployment details.
- [Trade Processing Sequence Diagram](trade-processing-sequence.puml) — request processing and persistence flow.
- [Trade Store Class Diagram](trade-store-class-diagram.puml) — application components and their relationships.
- [Full implementation on GitHub](https://github.com/mahen0202/dws-trade-store/tree/feature/kafka-ingestion)

