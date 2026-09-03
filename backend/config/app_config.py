import os
import logging
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class AppConfig(BaseModel):
    # Safety Gates
    live_execution_enabled: bool = False
    
    # Broker Config
    dhan_enabled: bool = False
    dhan_client_id: str = ""
    dhan_access_token: str = ""
    dhan_api_base_url: str = "https://api.dhan.co/v2"
    dhan_static_ip_configured: bool = False

    # LLM Config
    groq_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    google_api_key: str = ""
    
    @property
    def dhan_access_token_redacted(self) -> str:
        return "***REDACTED***" if self.dhan_access_token else ""

_global_app_config: AppConfig = None

def get_app_config() -> AppConfig:
    return reload_app_config()

def reload_app_config() -> AppConfig:
    global _global_app_config
    
    def parse_bool(env_key: str, default: bool = False) -> bool:
        val = os.getenv(env_key, "").strip().lower()
        if not val:
            return default
        return val == "true"
        
    config = AppConfig(
        live_execution_enabled=parse_bool("LIVE_EXECUTION_ENABLED", False),
        dhan_enabled=parse_bool("DHAN_ENABLED", False),
        dhan_client_id=os.getenv("DHAN_CLIENT_ID", "").strip(),
        dhan_access_token=os.getenv("DHAN_ACCESS_TOKEN", "").strip(),
        dhan_api_base_url=os.getenv("DHAN_API_BASE_URL", "https://api.dhan.co/v2").strip(),
        dhan_static_ip_configured=parse_bool("DHAN_STATIC_IP_CONFIGURED", False),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip()
    )
    
    _global_app_config = config
    return config

