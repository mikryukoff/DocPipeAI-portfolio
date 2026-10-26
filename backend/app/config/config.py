from dataclasses import dataclass

from environs import Env


@dataclass
class Logger:
    logs_path: str


@dataclass
class UserData:
    """Корень data/users/..., общий config, флаги очистки."""

    base_path: str
    config_path: str
    delete_job_uploads_after_completion: bool
    delete_generated_passports_after_download: bool


@dataclass
class Security:
    jwt_access_secret: str
    jwt_refresh_secret: str
    jwt_change_password_secret: str
    jwt_mfa_secret: str
    jwt_access_ttl_min: int
    jwt_refresh_ttl_days: int
    jwt_change_password_ttl_min: int
    jwt_mfa_ttl_min: int
    file_encryption_key: str
    temp_password_len: int
    demo_download_limit: int
    demo_period_days: int
    login_attempts_limit: int
    login_window_min: int
    login_block_min: int
    remove_source_after_processing: bool
    auth_cookie_secure: bool
    auth_cookie_samesite: str
    allow_password_generator_endpoint: bool
    bootstrap_admin_username: str
    bootstrap_admin_password: str
    bootstrap_admin_role: str
    bootstrap_admin_is_active: bool
    bootstrap_admin_reset_password_on_start: bool
    force_relogin_on_restart: bool
    admin_logs_clear_password: str


@dataclass
class UploadValidation:
    max_upload_size_mb: int
    allowed_mime_pdf: list[str]
    allowed_mime_excel: list[str]
    allowed_mime_archive: list[str]


@dataclass
class WordExporter:
    word_output_path: str
    word_template_path: str


@dataclass
class CSVParser:
    json_output_path: str
    excel_output_path: str
    pipelines_pages_path: str


@dataclass
class TablesExtractor:
    pdf_path: str
    output_dir: str


@dataclass
class TextExtractor:
    pdf_path: str
    output_dir: str


@dataclass
class OCR:
    mode: str
    ollama_host: str
    poppler_path: str
    crop_output_dir: str
    parsed_output_dir: str


@dataclass
class ExcelImport:
    input_path: str
    preview_output_dir: str


@dataclass
class App:
    project_name: str
    version: str
    environment: str


# Описание настроек подключения к БД
@dataclass
class Database:
    host: str        # Хост БД
    user: str        #
    password: str    # Пароль от БД
    db_name: str     # Название БД
    db_port: str


# Основной конфиг приложения
@dataclass
class Config:
    app: App
    database: Database
    tables_extractor: TablesExtractor
    text_extractor: TextExtractor
    ocr: OCR
    excel_import: ExcelImport
    csv_parser: CSVParser
    word_exporter: WordExporter
    logger: Logger
    user_data: UserData
    security: Security
    upload_validation: UploadValidation


_DEFAULT_SECRET_VALUES = {
    "JWT_ACCESS_SECRET": "change-me-access-secret",
    "JWT_REFRESH_SECRET": "change-me-refresh-secret",
    "JWT_CHANGE_PASSWORD_SECRET": "change-me-change-password-secret",
    "JWT_MFA_SECRET": "change-me-mfa-secret",
    "FILE_ENCRYPTION_KEY": "insecure-dev-key",
    "BOOTSTRAP_ADMIN_PASSWORD": "admin12345!",
}


def _is_production_environment(environment: str) -> bool:
    env = (environment or "").strip().lower()
    return env in {"prod", "production"}


def _validate_prod_security(config: Config) -> None:
    if not _is_production_environment(config.app.environment):
        return

    secret_checks = {
        "JWT_ACCESS_SECRET": config.security.jwt_access_secret,
        "JWT_REFRESH_SECRET": config.security.jwt_refresh_secret,
        "JWT_CHANGE_PASSWORD_SECRET": config.security.jwt_change_password_secret,
        "JWT_MFA_SECRET": config.security.jwt_mfa_secret,
        "FILE_ENCRYPTION_KEY": config.security.file_encryption_key,
        "BOOTSTRAP_ADMIN_PASSWORD": config.security.bootstrap_admin_password,
    }
    weak_vars = [
        key
        for key, value in secret_checks.items()
        if value == _DEFAULT_SECRET_VALUES[key]
    ]
    if weak_vars:
        joined = ", ".join(sorted(weak_vars))
        raise ValueError(
            "Production startup blocked: insecure default secrets detected "
            f"({joined})."
        )

    if config.security.bootstrap_admin_reset_password_on_start:
        raise ValueError(
            "Production startup blocked: BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START "
            "must be false."
        )
    if not config.security.auth_cookie_secure:
        raise ValueError("Production startup blocked: AUTH_COOKIE_SECURE must be true.")
    if config.security.auth_cookie_samesite not in {"lax", "strict", "none"}:
        raise ValueError(
            "Production startup blocked: AUTH_COOKIE_SAMESITE must be one of "
            "lax/strict/none."
        )
    if (
        config.security.auth_cookie_samesite == "none"
        and not config.security.auth_cookie_secure
    ):
        raise ValueError(
            "Production startup blocked: AUTH_COOKIE_SAMESITE=none requires "
            "AUTH_COOKIE_SECURE=true."
        )
    if not config.user_data.delete_job_uploads_after_completion:
        raise ValueError(
            "Production startup blocked: DELETE_JOB_UPLOADS_AFTER_COMPLETION must be true."
        )
    if not config.user_data.delete_generated_passports_after_download:
        raise ValueError(
            "Production startup blocked: DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD "
            "must be true."
        )
    if not config.security.remove_source_after_processing:
        raise ValueError(
            "Production startup blocked: REMOVE_SOURCE_AFTER_PROCESSING must be true."
        )


# Функция загрузки конфигурации
def load_config(path: str | None = None) -> Config:
    # Инициализация окружения
    env = Env()
    env.read_env(path)

    app_environment = env("ENVIRONMENT", "production").strip().lower() or "production"
    is_production = _is_production_environment(app_environment)

    remove_source_legacy = env.bool(
        "REMOVE_SOURCE_AFTER_PROCESSING", is_production
    )
    delete_passports_after_download = env.bool(
        "DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD",
        True if is_production else remove_source_legacy,
    )
    delete_job_uploads = env.bool(
        "DELETE_JOB_UPLOADS_AFTER_COMPLETION",
        True if is_production else remove_source_legacy,
    )
    auth_cookie_secure = env.bool("AUTH_COOKIE_SECURE", is_production)
    auth_cookie_samesite = env(
        "AUTH_COOKIE_SAMESITE",
        "strict" if is_production else "lax",
    ).strip().lower()
    allow_password_generator_endpoint = env.bool(
        "ALLOW_PASSWORD_GENERATOR_ENDPOINT",
        not is_production,
    )

    # Возврат конфигурации
    config = Config(
        app=App(
            project_name=env("PROJECT_NAME"),
            version=env("VERSION"),
            environment=app_environment,
        ),
        database=Database(
            host=env("DB_HOST"),            # Хост БД
            user=env("DB_USER"),            #
            password=env("DB_PASSWORD"),    # Пароль от БД
            db_name=env("DB_NAME"),         # Название БД
            db_port=env("DB_PORT")
        ),
        tables_extractor=TablesExtractor(
            pdf_path=env("DRAWINGS_PDF_PATH"),
            output_dir=env("DRAWINGS_OUTPUT")
        ),
        text_extractor=TextExtractor(
            pdf_path=env("OCR_PDF_PATH"),
            output_dir=env("OCR_OUTPUT")
        ),
        ocr=OCR(
            mode=env("MODE", "PRODUCTION"),
            ollama_host=env("OLLAMA_HOST", "http://localhost:11434"),
            poppler_path=env("POPPLER_PATH", ""),
            crop_output_dir=env("OCR_CROP_OUTPUT_PATH", "data/ocr/crop_page"),
            parsed_output_dir=env("OCR_PARSED_OUTPUT_PATH", "data/ocr/parsed_texts"),
        ),
        excel_import=ExcelImport(
            input_path=env("EXCEL_INPUT_PATH", "data/raw/excel"),
            preview_output_dir=env("EXCEL_PREVIEW_OUTPUT_PATH", "data/interim/excel_inspect"),
        ),
        csv_parser=CSVParser(
            json_output_path=env("JSON_OUTPUT_PATH"),
            excel_output_path=env("EXCEL_OUTPUT_PATH"),
            pipelines_pages_path=env("PIPELINES_PAGES_PATH")
        ),
        word_exporter=WordExporter(
            word_template_path=env("WORD_TEMPLATE_PATH"),
            word_output_path=env("WORD_OUTPUT_PATH")
        ),
        logger=Logger(
            logs_path=env("LOGS_OUTPUT_PATH")
        ),
        user_data=UserData(
            base_path=env("DATA_BASE_PATH", "data"),
            config_path=env("CONFIG_DATA_PATH", "data/config"),
            delete_job_uploads_after_completion=delete_job_uploads,
            delete_generated_passports_after_download=delete_passports_after_download,
        ),
        security=Security(
            jwt_access_secret=env(
                "JWT_ACCESS_SECRET",
                _DEFAULT_SECRET_VALUES["JWT_ACCESS_SECRET"],
            ),
            jwt_refresh_secret=env(
                "JWT_REFRESH_SECRET",
                _DEFAULT_SECRET_VALUES["JWT_REFRESH_SECRET"],
            ),
            jwt_change_password_secret=env(
                "JWT_CHANGE_PASSWORD_SECRET",
                _DEFAULT_SECRET_VALUES["JWT_CHANGE_PASSWORD_SECRET"],
            ),
            jwt_mfa_secret=env(
                "JWT_MFA_SECRET",
                _DEFAULT_SECRET_VALUES["JWT_MFA_SECRET"],
            ),
            jwt_access_ttl_min=env.int("JWT_ACCESS_TTL_MIN", 15),
            jwt_refresh_ttl_days=env.int("JWT_REFRESH_TTL_DAYS", 7),
            jwt_change_password_ttl_min=env.int("JWT_CHANGE_PASSWORD_TTL_MIN", 10),
            jwt_mfa_ttl_min=env.int("JWT_MFA_TTL_MIN", 5),
            file_encryption_key=env(
                "FILE_ENCRYPTION_KEY",
                _DEFAULT_SECRET_VALUES["FILE_ENCRYPTION_KEY"],
            ),
            temp_password_len=env.int("TEMP_PASSWORD_LEN", 12),
            demo_download_limit=env.int("DEMO_DOWNLOAD_LIMIT", 20),
            demo_period_days=env.int("DEMO_PERIOD_DAYS", 7),
            login_attempts_limit=env.int("LOGIN_ATTEMPTS_LIMIT", 5),
            login_window_min=env.int("LOGIN_WINDOW_MIN", 15),
            login_block_min=env.int("LOGIN_BLOCK_MIN", 30),
            remove_source_after_processing=remove_source_legacy,
            auth_cookie_secure=auth_cookie_secure,
            auth_cookie_samesite=auth_cookie_samesite,
            allow_password_generator_endpoint=allow_password_generator_endpoint,
            bootstrap_admin_username=env("BOOTSTRAP_ADMIN_USERNAME", "admin"),
            bootstrap_admin_password=env(
                "BOOTSTRAP_ADMIN_PASSWORD",
                _DEFAULT_SECRET_VALUES["BOOTSTRAP_ADMIN_PASSWORD"],
            ),
            bootstrap_admin_role=env("BOOTSTRAP_ADMIN_ROLE", "admin"),
            bootstrap_admin_is_active=env.bool("BOOTSTRAP_ADMIN_IS_ACTIVE", True),
            bootstrap_admin_reset_password_on_start=env.bool(
                "BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START",
                False if is_production else True,
            ),
            force_relogin_on_restart=env.bool(
                "FORCE_RELOGIN_ON_RESTART",
                True,
            ),
            admin_logs_clear_password=env(
                "ADMIN_LOGS_CLEAR_PASSWORD",
                "",
            ),
        ),
        upload_validation=UploadValidation(
            max_upload_size_mb=env.int("MAX_UPLOAD_SIZE_MB", 50),
            allowed_mime_pdf=env.list(
                "ALLOWED_MIME_PDF",
                default=["application/pdf"],
            ),
            allowed_mime_excel=env.list(
                "ALLOWED_MIME_EXCEL",
                default=[
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel.sheet.macroEnabled.12",
                ],
            ),
            allowed_mime_archive=env.list(
                "ALLOWED_MIME_ARCHIVE",
                default=[
                    "application/zip",
                    "application/x-zip-compressed",
                    "application/vnd.rar",
                    "application/x-rar-compressed",
                    "application/x-compressed",
                    "application/octet-stream",
                ],
            ),
        )
    )
    _validate_prod_security(config)
    return config
