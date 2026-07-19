import os
from openai import AsyncOpenAI

# `or "not-configured"` (not `.get(key, "not-configured")`) matters here:
# if .env has `OPENAI_API_KEY=` (empty), the key still exists in the
# environment, so `.get()`'s default is never used and returns "" — which
# the OpenAI SDK treats as missing credentials and raises on. `or` covers
# both "unset" and "set to empty string".
_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY") or "not-configured")


class OpenAIProvider:
    """Same common interface as AnthropicProvider — see that file for the contract."""

    id = "openai"

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


openai_provider = OpenAIProvider()
