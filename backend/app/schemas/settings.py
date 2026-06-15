"""Application settings schemas."""

from pydantic import BaseModel, Field


class SettingsStatusResponse(BaseModel):
    llm_provider: str
    llm_model: str = ""
    is_mock: bool = True
    deepseek_configured: bool
    deepseek_model: str = ""
    spark_enabled: bool = False
    spark_configured: bool = False
    spark_model: str = ""
    spark_base_url_configured: bool = False
    fallback_provider: str = ""
    fallback_available: bool = False
    embedding_provider: str
    embedding_is_mock: bool = True
    model_status: dict = Field(default_factory=dict)
    rag_status: dict = Field(default_factory=dict)
    retrieval_mode: str = ""
    course_references_enabled: bool = True


class LLMConfigRequest(BaseModel):
    provider: str = "deepseek"
    api_key: str = Field(..., min_length=1)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    timeout_seconds: int = 180


class LLMTestRequest(BaseModel):
    message: str = "你好，请用一句话说明你已连接成功"
    provider: str = ""  # "deepseek" or "spark"
    model: str = ""     # optional, overrides the configured model


class LLMTestResponse(BaseModel):
    ok: bool
    provider: str = ""
    model: str = ""
    response: str = ""
    latency_ms: float = 0
    error: str = ""
    message: str = ""
    fallback_available: bool = False
