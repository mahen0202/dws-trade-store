\# DWS Trade Store — Quick Start Guide



\## 1. Overview



This application provides REST APIs for managing trades using Python FastAPI and PostgreSQL.



It also supports optional asynchronous trade ingestion using Apache Kafka.



\*\*GitHub repository:\*\* https://github.com/mahen0202/dws-trade-store



\*\*Full implementation branch:\*\* `feature/kafka-ingestion`



\*\*Technology stack:\*\* Python 3.12, FastAPI, PostgreSQL 16, Apache Kafka 4.1.1, Docker, Pytest, GitHub Actions.



\## 2. Option A — Run the REST API Locally (Windows)



\### Prerequisites



Install Python 3.12, PostgreSQL 16 or later, and Git.



\### Step 1 — Download the application



Open PowerShell:



```powershell

git clone https://github.com/mahen0202/dws-trade-store.git

cd dws-trade-store

git checkout feature/kafka-ingestion

```



\### Step 2 — Create the PostgreSQL database



Start PostgreSQL and connect using pgAdmin or psql with an administrator account.



Execute:



```sql

CREATE USER trade\_app WITH PASSWORD 'choose\_a\_secure\_local\_password';

CREATE DATABASE trade\_store OWNER trade\_app;

```



Use a unique password rather than the example value.



\### Step 3 — Configure environment variables



Create `.env` in the project root using `.env.example` as a reference.



Set:



```env

DATABASE\_URL=postgresql+psycopg://trade\_app:YOUR\_PASSWORD@localhost:5432/trade\_store

```



Replace `YOUR\_PASSWORD` with the password created in PostgreSQL. URL-encode special characters if necessary.



Do not commit `.env` to Git.


### Initialize the database tables

After creating the PostgreSQL database and configuring `.env`, run this command from the project root with the Python virtual environment activated:

```powershell
python -c "from app.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine); print('Database tables initialized successfully')"
```

This imports the SQLAlchemy models and creates any missing tables in PostgreSQL.

It does not delete existing trade records or recreate tables that already exist.

**Note:** `create_all()` is suitable for initializing this demonstration application. It does not manage schema migrations for existing tables.



\### Step 4 — Install Python dependencies



```powershell

python -m venv .venv

.\\.venv\\Scripts\\Activate.ps1

python -m pip install --upgrade pip

pip install -r requirements.txt

```



\### Step 5 — Start FastAPI



```powershell

uvicorn app.main:app --reload

```



Open:



\- Swagger UI: http://127.0.0.1:8000/docs

\- Health check: http://127.0.0.1:8000/health



Use Swagger UI to explore and execute the available REST API operations.



\## 3. Option B — Run Kafka Locally



This option extends the local REST API setup.



\### Prerequisites



Complete Option A and install Docker Desktop.



\### Step 1 — Start Kafka



From the project directory:



```powershell

docker compose up -d kafka

```



Verify:



```powershell

docker ps

```



The Kafka container should be named `dws-trade-kafka`.



PostgreSQL remains installed locally and is not started by Docker Compose.



\### Step 2 — Create Kafka topics



```powershell

docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.incoming --partitions 6 --replication-factor 1

```



```powershell

docker exec dws-trade-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --create --if-not-exists --topic trades.rejected --partitions 6 --replication-factor 1

```



\### Step 3 — Start FastAPI with Kafka enabled



Open a new PowerShell terminal in the project directory and activate the virtual environment:



```powershell

.\\.venv\\Scripts\\Activate.ps1

$env:KAFKA\_ENABLED="true"

uvicorn app.main:app --reload

```



\### Step 4 — Start 3 Kafka consumers



Open another PowerShell terminal:



```powershell

.\\.venv\\Scripts\\Activate.ps1

$env:KAFKA\_CONSUMER\_COUNT="3"

python -m app.kafka.launcher

```



The launcher starts three consumer processes.



All consumers use the same consumer group, `trade-store-consumers`.



Kafka distributes the six topic partitions across these consumers.



\### Step 5 — Verify partition assignments



```powershell

docker exec dws-trade-kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group trade-store-consumers --members --verbose

```



Under normal operation, each of the three consumers should have two partitions assigned.



\### Step 6 — Test Kafka ingestion



Open Swagger UI:



http://127.0.0.1:8000/docs



Locate `POST /trades/kafka` and submit a valid trade using the request schema shown in Swagger.



The API should return HTTP 202 Accepted.



The Kafka consumer processes the message asynchronously and persists it in PostgreSQL.



Retrieve the trade using `GET /trades/{trade\_id}`.



\## 4. Option C — Use the Existing AWS Deployment



The Kafka-enabled application has been deployed to AWS EC2.



The deployment includes FastAPI, PostgreSQL, a Kafka broker, and three Kafka consumers.



The `trades.incoming` topic has six partitions.



\### Access



The FastAPI service currently listens on `127.0.0.1:8000` on the EC2 instance.



Therefore, it is not directly exposed through a public HTTP URL.



Authorized users can access it through SSH port forwarding:



```bash

ssh -i /path/to/authorized-key.pem -L 8000:127.0.0.1:8000 ubuntu@15.135.206.84

```



Then open:



http://localhost:8000/docs



The SSH private key is not included in the repository. Contact the project owner to arrange an authorized demonstration.



The EC2 instance uses Elastic IP 15.135.206.84, which remains stable across reboot and Stop/Start while associated.



\## 5. Test the Application



Open Swagger UI and execute the following operations:



| API | Purpose |

|---|---|

| `GET /health` | Verify application health |

| `POST /trades` | Create or update a trade |

| `GET /trades` | List stored trades |

| `GET /trades/{trade\_id}` | Retrieve a trade |

| `POST /trades/kafka` | Submit a trade asynchronously through Kafka |



Use the example request schema provided by Swagger UI.



The application implements trade version validation and maturity-date rules.



\## 6. Automated Tests



Activate the virtual environment and run:



```powershell

python -m pytest

```



To run coverage reporting:



```powershell

python -m pytest --cov=app --cov-report=term-missing

```



The GitHub Actions pipeline also runs regression tests and dependency vulnerability scanning.



CI/CD results:



https://github.com/mahen0202/dws-trade-store/actions



\## 7. Troubleshooting



\*\*Database connection failure:\*\* Confirm PostgreSQL is running, the database exists, and `.env` contains the correct credentials.



\*\*Port 8000 already in use:\*\* Stop the existing FastAPI process or run Uvicorn on a different port.



\*\*Kafka connection failure:\*\* Confirm Docker Desktop is running and the `dws-trade-kafka` container is healthy.



\*\*Kafka consumers not processing messages:\*\* Confirm Kafka topics exist, check consumer logs, and inspect consumer-group assignments.



\*\*AWS connection failure:\*\* Verify the current EC2 public IP, authorized SSH access, and security-group permissions.



\## 8. Deployment Notes



The `master` branch contains the original REST API implementation.



The `feature/kafka-ingestion` branch contains the Kafka enhancement and its AWS deployment configuration.



The GitHub Actions workflow includes automated testing, vulnerability scanning, and branch-specific AWS deployment jobs.



Deploying to a new AWS account requires configuring the EC2 instance, PostgreSQL, Docker, systemd services, GitHub Actions runner, and environment-specific secrets. These are not provisioned automatically by cloning the repository.



For architecture diagrams and implementation details, see the main README and `docs/` directory.

