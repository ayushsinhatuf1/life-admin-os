from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "change-me"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    database_url: str = "postgresql+psycopg://lifeadmin:lifeadmin@localhost:5432/lifeadmin"

    s3_endpoint_url: str | None = None
    s3_bucket: str = "life-admin-documents"
    s3_region: str = "ap-south-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    anthropic_api_key: str | None = None
    extraction_model: str = "claude-sonnet-4-6"
    assistant_model: str = "claude-sonnet-4-6"

    max_upload_mb: int = 25
    allowed_mime: str = "application/pdf,image/jpeg,image/png"
    max_pdf_pages: int = 100
    max_decompressed_mb: int = 100
    clamav_host: str | None = None
    clamav_port: int = 3310
    upload_rate_limit_count: int = 20
    upload_rate_limit_seconds: int = 600

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    mail_from: str = "reminders@lifeadminos.app"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
