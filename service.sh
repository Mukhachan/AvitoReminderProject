#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SERVICE_NAME="avito-reminder.service"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_FILE="$SYSTEMD_USER_DIR/$SERVICE_NAME"

require_systemd() {
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "ОШИБКА: systemd не найден. Используйте bash start.sh"
        exit 1
    fi
}

install_service() {
    require_systemd
    if [[ ! -x "$PROJECT_DIR/.venv/bin/python" || ! -f "$PROJECT_DIR/.env" ]]; then
        echo "ОШИБКА: сначала выполните bash install.sh и заполните .env"
        exit 1
    fi

    mkdir -p "$SYSTEMD_USER_DIR"
    umask 077
    {
        echo "[Unit]"
        echo "Description=Avito Reminder Telegram bot"
        echo "Wants=network-online.target"
        echo "After=network-online.target"
        echo
        echo "[Service]"
        echo "Type=simple"
        printf 'WorkingDirectory="%s"\n' "$PROJECT_DIR"
        printf 'EnvironmentFile="%s/.env"\n' "$PROJECT_DIR"
        printf 'ExecStart="%s/.venv/bin/python" -m avito_reminder\n' "$PROJECT_DIR"
        echo "Restart=always"
        echo "RestartSec=10"
        echo "TimeoutStopSec=30"
        echo "KillSignal=SIGINT"
        echo "NoNewPrivileges=true"
        echo "PrivateTmp=true"
        echo "RestrictSUIDSGID=true"
        echo "RestrictRealtime=true"
        echo "Environment=PYTHONUTF8=1"
        echo "Environment=PYTHONUNBUFFERED=1"
        echo "UMask=0077"
        echo
        echo "[Install]"
        echo "WantedBy=default.target"
    } >"$UNIT_FILE"

    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    echo "Сервис установлен и запущен."
    echo "Статус: bash service.sh status"
    echo "Логи:   bash service.sh logs"

    if command -v loginctl >/dev/null 2>&1; then
        linger="$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || true)"
        if [[ "$linger" != "yes" ]]; then
            echo "Для запуска после перезагрузки выполните один раз:"
            echo "sudo loginctl enable-linger $USER"
        fi
    fi
}

case "${1:-status}" in
    install)
        install_service
        ;;
    start|stop|restart)
        require_systemd
        systemctl --user "$1" "$SERVICE_NAME"
        ;;
    status)
        require_systemd
        systemctl --user status "$SERVICE_NAME" --no-pager
        ;;
    logs)
        require_systemd
        journalctl --user -u "$SERVICE_NAME" -f
        ;;
    uninstall)
        require_systemd
        systemctl --user disable --now "$SERVICE_NAME" 2>/dev/null || true
        rm -f -- "$UNIT_FILE"
        systemctl --user daemon-reload
        echo "Сервис удалён; данные и .env сохранены."
        ;;
    *)
        echo "Использование: bash service.sh {install|start|stop|restart|status|logs|uninstall}"
        exit 2
        ;;
esac
