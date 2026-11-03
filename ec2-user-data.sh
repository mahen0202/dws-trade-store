
#!/usr/bin/env bash
# EC2 User Data: first-boot automation for Trade Store.
# Runs as root through cloud-init on Ubuntu 24.04.

set -Eeuo pipefail

LOG_FILE="/var/log/trade-store-user-data.log"
exec > >(tee -a "$LOG_FILE") 2>&1

REPO_URL="https://github.com/mahen0202/dws-trade-store.git"
BRANCH="master"
APP_DIR="/home/ubuntu/dws-trade-store"

on_error() {
    status=$?
    echo "ERROR: Setup failed at line ${BASH_LINENO[0]} (exit ${status})."
    echo "Check ${LOG_FILE} and /var/log/cloud-init-output.log."
    exit "$status"
}
trap on_error ERR

echo "=== Trade Store first boot started: $(date -Is) ==="

export DEBIAN_FRONTEND=noninteractive

# Install Git and download prerequisites.
apt-get update
apt-get install -y git ca-certificates curl

# Clone the application repository.
if [[ -d "${APP_DIR}/.git" ]]; then
    git -C "${APP_DIR}" fetch origin "${BRANCH}"
    git -C "${APP_DIR}" checkout "${BRANCH}"
    git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
else
    install -d -o ubuntu -g ubuntu "$(dirname "${APP_DIR}")"
    git clone --branch "${BRANCH}" --single-branch \
        "${REPO_URL}" "${APP_DIR}"
fi

chown -R ubuntu:ubuntu "${APP_DIR}"

# Ensure the bootstrap script is available and executable.
if [[ ! -f "${APP_DIR}/bootstrap_ec2.sh" ]]; then
    echo "ERROR: bootstrap_ec2.sh not found."
    exit 1
fi

chmod +x "${APP_DIR}/bootstrap_ec2.sh"

# Run the main infrastructure bootstrap.
echo "=== Starting infrastructure bootstrap: $(date -Is) ==="
bash "${APP_DIR}/bootstrap_ec2.sh"

echo "=== Trade Store setup completed: $(date -Is) ==="
echo "Log file: ${LOG_FILE}"
