# Avito Reminder 2.0

Telegram-бот сохраняет параметры поиска Avito, периодически проверяет выдачу и отправляет новые объявления в тот же чат. Проект обновлён для Python 3.11+ и aiogram 3.

## Возможности

- пошаговый мастер: товар, город, цена от/до, интервал и подтверждение;
- короткая команда `/add Москва | iPhone 13 | 30000 | 50000`;
- несколько поисков на пользователя;
- индивидуальный интервал проверки для каждого поиска;
- кнопки открытия Avito, проверки, паузы, возобновления и безопасного удаления;
- сводка состояния активных, приостановленных и ошибочных поисков;
- SQLite без отдельного сервера баз данных;
- защита от повторной отправки объявлений;
- повторные запросы, тайм-ауты и backoff;
- гибридный парсинг: постоянный профиль Chromium, MFE JSON и JSON-пагинация Avito;
- явное обнаружение блокировки IP/капчи Avito;
- диагностика и тесты;
- запуск напрямую или через Docker Compose.

## Быстрый запуск на Windows

Требуется Python 3.11 или новее.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m playwright install chromium
Copy-Item .env.example .env
```

Откройте `.env` и укажите новый токен, полученный у [@BotFather](https://t.me/BotFather):

```dotenv
TELEGRAM_BOT_TOKEN=123456:replace_me
```

В `.env.example` включён Raspberry Pi-профиль с SOCKS5 на `127.0.0.1:20808`.
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
TELEGRAM_PROXY=socks5://127.0.0.1:20808
TELEGRAM_PROXY_RDNS=true
AVITO_TRANSPORT=hybrid
AVITO_HTTP_IMPERSONATE=chrome
AVITO_API_MAX_PAGES=3
AVITO_BROWSER_HEADLESS=true
AVITO_BROWSER_PROFILE_PATH=data/chromium-profile
AVITO_PAGE_RELOAD_DELAY_SECONDS=90
AVITO_ERROR_RELOAD_ATTEMPTS=3
AVITO_COOLDOWN_SECONDS=10800
AVITO_PROXY_MODE=direct
AVITO_PROXY=
AVITO_PROXY_RDNS=true
```

Telegram всегда работает через Naive/SOCKS5. Avito открывается установленным Chromium через
обычное подключение Raspberry Pi и не использует VPN. Профиль Chromium сохраняется между
запусками в `data/chromium-profile`. Перед выдачей браузер открывает `https://www.avito.ru/`,
а затем переходит на поисковую ссылку в той же вкладке с cookies и referer главной страницы.
Между последовательными поисками выдерживается глобальная пауза 60–90 секунд, поэтому несколько
подписок не создают пачку одновременных обращений к Avito.

После успешной загрузки первой страницы бот использует алгоритм, адаптированный из
`Duff89/parser_avito`:

1. извлекает структурированный каталог, `searchCore` и `context` из
   `script[type="mime/invalid"][data-mfe-state="true"]`;
2. синхронизирует cookies постоянного Chromium-профиля с одной долгоживущей сессией
   `curl_cffi`;
3. при необходимости получает страницы 2–3 через `/web/1/js/items`;
4. сохраняет один стабильный Chrome TLS/HTTP-отпечаток на весь процесс;
5. при изменении внутреннего JSON Avito возвращается к разбору HTML-карточек первой страницы.

`AVITO_API_MAX_PAGES` ограничивает нагрузку внутренней пагинации. `AVITO_HTTP_IMPERSONATE`
лучше оставлять равным `chrome`: случайная смена Chrome/Safari/Firefox при тех же cookies
создавала бы противоречивый отпечаток. Внешние cookies, автоматическое решение капчи и смена IP
не используются.

Установка:

```bash
cd ~/AvitoReminderProject
bash install.sh
nano .env
bash check.sh
bash start.sh
```

`bash check.sh` отдельно проверяет локальный SOCKS5, Telegram API, запуск Chromium и прямое
открытие страницы Avito.
До запуска проверки убедитесь, что VPN-сервис слушает порт:

```bash
ss -lnt | grep 20808
curl --proxy socks5h://127.0.0.1:20808 -I https://api.telegram.org
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

- `/menu` — вернуться в главное меню;
- `/start` — главное меню;
- `/add` — пошаговое создание поиска;
- `/list` — все поиски пользователя;
- `/status` — сводка по активным и приостановленным поискам;
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

Если Avito показывает «Доступ ограничен: проблема с IP», остановите сервис и откройте тот же
постоянный профиль в видимом Chromium:

```bash
bash service.sh stop
.venv/bin/python -m avito_reminder.cli --setup-browser
bash service.sh start
```

В браузере нажмите «Продолжить» и завершите предложенную Avito проверку. Режим не обходит
капчу автоматически: проверку выполняет пользователь. Если после неё страница по-прежнему
сообщает о проблеме с IP, смените публичный IP обычного подключения (например, перезапустите
роутер при динамическом IP) либо дождитесь снятия ограничения.

Успешно загруженная страница читается сразу: Chromium не ждёт 90 секунд и не обновляет её.
Если Avito вернул ошибку, блокировку или капчу, вкладка остаётся открытой, парсер ждёт
90 секунд и делает повторное обновление. Цикл повторяется только пока сохраняется ошибка. Первый
снимок сохраняется только локально в `data/diagnostics`; в Telegram скриншоты не отправляются. После восстановления
главной страницы парсер сразу переходит к текущему поиску. После трёх неудачных перезагрузок
подряд все обращения к Avito приостанавливаются на 10800 секунд (3 часа). После паузы мониторинг
возобновляется автоматически. Бот не обходит капчу автоматически;
в видимом режиме её можно завершить вручную. Для прежнего HTTP-клиента
можно вручную задать `AVITO_TRANSPORT=http`; `AVITO_TRANSPORT=browser` отключает только
JSON-пагинацию. Основной серверный режим — `hybrid`.
`AVITO_PROXY_MODE=direct` гарантирует, что HTTP-режим также не использует Naive.

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
`network_mode: host`, чтобы адрес `127.0.0.1:20808` внутри контейнера указывал на VPN-сервис
самого Raspberry Pi. На сервере предпочтителен systemd-вариант: он проще для диагностики.

## Безопасность

Реальные токены, пароли, cookie и адреса прокси должны находиться только в `.env`. Старые секреты ранее были записаны в историю Git — их необходимо заменить у соответствующих провайдеров. Простого удаления из текущего `config.py` недостаточно для уже опубликованной истории.

## Структура

- `avito_reminder/avito.py` — Chromium/HTTP-клиент, URL и управление выдачей;
- `avito_reminder/avito_mfe.py` — разбор MFE-состояния и внутренней JSON-пагинации;
- `avito_reminder/database.py` — SQLite и дедупликация;
- `avito_reminder/telegram.py` — команды и сценарий ввода;
- `avito_reminder/service.py` — планировщик и уведомления;
- `avito_reminder/app.py` — сборка и запуск приложения;
- `TESTS/test_*.py` — автоматические тесты новой версии.
