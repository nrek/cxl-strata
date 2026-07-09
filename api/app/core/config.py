from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    strata_env: str = "development"
    database_url: str = "postgresql+psycopg://strata:strata@127.0.0.1:5432/strata"
    api_key_pepper: str = "change-me-in-production"
    strata_api_keys: str = "strata_dev_example"
    bootstrap_org_slug: str = "bootstrap-org"
    bootstrap_org_name: str = "Bootstrap Organization"
    strata_public_url: str = "http://127.0.0.1:8015"
    strata_client_git_url: str = "https://github.com/nrek/cxl-strata.git"
    strata_client_git_ref: str = "main"
    strata_default_org: str = "your-org"
    # Advertised client package version — bump when shipping a client release.
    # Local apps compare this to their installed version and show [ update ].
    strata_client_version: str = "0.3.1"

    def allowed_api_keys(self) -> list[str]:
        return [key.strip() for key in self.strata_api_keys.split(",") if key.strip()]


settings = Settings()
