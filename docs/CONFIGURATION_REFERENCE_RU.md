# DocPipeAI — справочник конфигурации (.env)

Система читает переменные окружения из файла `.env` в корне проекта (или из окружения контейнера).

Ниже — справочник ключей, сгруппированный по смыслу. Если ключ не указан, может применяться значение по умолчанию (указано в описании).

## 1) Базовые параметры приложения
- `PROJECT_NAME` (**обязательно**): отображаемое имя проекта.
- `VERSION` (**обязательно**): версия (строка).
- `ENVIRONMENT` (по умолчанию: `production`): режим запуска конфигурации.
  - В `production` приложение блокирует старт с дефолтными секретами и небезопасными флагами.
  - Для локальной разработки/тестов обычно задают `development` или `test`.

## 2) Подключение к базе данных (MySQL)
- `DB_HOST` (**обязательно**): хост БД.
  - Для Docker Compose обычно `db`.
  - Для локального запуска обычно `localhost`.
- `DB_PORT` (**обязательно**): порт БД (обычно `3306`).
- `DB_NAME` (**обязательно**): имя базы (например `docpipeai`).
- `DB_USER` (**обязательно**): пользователь БД.
- `DB_PASSWORD` (**обязательно**): пароль БД.
- `DB_ROOT_PASSWORD` (используется в `docker-compose.yaml`): пароль `root` для MySQL.

## 3) Пути данных и файлов (хранилище)
Эти пути используются для хранения загруженных файлов, промежуточных результатов и выходных документов.

- `DATA_BASE_PATH` (по умолчанию: `data`): корень данных.
  Внутри, например, `data/users/<login>/...`.
- `CONFIG_DATA_PATH` (по умолчанию: `data/config`): общие конфиги/маппинги.
- `LOGS_OUTPUT_PATH` (**обязательно**, без дефолта): каталог для логов приложения.

### PDF таблицы / промежуточные данные
- `DRAWINGS_PDF_PATH` (**обязательно**): каталог/путь входных PDF (если используется режим чтения из диска).
- `DRAWINGS_OUTPUT` (**обязательно**): куда сохранять извлечённые таблицы/результаты (interim).

### OCR / извлечение текста
- `OCR_PDF_PATH` (**обязательно**): каталог/путь входных PDF для OCR-ветки.
- `OCR_OUTPUT` (**обязательно**): каталог вывода текстов (interim).
- `MODE` (по умолчанию: `PRODUCTION`): режим работы (используется в OCR настройках).
- `OLLAMA_HOST` (по умолчанию: `http://localhost:11434`): адрес Ollama (если включены OCR-интеграции).
- `POPPLER_PATH` (по умолчанию: пусто): путь к poppler (если требуется для конвертации PDF в изображения на Windows).
- `OCR_CROP_OUTPUT_PATH` (по умолчанию: `data/ocr/crop_page`): куда писать crop-изображения.
- `OCR_PARSED_OUTPUT_PATH` (по умолчанию: `data/ocr/parsed_texts`): куда писать распознанные тексты/JSON. Файлы `*.json` в этом каталоге также используются для **сопоставления закладных с группами на чертеже**: у каждого номера (ключ объекта) задаются связанные номера в поле **`alias`**. Если вы правите эти JSON на диске, чтобы приложение перечитало карту чертежей, обычно достаточно **перезапустить процесс** сервера (кэш загрузки JSON держится в памяти до рестарта).

### Excel
- `EXCEL_INPUT_PATH` (по умолчанию: `data/raw/excel`): каталог входных Excel (если используется работа с диском).
- `EXCEL_PREVIEW_OUTPUT_PATH` (по умолчанию: `data/interim/excel_inspect`): каталог предпросмотра/диагностики Excel.

### Выходные “структурированные” файлы
- `JSON_OUTPUT_PATH` (**обязательно**): путь до общего JSON-выхода (если используется).
- `EXCEL_OUTPUT_PATH` (**обязательно**): путь до общего Excel-выхода (если используется).
- `PIPELINES_PAGES_PATH` (**обязательно**): путь до файла страниц/пайплайнов (если используется).

### Генерация паспортов (Word)
- `WORD_TEMPLATE_PATH` (**обязательно**): путь к шаблону `.docx` паспорта.
- `WORD_OUTPUT_PATH` (**обязательно**): каталог, куда сохраняются сформированные паспорта (до выдачи/скачивания).

## 4) Очистка файлов (операционные флаги)
- `DELETE_JOB_UPLOADS_AFTER_COMPLETION`:
  - `production`: по умолчанию `true`
  - прочие среды: по умолчанию значение `REMOVE_SOURCE_AFTER_PROCESSING`
- `DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD`:
  - `production`: по умолчанию `true`
  - прочие среды: по умолчанию значение `REMOVE_SOURCE_AFTER_PROCESSING`
- `REMOVE_SOURCE_AFTER_PROCESSING` (legacy):
  - `production`: по умолчанию `true`
  - прочие среды: по умолчанию `false`

## 5) Логирование
- `LOG_BODY_ENABLED` (по умолчанию: `false`): логировать ли тела запросов.
- `LOG_VERBOSE_HTTP` (по умолчанию: `false`): расширенный HTTP-лог (headers/cookies/body). Для прода обычно `false`.

## 6) Безопасность и авторизация
### JWT secrets (рекомендуется **обязательно** задавать в проде)
- `JWT_ACCESS_SECRET` (по умолчанию: `change-me-access-secret`)
- `JWT_REFRESH_SECRET` (по умолчанию: `change-me-refresh-secret`)
- `JWT_CHANGE_PASSWORD_SECRET` (по умолчанию: `change-me-change-password-secret`)
- `JWT_MFA_SECRET` (по умолчанию: `change-me-mfa-secret`)

### JWT TTL
- `JWT_ACCESS_TTL_MIN` (по умолчанию: `15`)
- `JWT_REFRESH_TTL_DAYS` (по умолчанию: `7`)
- `JWT_CHANGE_PASSWORD_TTL_MIN` (по умолчанию: `10`)
- `JWT_MFA_TTL_MIN` (по умолчанию: `5`)

### Прочее
- `FILE_ENCRYPTION_KEY` (по умолчанию: `insecure-dev-key`): ключ шифрования файлов на диске.
  В проде обязательно задайте свой.
- `AUTH_COOKIE_SECURE`:
  - `production`: по умолчанию `true`
  - прочие среды: по умолчанию `false`
- `AUTH_COOKIE_SAMESITE`:
  - `production`: по умолчанию `strict`
  - прочие среды: по умолчанию `lax`
- `ALLOW_PASSWORD_GENERATOR_ENDPOINT`:
  - `production`: по умолчанию `false`
  - прочие среды: по умолчанию `true`
- `TEMP_PASSWORD_LEN` (по умолчанию: `12`): длина временного пароля при создании пользователя админом.
- `DEMO_DOWNLOAD_LIMIT` (по умолчанию: `20`): лимит скачиваний паспортов для demo-роли.
- `DEMO_PERIOD_DAYS` (по умолчанию: `7`): окно учёта лимита demo.

### Rate limit логина
- `LOGIN_ATTEMPTS_LIMIT` (по умолчанию: `5`)
- `LOGIN_WINDOW_MIN` (по умолчанию: `15`)
- `LOGIN_BLOCK_MIN` (по умолчанию: `30`)

## 7) Bootstrap admin (первый доступ / восстановление)
При старте приложение создаёт/обновляет администратора по этим ключам:
- `BOOTSTRAP_ADMIN_USERNAME` (по умолчанию: `admin`)
- `BOOTSTRAP_ADMIN_PASSWORD` (по умолчанию: `admin12345!`)
- `BOOTSTRAP_ADMIN_ROLE` (по умолчанию: `admin`)
- `BOOTSTRAP_ADMIN_IS_ACTIVE` (по умолчанию: `true`)
- `BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START`:
  - `production`: по умолчанию `false` (и обязателен `false`)
  - прочие среды: по умолчанию `true`

Рекомендация: в проде **обязательно** переопределить `BOOTSTRAP_ADMIN_PASSWORD` и затем выставить `BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START=false`, чтобы пароль админа не перезаписывался на каждом старте.

## 8) Валидация загрузок (размер и MIME)
- `MAX_UPLOAD_SIZE_MB` (по умолчанию: `50`): максимальный размер загрузки.
- `ALLOWED_MIME_PDF` (по умолчанию: `application/pdf`)
- `ALLOWED_MIME_EXCEL` (по умолчанию включает основные MIME для `.xls/.xlsx/.xlsm`)
- `ALLOWED_MIME_ARCHIVE` (по умолчанию включает zip/rar + несколько “generic” типов)

## 9) Миграции БД при старте контейнера
- `RUN_MIGRATIONS` (по умолчанию: `false`): если `true`, контейнер при старте выполнит `alembic upgrade head`.

