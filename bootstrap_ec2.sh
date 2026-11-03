#!/usr/bin/env bash
# Rebuild the DWS Trade Store application stack on a fresh Ubuntu EC2 instance.
# Safe to rerun: does not drop the database or delete trade records.
set -Eeuo pipefail

REPO_URL="https://github.com/mahen0202/dws-trade-store.git"
APP_DIR="/home/ubuntu/dws-trade-store"
APP_USER="ubuntu"
DB_NAME="trade_store"
DB_USER="trade_app"
SERVICE_NAME="trade-store"
PYTHON_BIN="python3.12"
REGION_TZ="Asia/Kolkata"

log() { echo -e "\n[bootstrap] $*"; }
die() { echo "[bootstrap] ERROR: $*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run with sudo: sudo bash bootstrap_ec2.sh"
id "$APP_USER" >/dev/null 2>&1 || die "Expected Ubuntu EC2 user 'ubuntu' was not found."

# Determine the public IPv4 address for the self-signed certificate.
PUBLIC_IP="${PUBLIC_IP:-}"
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP="$(curl -4fsS --max-time 10 https://checkip.amazonaws.com | tr -d '[:space:]' || true)"
fi
[[ "$PUBLIC_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "Could not determine public IPv4. Re-run with: sudo PUBLIC_IP=x.x.x.x bash bootstrap_ec2.sh"

log "Installing operating-system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  git curl ca-certificates build-essential libpq-dev \
  postgresql postgresql-contrib nginx openssl \
  python3.12 python3.12-venv python3-pip

log "Preparing application source"
if [[ -d "$APP_DIR/.git" ]]; then
  sudo -u "$APP_USER" git -C "$APP_DIR" fetch origin
  sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard origin/master
else
  [[ ! -e "$APP_DIR" ]] || die "$APP_DIR exists but is not a Git repository; move it aside before continuing."
  sudo -u "$APP_USER" git clone --branch master "$REPO_URL" "$APP_DIR"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

log "Starting and enabling PostgreSQL"
systemctl enable --now postgresql

# Keep an existing .env unchanged. On a fresh server, create one with a random
# URL-safe password so it can safely be embedded in a SQLAlchemy URL.
if [[ ! -f "$APP_DIR/.env" ]]; then
  DB_PASSWORD="$(openssl rand -hex 24)"
  cat > "$APP_DIR/.env" <<EOF
DATABASE_URL=postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  unset DB_PASSWORD
  log "Created a new .env with a generated database password. Back it up securely."
else
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
fi

DATABASE_URL="$(grep -E '^DATABASE_URL=' "$APP_DIR/.env" | tail -n1 | cut -d= -f2-)"
[[ -n "$DATABASE_URL" ]] || die "DATABASE_URL is missing from $APP_DIR/.env"

# Extract password from the project's standard SQLAlchemy URL format.
DB_PASSWORD="$(printf '%s' "$DATABASE_URL" | sed -E 's#^[^:]+://[^:]+:([^@]+)@.*#\1#')"
[[ "$DB_PASSWORD" != "$DATABASE_URL" && -n "$DB_PASSWORD" ]] || die "Could not parse DB password from DATABASE_URL. Use a URL-safe password."

log "Ensuring PostgreSQL role and database exist (no data is dropped)"
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  --set=db_user="$DB_USER" --set=db_password="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user')
\gexec
ALTER ROLE :"db_user" WITH LOGIN PASSWORD :'db_password';
SQL

sudo -u postgres psql -v ON_ERROR_STOP=1 --set=db_name="$DB_NAME" --set=db_user="$DB_USER" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
SQL
unset DB_PASSWORD

log "Creating Python virtual environment and installing dependencies"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo -u "$APP_USER" "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

log "Initializing database schema without dropping existing tables"
sudo -u "$APP_USER" bash -c \
  "cd '$APP_DIR' && set -a && source .env && set +a && .venv/bin/python -c 'from app.database import Base, engine; from app.models import Trade; Base.metadata.create_all(bind=engine)'"

log "Creating HTTPS certificate (self-signed; browser trust warning is expected)"
install -d -m 755 /etc/nginx/ssl
if [[ ! -s /etc/nginx/ssl/trade-store.crt || ! -s /etc/nginx/ssl/trade-store.key ]]; then
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/trade-store.key \
    -out /etc/nginx/ssl/trade-store.crt \
    -subj "/CN=${PUBLIC_IP}" \
    -addext "subjectAltName=IP:${PUBLIC_IP}"
  chmod 600 /etc/nginx/ssl/trade-store.key
  chmod 644 /etc/nginx/ssl/trade-store.crt
fi

log "Installing Nginx reverse-proxy configuration"
cat > /etc/nginx/sites-available/trade-store <<EOF
server {
    listen 80;
    server_name ${PUBLIC_IP};
    return 301 https://\\$host\\$request_uri;
}

server {
    listen 443 ssl;
    server_name ${PUBLIC_IP};

    ssl_certificate /etc/nginx/ssl/trade-store.crt;
    ssl_certificate_key /etc/nginx/ssl/trade-store.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \\$host;
        proxy_set_header X-Real-IP \\$remote_addr;
        proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \\$scheme;
    }
}
EOF

ln -sfn /etc/nginx/sites-available/trade-store /etc/nginx/sites-enabled/trade-store
rm -f /etc/nginx/sites-enabled/default
nginx -t

log "Installing systemd service"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Deutsche Bank Trade Store API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
systemctl enable nginx
systemctl reload nginx

log "Waiting for application health check"
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health; then
    echo
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    journalctl -u "$SERVICE_NAME" -n 80 --no-pager
    die "Application did not become healthy. Check the service logs above."
  fi
  sleep 2
done

log "Bootstrap completed"
echo "API HTTPS URL: https://${PUBLIC_IP}/"
echo "Health check:  curl -k https://${PUBLIC_IP}/health"
echo "Swagger UI:    https://${PUBLIC_IP}/docs"
echo
echo "IMPORTANT:"
echo "1. Ensure the EC2 security group allows inbound TCP 80 and 443."
echo "2. Keep TCP 5432 private; do not expose PostgreSQL publicly."
echo "3. Back up .env and /etc/nginx/ssl/trade-store.key securely."
echo "4. This script does not register the GitHub Actions self-hosted runner."
echo "   Runner registration requires a fresh, short-lived GitHub token."
echo "5. This script preserves existing database records; it does not run migrations."
