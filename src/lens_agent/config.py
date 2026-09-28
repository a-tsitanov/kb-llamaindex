"""lens-agent settings (env prefix ``LENS_AGENT_``).

``LENS_AGENT_MCP`` is a JSON list; a new source is one more entry, no code::

    [{"name": "kb-tools", "namespace": "kb", "url": "http://mcp-tools:9002/mcp",
      "token": "<key>", "role": "source"},
     {"name": "board", "url": "http://lens:8010/mcp/mcp", "token": "<LENS_BOARD_MCP_TOKEN>",
      "role": "board"}]

REST keys and the stream secret are shared with the board (``LENS_API_KEYS``,
``LENS_STREAM_SECRET``) — see ``src.lens.config``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import settings


class McpEntry(BaseModel):
    name: str
    url: str
    namespace: str | None = None
    token: SecretStr | None = None
    role: Literal["source", "board"] = "source"
    enabled: bool = True

    @field_validator("token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def ns(self) -> str:
        return self.namespace or self.name


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LENS_AGENT_", env_file=".env",
                                      extra="ignore")

    mcp: list[McpEntry] = []
    model: str = "large"  # LiteLLM alias
    result_chars: int = 4000  # source result cut before it reaches the model
    source_calls: int = 8  # soft budget per run
    board_calls: int = 20  # soft budget per run
    request_limit: int = 30  # hard: model requests per run
    run_timeout_s: float = 600.0
    tool_timeout_s: float = 120.0
    connect_timeout_s: float = 10.0
    retention_days: int = 30
    heartbeat_s: float = 15.0

    def enabled(self) -> list[McpEntry]:
        return [e for e in self.mcp if e.enabled]

    def board(self) -> McpEntry | None:
        return next((e for e in self.enabled() if e.role == "board"), None)

    def llm_base_url(self) -> str:
        return settings.litellm.base_url

    def llm_api_key(self) -> str:
        return settings.litellm.api_key.get_secret_value()


agent_settings = AgentSettings()
