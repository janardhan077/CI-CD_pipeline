"""
Central configuration shared by every IN-ON microservice.

All services read the SAME database_url (this is the "shared DB" split:
one physical database, but each service only ever writes to the tables
it owns - see the README for the ownership map). Ledger URL lets every
other service find the Ledger service without hardcoding hosts, so the
same code works in docker-compose (service DNS names) and locally
(localhost + different ports).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="INON_", extra="ignore")

    app_name: str = "IN-ON"
    environment: str = "development"

    # Same physical database for every service in this shared-DB split.
    database_url: str = "sqlite:////app/data/inon.db"

    # Base URL of the Ledger service - every other financial service
    # calls through this instead of writing ledger_transactions itself.
    ledger_service_url: str = "http://ledger-service:8000"

    # Peer service URLs - used by the Report service (pure aggregator,
    # no table of its own) and the Assistant service (no DB access at
    # all, by design - see services/assistant_service's README note).
    sales_service_url: str = "http://sales-service:8000"
    credit_service_url: str = "http://credit-service:8000"
    expense_service_url: str = "http://expense-service:8000"
    stock_service_url: str = "http://stock-service:8000"
    cashbank_service_url: str = "http://cashbank-service:8000"
    report_service_url: str = "http://report-service:8000"

    # Ollama is a separate local service - never bundled with app
    # secrets or given database access.
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "gemma3"

    default_currency: str = "INR"
    default_stock_unit: str = "bag"

    log_level: str = "INFO"

    # Timeout for inter-service HTTP calls (seconds).
    http_timeout: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
