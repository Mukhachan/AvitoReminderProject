#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ОШИБКА: python3 не найден."
    echo "Для Raspberry Pi OS: sudo apt update && sudo apt install -y python3 python3-venv"
    exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo "ОШИБКА: требуется Python 3.11 или новее."
    exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
    echo "Создаю виртуальное окружение..."
    if ! "$PYTHON_BIN" -m venv .venv; then
        echo "Не удалось создать .venv. Установите: sudo apt install -y python3-venv"
        exit 1
    fi
fi

echo "Устанавливаю зависимости..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --upgrade -r requirements.txt

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Создан .env: Telegram через 127.0.0.1:20808, Avito напрямую. Добавьте токен."
else
    echo "Существующий .env сохранён без изменений."
fi

chmod 600 .env
mkdir -p data
chmod 700 data

echo
echo "Установка завершена."
echo "1. Заполните токен: nano .env"
echo "2. Проверьте VPN и API: bash check.sh"
echo "3. Тестовый запуск: bash start.sh"
echo "4. Автозапуск: bash service.sh install"
