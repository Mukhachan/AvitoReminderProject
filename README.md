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
- гибридный парсинг: изолированные Chromium-сессии, MFE JSON и JSON-пагинация Avito;
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
AVITO_BROWSER_STEALTH=true
AVITO_BROWSER_SNAPSHOTS=true
AVITO_IDENTITY_ROTATE_ON_BLOCK=true
AVITO_NEW_USER_PER_SESSION=true
AVITO_IDENTITY_ROTATE_ON_BROWSER_START=true
AVITO_BROWSER_LOCALE=ru-RU
AVITO_BROWSER_TIMEZONE=Europe/Moscow
AVITO_PAGE_RELOAD_DELAY_SECONDS=90
AVITO_PAGE_RELOAD_JITTER_SECONDS=30
AVITO_ERROR_RELOAD_ATTEMPTS=3
AVITO_COOLDOWN_SECONDS=10800
AVITO_PROXY_MODE=fallback
AVITO_PROXY=
AVITO_PROXY_POOL_FILE=data/avito_proxies.txt
AVITO_PROXY_ROTATION_ENABLED=true
AVITO_PROXY_ROTATE_AFTER_RELOADS=1
AVITO_PROXY_ROTATION_DELAY_SECONDS=15
AVITO_PROXY_MAX_ROTATIONS=5
AVITO_PROXY_ROTATE_ON_BROWSER_START=true
AVITO_LOG_PUBLIC_IP=true
AVITO_PROXY_RDNS=true
```

Telegram всегда работает через Naive/SOCKS5. Avito открывается установленным Chromium через
обычное подключение Raspberry Pi, а внешний прокси подключается только после подтверждённой
блокировки. Browser identity эфемерна: сохранённый
`data/chromium-profile/avito-browser-identity.json` не загружается.
Каждая логическая проверка получает новый `BrowserContext` без cookies, local/session storage,
IndexedDB, Cache Storage и Service Workers предыдущей проверки. Перед выдачей браузер открывает
`https://www.avito.ru/`, а затем переходит на поисковую ссылку в той же временной сессии с referer
главной страницы. По окончании проверки контекст закрывается и его состояние отбрасывается.
При `AVITO_NEW_USER_PER_SESSION=true` перед второй и каждой следующей проверкой дополнительно
закрываются процесс Chromium и HTTP-сессия. Новый запуск получает новую identity, а при доступной
ротации — следующий sticky-прокси. В режиме `direct` процесс и identity меняются, но внешний IP
остаётся прежним.
Между последовательными поисками выдерживается глобальная пауза 60–90 секунд, поэтому несколько
подписок не создают пачку одновременных обращений к Avito.

После успешной загрузки первой страницы бот использует алгоритм, адаптированный из
`Duff89/parser_avito`:

1. извлекает структурированный каталог, `searchCore` и `context` из
   `script[type="mime/invalid"][data-mfe-state="true"]`;
2. перед JSON-запросами переносит актуальные cookies из Chromium в `curl_cffi`, а полученные
   `Set-Cookie` возвращает в текущую изолированную сессию;
3. при необходимости получает страницы 2–3 через `/web/1/js/items`;
4. использует один согласованный набор User-Agent, client hints, viewport, locale и Chrome
   TLS/HTTP-отпечатка в пределах одного запуска Chromium;
5. при изменении внутреннего JSON Avito возвращается к разбору HTML-карточек первой страницы.

`AVITO_API_MAX_PAGES` ограничивает нагрузку внутренней пагинации. `AVITO_HTTP_IMPERSONATE`
лучше оставлять равным `chrome`: случайная смена Chrome/Safari/Firefox при тех же cookies
создавала бы противоречивый отпечаток. Для общего значения `chrome` парсер автоматически
выбирает точную поддерживаемую `curl_cffi` версию, соответствующую `AVITO_USER_AGENT`.
При `AVITO_IDENTITY_ROTATE_ON_BROWSER_START=true` каждый фактический запуск Chromium создаёт
новую эфемерную identity и выбирает новый согласованный viewport. Это относится и к первому
запуску процесса, и к автоматическому восстановлению после закрытия окна. Старый
`avito-browser-identity.json`, если он остался от предыдущей версии, игнорируется.
`AVITO_BROWSER_STEALTH=true` скрывает стандартные признаки Playwright и согласует JS-параметры
с identity текущего запуска. Автоматическое решение капчи не используется.

`AVITO_BROWSER_SNAPSHOTS=true` сохраняет для каждой успешной проверки JSON со значениями
`navigator`, timezone, viewport, screen, IndexedDB, Cache Storage и Service Workers в
`data/diagnostics/browser-sessions/`. Снимки можно сравнивать функцией
`diff_browser_snapshots` из `avito_reminder.browser_sessions`; storage-маркеры проверяются
функциями `inspect_browser_storage` и `storage_leaks`.

### Ротация IP Avito

Для браузера используйте sticky-сессии: один IP должен оставаться стабильным во время полной
загрузки главной страницы, поисковой выдачи и внутренних JSON-запросов. Сгенерируйте у провайдера
несколько российских sticky-прокси в формате `http://user:pass@host:port`. Не помещайте пароль
в `.env` по одной строке: отдельный файл проще защитить и обновлять.

На Raspberry Pi:

```bash
cd ~/Документы/AvitoReminderProject
cp avito_proxies.example.txt data/avito_proxies.txt
nano data/avito_proxies.txt
chmod 600 data/avito_proxies.txt
```

В `data/avito_proxies.txt` должен находиться один полный URL прокси на строку. Комментарии с `#`
и пустые строки пропускаются. Каталог `data/` исключён из Git, поэтому файл с паролями не попадёт
в репозиторий.

В `.env` включите:

```dotenv
AVITO_PROXY_MODE=fallback
AVITO_PROXY_POOL_FILE=data/avito_proxies.txt
AVITO_PROXY_ROTATION_ENABLED=true
AVITO_PROXY_ROTATE_AFTER_RELOADS=1
AVITO_PROXY_ROTATION_DELAY_SECONDS=15
AVITO_PROXY_MAX_ROTATIONS=5
AVITO_PROXY_ROTATE_ON_BROWSER_START=true
```

`fallback` сначала использует обычный IP Raspberry Pi. Если Avito показал блокировку, парсер
один раз ждёт случайные 90–120 секунд и обновляет страницу. При повторной блокировке он очищает
заблокированные cookies, local/session storage, Cache Storage и IndexedDB, создаёт новую
согласованную identity, закрывает Chromium и HTTP-сессию, выбирает следующий прокси, ждёт
15 секунд и заново открывает Avito. После пяти неудачных смен IP включается общая пауза на три часа.
Режим `proxy` при каждом запуске процесса начинает со случайного прокси. При
`AVITO_PROXY_ROTATE_ON_BROWSER_START=true` следующий фактический запуск Chromium получает
следующий endpoint пула (и вызывает `AVITO_PROXY_CHANGE_URL`, если он задан). Уже подготовленный
после блокировки endpoint второй раз не переключается. В режиме `direct` пул полностью отключён.

На странице `https://www.avito.ru/#block` с заголовком «Доступ ограничен: проблема с IP» парсер
ждёт 90–120 секунд и один раз обновляет ту же вкладку. Если проблема исчезла, проверка продолжится
с текущим пользователем и IP; если осталась — Chromium и сетевые сессии закрываются, создаётся
новая identity и выбирается следующий IP пула. Страницы с текстом «Блокировка IP» и капча не
ожидаются и не обновляются: для них новый пользователь и прокси создаются сразу.

Если на странице появилась кнопка «Нажмите для подтверждения» или другой признак капчи, бот
отправляет отдельное сообщение с инструкцией открыть Chromium и пройти проверку. В видимом режиме
на подтверждение остаётся текущее окно браузера; в headless-режиме сообщение содержит команду
остановки сервиса и запуска `--setup-browser`. После ожидания 90–120 секунд парсер автоматически
обновляет страницу.

Чтобы парсер с самого запуска не использовал обычный IP и сразу открыл Avito через пул, замените
только одну строку в `.env`:

```dotenv
AVITO_PROXY_MODE=proxy
```

В этом режиме наличие `AVITO_PROXY` или непустого `AVITO_PROXY_POOL_FILE` проверяется при старте.
При каждом новом запуске бота первый Chromium получает случайный адрес из списка; при блокировке
парсер последовательно переключается на следующие адреса по тому же алгоритму. Вернуть
первоначальную схему можно значением `AVITO_PROXY_MODE=fallback`.

Chromium создаёт одну вкладку в новом изолированном контексте для каждой проверки. Если
прокси не смог выполнить первый переход и вкладка после тайм-аута осталась `about:blank`, парсер
не тратит время на снимок пустой страницы: сетевой контекст закрывается и сразу выбирается
следующий IP пула. Обычный диагностический снимок ограничен пятью секундами.

В видимом режиме перед первым ответом отображается страница «Подключение к Avito». Навигация
сначала ждёт получения ответа от сервера, а загрузку DOM — отдельным ограниченным этапом. Полоса
Chromium про `--no-sandbox` является предупреждением стандартного запуска Playwright на Linux,
а не ошибкой Avito или прокси; состояние маршрута следует смотреть в журнале бота.

Если пользователь закрыл видимое окно Chromium или процесс браузера аварийно завершился, бот
сбрасывает закрытую сессию и один раз автоматически запускает Chromium заново с новой identity
и, если доступна ротация, со следующим прокси/IP. Перезапуск всего Telegram-бота для следующей
проверки не требуется. После
успешного поиска вкладка и её `BrowserContext` закрываются; сам процесс Chromium может обслужить
следующую проверку уже в новом чистом контексте.

Если провайдер выдаёт один прокси-шлюз и отдельный секретный URL для принудительной смены IP,
можно дополнительно задать `AVITO_PROXY_CHANGE_URL`. Парсер вызовет его непосредственно перед
перезапуском Chromium. В штатной строке маршрута не выводятся значение секретного URL, логин и
пароль прокси: в журнале остаются только схема, хост и порт.

При `AVITO_LOG_PUBLIC_IP=true` после запуска Chromium и каждой смены прокси выполняется короткая
проверка через ipify. В журнал записываются фактический публичный IP и безопасная метка маршрута
без логина и пароля. Недоступность сервиса определения IP не останавливает поиск. В режиме
ротации «на каждый запрос» проверочный IP может отличаться от IP следующего обращения к Avito;
для sticky-сессий он остаётся тем же.
При запуске также выводятся безопасный `identity` ID, viewport и точный `curl_cffi` impersonate;
после JSON-запросов журнал показывает количество cookies, перенесённых в каждом направлении,
без вывода имён и значений cookies.

Установка:

```bash
cd ~/AvitoReminderProject
bash install.sh
nano .env
bash check.sh
bash start.sh
```

`bash check.sh` отдельно проверяет локальный SOCKS5, Telegram API, запуск Chromium, количество
настроенных Avito-прокси и открытие страницы Avito по текущему маршруту.
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

Если Avito показывает «Доступ ограничен: проблема с IP», остановите сервис и откройте временную
видимую Chromium-сессию:

```bash
bash service.sh stop
.venv/bin/python -m avito_reminder.cli --setup-browser
bash service.sh start
```

В браузере нажмите «Продолжить» и завершите предложенную Avito проверку. Режим не обходит
капчу автоматически: проверку выполняет пользователь. Если после неё страница по-прежнему
сообщает о проблеме с IP, смените публичный IP обычного подключения (например, перезапустите
роутер при динамическом IP) либо дождитесь снятия ограничения.

Успешно загруженная страница читается сразу: Chromium не ждёт 90–120 секунд и не обновляет её.
Если Avito вернул ошибку, блокировку или капчу, вкладка остаётся открытой, парсер ждёт
90–120 секунд и делает повторное обновление. Цикл повторяется только пока сохраняется ошибка. Первый
снимок сохраняется только локально в `data/diagnostics`; в Telegram скриншоты не отправляются. После восстановления
главной страницы парсер сразу переходит к текущему поиску. После трёх неудачных перезагрузок
подряд без настроенной ротации все обращения к Avito приостанавливаются на 10800 секунд (3 часа).
С настроенным пулом блокировка сначала запускает последовательную смену IP; общая пауза включается
после исчерпания `AVITO_PROXY_MAX_ROTATIONS`. После паузы мониторинг возобновляется автоматически.
Бот не обходит капчу автоматически;
в видимом режиме её можно завершить вручную. Для прежнего HTTP-клиента
можно вручную задать `AVITO_TRANSPORT=http`; `AVITO_TRANSPORT=browser` отключает только
JSON-пагинацию. Основной серверный режим — `hybrid`.
`AVITO_PROXY_MODE=direct` гарантирует, что Avito не использует ни Naive, ни внешний пул.

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
- `avito_reminder/browser_sessions.py` — фабрика изолированных сессий, snapshot и storage-аудит;
- `avito_reminder/avito_mfe.py` — разбор MFE-состояния и внутренней JSON-пагинации;
- `avito_reminder/database.py` — SQLite и дедупликация;
- `avito_reminder/telegram.py` — команды и сценарий ввода;
- `avito_reminder/service.py` — планировщик и уведомления;
- `avito_reminder/app.py` — сборка и запуск приложения;
- `TESTS/test_*.py` — автоматические тесты новой версии.
