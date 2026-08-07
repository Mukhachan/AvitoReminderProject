# Avito Reminder 2.0

Telegram-бот сохраняет параметры поиска Avito, периодически проверяет выдачу и отправляет новые объявления в тот же чат. Проект обновлён для Python 3.11+ и aiogram 3.

## Возможности

- пошаговое создание поиска: запрос, город, цена от/до;
- короткая команда `/add Москва | iPhone 13 | 30000 | 50000`;
- несколько поисков на пользователя;
- кнопки проверки, паузы, возобновления и удаления;
- SQLite без отдельного сервера баз данных;
- защита от повторной отправки объявлений;
- повторные запросы, тайм-ауты и backoff;
- явное обнаружение блокировки IP/капчи Avito;
- диагностика и тесты;
- запуск напрямую или через Docker Compose.

## Быстрый запуск на Windows

Требуется Python 3.11 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Откройте `.env` и укажите новый токен, полученный у [@BotFather](https://t.me/BotFather):

```dotenv
TELEGRAM_BOT_TOKEN=123456:replace_me
```

В `.env.example` включён Raspberry Pi-профиль `TELEGRAM_PROXY=socks5://127.0.0.1:10808`.
Если на Windows такого локального SOCKS5 нет, оставьте `TELEGRAM_PROXY=` пустым.

Проверьте локальные компоненты и запустите бота:

```powershell
.\.venv\Scripts\python -m avito_reminder.cli
.\.venv\Scripts\python -m avito_reminder
```

Старый вариант запуска также поддерживается:

```powershell
.\.venv\Scripts\python bot.py
```

## Raspberry Pi / Linux-сервер

Рекомендуется 64-битная Raspberry Pi OS или Debian с Python 3.11+ и systemd.
Telegram использует тот же локальный SOCKS5-порт, что и Profi.ru Parser:

```dotenv
TELEGRAM_PROXY=socks5://127.0.0.1:10808
TELEGRAM_PROXY_RDNS=true
AVITO_HTTP_PROXY=
```

Таким образом, через VPN идёт только Telegram. Запросы Avito выполняются напрямую.

Установка:

```bash
cd ~/AvitoReminderProject
bash install.sh
nano .env
bash check.sh
bash start.sh
```

`bash check.sh` отдельно проверяет локальный SOCKS5, Telegram API и прямой запрос Avito.
До запуска проверки убедитесь, что VPN-сервис слушает порт:

```bash
ss -lnt | grep 10808
curl --proxy socks5h://127.0.0.1:10808 -I https://api.telegram.org
```

Для постоянной работы установите пользовательский systemd-сервис:

```bash
bash service.sh install
sudo loginctl enable-linger "$(whoami)"
bash service.sh status
```

Управление и журнал:

```bash
bash service.sh restart
bash service.sh logs
bash service.sh stop
```

Сервис автоматически перезапускается после ошибки и продолжает работать после закрытия SSH.

## Команды бота

- `/start` — главное меню;
- `/add` — пошаговое создание поиска;
- `/list` — все поиски пользователя;
- `/check 1` — немедленно проверить поиск №1;
- `/pause 1` и `/resume 1` — остановить или возобновить мониторинг;
- `/delete 1` — удалить поиск;
- `/cancel` — отменить ввод параметров.

По умолчанию первая проверка присылает не более пяти свежих результатов. Чтобы первая проверка только создала базовую отметку без сообщений, задайте `NOTIFY_INITIAL_RESULTS=false`.

## Проверка Avito

Локальная диагностика реального запроса:

```powershell
.\.venv\Scripts\python -m avito_reminder.cli --live --query "iPhone 13" --city Москва
```

Полная серверная проверка Telegram и Avito:

```bash
.venv/bin/python -m avito_reminder.cli --all
```

Avito может ограничивать автоматические запросы по IP и показывать капчу. Бот не обходит капчу: он сохраняет ошибку, сообщает пользователю и повторяет проверку позже. При необходимости можно указать собственный разрешённый прокси через `AVITO_HTTP_PROXY`. Не используйте публичные или чужие прокси.

## Тесты и качество

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\ruff check .
```

Тесты используют локальные HTML-фикстуры и временную SQLite — реальный Telegram и Avito не вызываются.

## Docker

```powershell
Copy-Item .env.example .env
# заполните TELEGRAM_BOT_TOKEN
docker compose up --build -d
docker compose logs -f bot
```

База хранится в `data/avito_reminder.db` и монтируется в контейнер. Compose использует
`network_mode: host`, чтобы адрес `127.0.0.1:10808` внутри контейнера указывал на VPN-сервис
самого Raspberry Pi. На сервере предпочтителен systemd-вариант: он проще для диагностики.

## Безопасность

Реальные токены, пароли, cookie и адреса прокси должны находиться только в `.env`. Старые секреты ранее были записаны в историю Git — их необходимо заменить у соответствующих провайдеров. Простого удаления из текущего `config.py` недостаточно для уже опубликованной истории.

## Структура

- `avito_reminder/avito.py` — URL, HTTP-клиент и разбор выдачи;
- `avito_reminder/database.py` — SQLite и дедупликация;
- `avito_reminder/telegram.py` — команды и сценарий ввода;
- `avito_reminder/service.py` — планировщик и уведомления;
- `avito_reminder/app.py` — сборка и запуск приложения;
- `TESTS/test_*.py` — автоматические тесты новой версии.
