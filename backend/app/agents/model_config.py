from app.config import get_settings


def get_agent_model():
    """Model identifier for LlmAgents, swappable purely via env vars."""
    settings = get_settings()
    if settings.use_litellm:
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=settings.llm_model)
    return settings.gemini_model
