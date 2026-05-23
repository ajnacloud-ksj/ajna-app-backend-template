"""Settings for {{app-name}} — only declare app-specific fields here."""
import os
from dataclasses import dataclass
from ajna_cloud.config import BaseConfig, BaseSettings


@dataclass
class AppConfig(BaseConfig):
    # Add ONLY {{app-name}}-specific fields below.
    # Example feature flag — rename/remove for your app:
    feature_items_crud: bool = True


class Settings(BaseSettings):
    ConfigClass = AppConfig

    def _load(self) -> AppConfig:
        cfg = AppConfig.from_env()
        # Load app-specific fields. Example:
        cfg.feature_items_crud = os.environ.get('FEATURE_ITEMS_CRUD', 'true').lower() == 'true'
        return cfg


settings = Settings()
