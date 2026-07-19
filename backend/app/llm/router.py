from .providers.anthropic_provider import anthropic_provider
from .providers.openai_provider import openai_provider
from .providers.groq_provider import groq_provider

_PROVIDERS = {
    "anthropic": anthropic_provider,
    "openai": openai_provider,
    "groq": groq_provider,
}

# Model -> provider routing. Add a line here to onboard a new provider/model;
# nothing else in the app needs to change (this is the "auto-instrument"
# seam — every call, from any provider, funnels through get_provider() and
# therefore through OllieSDK, which is what actually logs it).
#
# Groq models are listed first and used as the default (see routes/chat.py)
# because Groq has a free tier — no card, no billing — which the Anthropic
# and OpenAI keys don't. Anthropic/OpenAI models stay mapped too, so adding
# a real key later just works without touching this file.
_MODEL_PROVIDER_MAP = {
    "llama-3.3-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    "gemma2-9b-it": "groq",
    "claude-sonnet-4-6": "anthropic",
    "claude-opus-4-6": "anthropic",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
}


def get_provider(model: str):
    provider_id = _MODEL_PROVIDER_MAP.get(model)
    if not provider_id:
        raise ValueError(f'No provider configured for model "{model}"')
    return _PROVIDERS[provider_id]


def list_models():
    return list(_MODEL_PROVIDER_MAP.keys())