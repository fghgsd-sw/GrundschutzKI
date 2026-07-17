from __future__ import annotations

from typing import Any, Awaitable, Callable

import litellm

from settings import CHAT_MODEL, CHAT_TEMPERATURE, EMBED_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL


def _client_args() -> dict[str, Any]:
    args: dict[str, Any] = {}
    if LITELLM_BASE_URL:
        args["api_base"] = LITELLM_BASE_URL
    if LITELLM_API_KEY:
        args["api_key"] = LITELLM_API_KEY
    return args


async def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    model: str | None = None,
):
    payload: dict[str, Any] = {
        "model": model or CHAT_MODEL,
        "messages": messages,
        "temperature": CHAT_TEMPERATURE,
        **_client_args(),
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
    return await litellm.acompletion(**payload, num_retries=1, timeout=45)


async def stream_or_collect(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = "auto",
    on_content_token: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[str | None, Any]:
    """Stream a chat call and detect whether the response is content or tool calls.

    Returns (full_content, None) for content responses — each token was passed to
    on_content_token as it arrived.
    Returns (None, message_obj) for tool-call responses — collected silently.
    """
    payload: dict[str, Any] = {
        "model": CHAT_MODEL,
        "messages": messages,
        "temperature": CHAT_TEMPERATURE,
        "stream": True,
        **_client_args(),
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    stream = await litellm.acompletion(**payload, timeout=90)

    chunks: list[Any] = []
    full_content = ""
    has_tool_calls = False

    async for chunk in stream:
        chunks.append(chunk)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "tool_calls", None):
            has_tool_calls = True
        if not has_tool_calls and delta.content:
            full_content += delta.content
            if on_content_token:
                await on_content_token(delta.content)

    if has_tool_calls:
        full_response = litellm.stream_chunk_builder(chunks, messages=messages)
        return None, full_response.choices[0].message

    return full_content, None


async def stream_chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, tool_choice: str | None = None):
    payload: dict[str, Any] = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": True,
        **_client_args(),
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
    return await litellm.acompletion(**payload)


async def embed(texts: list[str]) -> list[list[float]]:
    response = await litellm.aembedding(
        model=EMBED_MODEL,
        input=texts,
        encoding_format="float",
        **_client_args(),
    )
    data = sorted(response.data, key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def message_to_dict(message: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in tool_calls
        ]
    return data
