import os


def _set_default_env(name: str, value: str) -> None:
    if not os.getenv(name):
        os.environ[name] = value


# Минимальные значения переменных окружения, чтобы загрузка конфига не падала в тестах.
_set_default_env("PROJECT_NAME", "DocPipeAI")
_set_default_env("VERSION", "test")
_set_default_env("ENVIRONMENT", "test")
_set_default_env("DB_HOST", "localhost")
_set_default_env("DB_PORT", "3306")
_set_default_env("DB_NAME", "docpipeai_test")
_set_default_env("DB_USER", "test")
_set_default_env("DB_PASSWORD", "test")
_set_default_env("DRAWINGS_PDF_PATH", "data/raw/pdf")
_set_default_env("DRAWINGS_OUTPUT", "data/interim/tables_output")
_set_default_env("OCR_PDF_PATH", "data/raw/pdf")
_set_default_env("OCR_OUTPUT", "data/interim/text_output")
_set_default_env("JSON_OUTPUT_PATH", "data/processed/structured_files/pipelines_structured.json")
_set_default_env("EXCEL_OUTPUT_PATH", "data/processed/structured_files/pipelines_structured.xlsx")
_set_default_env("PIPELINES_PAGES_PATH", "data/processed/pipeline_pages/pipeline_pages.txt")
_set_default_env("WORD_TEMPLATE_PATH", "data/raw/docx/passport_template.docx")
_set_default_env("WORD_OUTPUT_PATH", "data/processed/structured_files/passports")
_set_default_env("LOGS_OUTPUT_PATH", "data/logs")
_set_default_env("DATA_BASE_PATH", "data")
_set_default_env("CONFIG_DATA_PATH", "data/config")
_set_default_env("AUTH_COOKIE_SECURE", "false")
_set_default_env("AUTH_COOKIE_SAMESITE", "lax")
_set_default_env("ALLOW_PASSWORD_GENERATOR_ENDPOINT", "true")
