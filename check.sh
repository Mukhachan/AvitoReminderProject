#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

if [[ ! -x .venv/bin/python ]]; then
    echo "ОШИБКА: сначала выполните bash install.sh"
    exit 1
fi

export PYTHONUTF8=1
export PYTHONUNBUFFERED=1
exec .venv/bin/python -m avito_reminder.cli --all

