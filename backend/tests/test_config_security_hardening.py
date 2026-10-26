from backend.app.config.config import load_config


def test_load_config_blocks_insecure_defaults_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_ACCESS_SECRET", raising=False)
    monkeypatch.delenv("JWT_REFRESH_SECRET", raising=False)
    monkeypatch.delenv("JWT_CHANGE_PASSWORD_SECRET", raising=False)
    monkeypatch.delenv("JWT_MFA_SECRET", raising=False)
    monkeypatch.delenv("FILE_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START", "false")
    monkeypatch.setenv("DELETE_JOB_UPLOADS_AFTER_COMPLETION", "true")
    monkeypatch.setenv("DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD", "true")
    monkeypatch.setenv("REMOVE_SOURCE_AFTER_PROCESSING", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "strict")

    try:
        load_config()
    except ValueError as exc:
        assert "insecure default secrets" in str(exc).lower()
    else:
        raise AssertionError("Expected production config validation error")


def test_load_config_accepts_secure_values_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_ACCESS_SECRET", "prod-access-secret-unique")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "prod-refresh-secret-unique")
    monkeypatch.setenv("JWT_CHANGE_PASSWORD_SECRET", "prod-change-secret-unique")
    monkeypatch.setenv("JWT_MFA_SECRET", "prod-mfa-secret-unique")
    monkeypatch.setenv("FILE_ENCRYPTION_KEY", "prod-file-encryption-secret-unique")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "ProdAdminStrong#2048")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_RESET_PASSWORD_ON_START", "false")
    monkeypatch.setenv("DELETE_JOB_UPLOADS_AFTER_COMPLETION", "true")
    monkeypatch.setenv("DELETE_GENERATED_PASSPORTS_AFTER_DOWNLOAD", "true")
    monkeypatch.setenv("REMOVE_SOURCE_AFTER_PROCESSING", "true")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("AUTH_COOKIE_SAMESITE", "strict")

    cfg = load_config()
    assert cfg.app.environment == "production"
    assert cfg.security.auth_cookie_secure is True
    assert cfg.user_data.delete_job_uploads_after_completion is True
