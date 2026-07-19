import os
from openai import AsyncOpenAI

_client = AsyncOpenAI(
    api_key=os.environ.get("GROQ_API_KEY") or "not-configured",
    base_url="https://api.groq.com/openai/v1",
)


class GroqProvider:
    """Same common interface as the other providers — see anthropic_provider.py for the contract."""

    id = "groq"

    async def complete(self, model: str, messages: list[dict], system: str | None):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        res = await _client.chat.completions.create(model=model, messages=full_messages)
        choice = res.choices[0]
        usage = res.usage
        return {
            "text": choice.message.content or "",
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
            "raw": res,
        }

    async def stream(self, model: str, messages: list[dict], system: str | None, on_chunk):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        stream = await _client.chat.completions.create(
            model=model,
            messages=full_messages,
            stream=True,
            stream_options={"include_usage": True},
        )

        text = ""
        usage = None
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                text += delta
                on_chunk(delta)
            if chunk.usage:
                usage = chunk.usage

        return {
            "text": text,
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
            "raw": {"usage": usage},
        }


groq_provider = GroqProvider()