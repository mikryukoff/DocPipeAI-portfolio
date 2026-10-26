# DocPipeAI — развёртывание и эксплуатация (сервер)

Этот документ для инженеров, которые **поднимают/обслуживают сервер** (Docker Compose, база, миграции, TLS reverse-proxy, бэкапы).

## 1) Требования
- Linux сервер (рекомендовано)
- Docker + Docker Compose
- Домен/поддомен (опционально) и открытый входящий порт (если нужен доступ извне)

## 2) Быстрый запуск (Docker Compose)
В репозитории есть `[docker-compose.yaml](../docker-compose.yaml)` со службами:
- `db` (MySQL 8)
- `adminer` (веб-интерфейс к БД)
- `backend` (FastAPI + встроенный фронтенд)

### 2.1 Подготовить `.env`
Создайте файл `.env` **в корне репозитория** рядом с `docker-compose.yaml`.

Минимальный пример для Compose (важно: `DB_HOST=db`):

```env
PROJECT_NAME=DocPipeAI
VERSION=1.0.0
ENVIRONMENT=production

DB_HOST=db
DB_PORT=3306
DB_NAME=docpipeai
DB_USER=docpipeai
DB_PASSWORD=change-me
DB_ROOT_PASSWORD=change-me-root

# Пути данных внутри контейнера; обычно их не меняют.
DATA_BASE_PATH=data
CONFIG_DATA_PATH=data/config
LOGS_OUTPUT_PATH=data/logs
WORD_TEMPLATE_PATH=data/raw/docx/passport_template.docx
WORD_OUTPUT_PATH=data/processed/structured_files/passports

# Security (поменять в проде!)
JWT_ACCESS_SECRET=change-me-access-secret
JWT_REFRESH_SECRET=change-me-refresh-secret
JWT_CHANGE_PASSWORD_SECRET=change-me-change-password-secret
JWT_MFA_SECRET=change-me-mfa-secret
FILE_ENCRYPTION_KEY=change-me-file-encryption-key
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=strict
DELETE_JOB_UPLOADS_AFTER_COMPLETION=true
DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD=true
REMOVE_SOURCE_AFTER_PROCESSING=true
BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START=false
ALLOW_PASSWORD_GENERATOR_ENDPOINT=false
```

Полный справочник переменных — в `[CONFIGURATION_REFERENCE_RU.md](CONFIGURATION_REFERENCE_RU.md)`.

### 2.2 Запуск

```bash
docker compose up -d --build
```

Что важно про порты:
- В текущем compose backend опубликован **только локально на сервере**: `127.0.0.1:8001 -> 8000`.
  Это сделано под схему “Nginx TLS снаружи”.

Проверка:
- MySQL: `127.0.0.1:3306` (привязан только к loopback)
- Adminer: `http://127.0.0.1:8080` (включается профилем `tools`: `docker compose --profile tools up -d`)
- Backend (локально на сервере): `http://127.0.0.1:8001`

## 3) Миграции БД (Alembic)
Entrypoint контейнера ждёт готовность БД и **может автоматически применять миграции**, если указать переменную:

```env
RUN_MIGRATIONS=true
```

Рекомендации:
- На первом запуске включите `RUN_MIGRATIONS=true`, затем можно выключить (или оставить включённым, если вам подходит авто-апгрейд схемы при старте).

## 4) HTTPS reverse-proxy (Nginx + TLS на нестандартном порту)
В репозитории есть готовый путь “TLS на `:8000` без `:80/:443`” (полезно, если 80/443 заняты или недоступны).

Пример (документационный IP из TEST-NET-3, не реальный хост): `https://203.0.113.10:8000` — A-записи `example.com` / `www.example.com` указывают на ваш сервер.

### 4.1 Как устроено
- `backend` слушает `127.0.0.1:8001` на сервере.
- Nginx принимает HTTPS на `:8000` и проксирует на `127.0.0.1:8001`.

### 4.2 Настройка скриптом
Скрипт установки:
- `[deploy/scripts/setup_https_nginx_certbot.sh](../deploy/scripts/setup_https_nginx_certbot.sh)`

Пример вызова:

```bash
sudo bash deploy/scripts/setup_https_nginx_certbot.sh \
  example.com www.example.com \
  127.0.0.1:8001 \
  /root/example.com.crt /root/example.com.key \
  8000
```

Проверочный скрипт:
- `[deploy/scripts/verify_https.sh](../deploy/scripts/verify_https.sh)`

```bash
bash deploy/scripts/verify_https.sh example.com www.example.com 203.0.113.10 8000
```

## 5) Bootstrap администратора (первый доступ)
При старте приложения создаётся/обновляется администратор из переменных окружения:
- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `BOOTSTRAP_ADMIN_ROLE` (обычно `admin`)
- `BOOTSTRAP_ADMIN_IS_ACTIVE`
- `BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START`

Рекомендации для прод-сервера:
- Задайте сильный пароль и храните `.env` вне git.
- После первого входа создайте “живых” пользователей через веб-интерфейс админки.
- Держите `BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START=false`, иначе приложение не запустится в `ENVIRONMENT=production`.

## 6) Бэкапы и восстановление
Что бэкапить:
- **База MySQL**: Docker volume `mysql_data`.
- **Файлы данных**: каталог `./data` (в compose монтируется в контейнер).

Минимальная стратегия:
- Регулярный дамп MySQL (например `mysqldump`) + архивирование `./data`.
- Хранить несколько точек восстановления.

## 7) Обслуживание и диагностика
- Серверные логи приложения смотрите через `docker logs docpipeai-backend`.
- Пользовательские диагностические логи лежат в `data/users/<login>/logs/`.
- Parsing-логи можно смотреть/выгружать из веб-админки.

