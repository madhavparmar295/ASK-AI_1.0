from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Every setting is read as GRIEVANCE_<NAME> (e.g. GRIEVANCE_DATABASE_URL), so this
    # module can share one .env and one process with the chatbot without either side
    # picking up the other's DATABASE_URL, SECRET_KEY or SMTP settings.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="GRIEVANCE_")

    env: str = "development"  # development | test | production
    # Its own database on purpose: both apps define a `users` table, and the chatbot's
    # one has integer ids while this one uses UUIDs. Sharing a database would collide.
    database_url: str = "sqlite:///./grievance.db"
    auto_create_tables: bool = True   # dev/bootstrap. In production run the migrations instead.
    secret_key: str = "change-me"
    google_client_id: str = ""
    allowed_email_domain: str = "college.edu"
    require_hd: bool = True
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    dev_login_enabled: bool = True
    unknown_email_policy: str = "reject"  # reject | student
    api_prefix: str = "/api/grievance"
    cors_origins: str = "http://localhost:5173"
    login_rate_limit_per_minute: int = 60   # per client address; students behind one campus NAT share an address

    # Tickets and files (Stage 2)
    max_tickets_per_day: int = 10
    max_attachments_per_user_per_ticket: int = 3
    max_upload_mb: int = 10
    upload_dir: str = "./uploads"        # keep OUTSIDE any web-served folder
    clamav_enabled: bool = False         # if true, uses the `clamscan` command
    auto_close_resolved_days: int = 3
    auto_close_needs_info_days: int = 7

    # Worker, email, alerts (Stage 3)
    worker_tick_seconds: int = 60          # the worker runs all jobs every tick
    heartbeat_alert_minutes: int = 60      # alert the admin if the worker has not run for this long
    watchdog_enabled: bool = True          # API-side check that the worker is alive
    smtp_host: str = ""                    # empty = email is not configured
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    mail_from: str = ""                    # default: no-reply@<ALLOWED_EMAIL_DOMAIN>
    admin_alert_email: str = ""            # default: every active admin's email
    app_base_url: str = "http://localhost:5173"   # used for links in emails
    email_max_attempts: int = 5
    email_retry_minutes: int = 5
    classify_rate_limit_per_minute: int = 60

    # Data retention (Stage 5). 0 = never delete. Set by the admin block's decision, see docs/RETENTION.md
    retention_years: int = 0
    retention_confidential_years: int = 0

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def sender_address(self) -> str:
        return self.mail_from or f"no-reply@{self.allowed_email_domain}"

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_for_runtime(self) -> None:
        """Refuse to start in production with unsafe settings."""
        if self.unknown_email_policy not in ("reject", "student"):
            raise RuntimeError("UNKNOWN_EMAIL_POLICY must be 'reject' or 'student'")
        if not self.is_production:
            return
        problems = []
        if self.dev_login_enabled:
            problems.append("DEV_LOGIN_ENABLED must be false")
        if self.secret_key == "change-me" or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a random string of 32+ characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (HTTPS)")
        if not self.google_client_id:
            problems.append("GOOGLE_CLIENT_ID must be set")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
