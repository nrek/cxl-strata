from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sibyl_env: str = "development"
    database_url: str = "postgresql+psycopg://sibyl:sibyl@127.0.0.1:5432/sibyl"
    api_key_pepper: str = "change-me-in-production"
    sibyl_api_keys: str = "sibyl_dev_example"
    bootstrap_org_slug: str = "bootstrap-org"
    bootstrap_org_name: str = "Bootstrap Organization"

    def allowed_api_keys(self) -> list[str]:
        return [key.strip() for key in self.sibyl_api_keys.split(",") if key.strip()]


settings = Settings()
