"""Lens settings (env prefix ``LENS_``).

``LENS_MCP_SERVERS`` is a JSON list, e.g.
``[{"name":"kb-tools","namespace":"kb","url":"http://mcp-tools:9002/mcp","token":"<key>"}]``.
``namespace`` groups servers that share one id space (all KB servers → ``kb``) so the
same entity from two servers gets one canvas key.  Role models default to the
LiteLLM large tier: planning and normalization need reliable tool-use + JSON.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import settings

DEFAULT_VOCABULARY = [
    "person", "organization", "event", "location", "document", "topic",
    "ip", "domain", "certificate", "service", "asn", "other",
]


class McpServerConfig(BaseModel):
    name: str
    url: str
    namespace: str | None = None
    token: SecretStr | None = None

    @field_validator("token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def ns(self) -> str:
        return self.namespace or self.name


class LensSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LENS_", env_file=".env", extra="ignore")

    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    model_planner: str = ""
    model_normalizer: str = ""
    max_tool_steps: int = 6
    sample_chars: int = 6000
    aggregate_threshold: int = 25
    tool_timeout_s: float = 120.0
    reconnect_backoff_s: float = 10.0
    vocabulary: list[str] = Field(default_factory=lambda: list(DEFAULT_VOCABULARY))
    # Lens has its own keys: never reuse the main KB API keys (they would leak
    # through the SSE stream URL otherwise).
    api_keys: str = "dev-lens-key"
    stream_secret: SecretStr = SecretStr("")
    cors_origins: str = "http://localhost:5173"

    def planner_model(self) -> str:
        return self.model_planner or settings.litellm.model_large

    def normalizer_model(self) -> str:
        return self.model_normalizer or settings.litellm.model_large

    def keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def stream_secret_value(self) -> str:
        return self.stream_secret.get_secret_value() or (self.keys_list() or [""])[0]


lens_settings = LensSettings()
