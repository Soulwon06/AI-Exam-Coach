"""AI service facade: routes material text to the configured provider."""
from app.core.config import settings
from app.services.ai_provider import AIProvider, HeuristicProvider


def _build_provider() -> AIProvider:
    if settings.ai_provider == "openai_compatible" and settings.openai_api_key:
        try:
            from app.services.openai_provider import OpenAICompatibleProvider

            return OpenAICompatibleProvider(settings)
        except Exception:
            pass
    return HeuristicProvider()


_ai_service = _build_provider()


def analyze_material(text: str, material_type: str) -> dict:
    return _ai_service.analyze_material(text, material_type)
