import os
from anthropic import AsyncAnthropic

# `or "not-configured"` (not `.get(key, "not-configured")`) matters here:
# if .env has `ANTHROPIC_API_KEY=` (empty), the key still exists in the
# environment, so `.get()`'s default is never used and returns "" — which
# the Anthropic SDK treats as missing credentials and raises on. `or` covers
# both "unset" and "set to empty string".
_client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or "not-configured")


class AnthropicProvider:
    """
    Normalizes Anthropic's API to the common provider interface every
    provider in this app implements:
        complete(model, messages, system) -> {text, input_tokens, output_tokens, raw}
        stream(model, messages, system, on_chunk) -> same shape, on_chunk called incrementally
    """

    id = "anthropic"

    async def complete(self, model: str, messages: list[dict], system: str | None):
        res = await _client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        text = "".join(block.text for block in res.content if block.type == "text")
        usage = res.usage
        return {
            "text": text,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "raw": res,
        }

    async def stream(self, model: str, messages: list[dict], system: str | None, on_chunk):
        text = ""
        async with _client.messages.stream(
            model=model,
            max_tokens=1024,
            system=system,
            messages=messages,
        ) as stream:
            async for delta in stream.text_stream:
                text += delta
                on_chunk(delta)
            final = await stream.get_final_message()

        usage = final.usage
        return {
            "text": text,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "raw": final,
        }


anthropic_provider = AnthropicProvider()
