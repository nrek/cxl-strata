from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    strata_env: str = "development"
    database_url: str = "postgresql+psycopg://strata:strata@127.0.0.1:5432/strata"
    api_key_pepper: str = "change-me-in-production"
    strata_api_keys: str = "strata_dev_example"
    bootstrap_org_slug: str = "bootstrap-org"
    bootstrap_org_name: str = "Bootstrap Organization"

    def allowed_api_keys(self) -> list[str]:
        return [key.strip() for key in self.strata_api_keys.split(",") if key.strip()]


settings = Settings()
