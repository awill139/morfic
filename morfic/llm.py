from __future__ import annotations

import asyncio
import contextvars
import time
from typing import Awaitable, Callable

import httpx

from .config import settings
from .provider_config import get_secret, load_provider_settings
from .hosted import hosted_task, emit_model_call
from .task_ids import task_for_system

TestHandler = Callable[[str, str, bool], Awaitable[str]]

# Token counts reported by the provider for the most recent call made in this async context.
_last_usage: contextvars.ContextVar[tuple[int | None, int | None]] = contextvars.ContextVar("morfic_last_usage", default=(None, None))


def _record_usage(usage: object, input_key: str, output_key: str) -> None:
    if isinstance(usage, dict):
        def num(k):
            v = usage.get(k)
            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
        _last_usage.set((num(input_key), num(output_key)))
    else:
        _last_usage.set((None, None))

# In Official + BYOK mode, the hosted service keeps the high-value planning
# decisions while source-heavy calls use the tester's local provider key.
OFFICIAL_BYOK_LOCAL_TASKS = {
    "generate_file",
    "repair_generated_file",
    "modify_repo",
    "localize_strings",
    "modify_patch",
    "modify_new_file",
}


class LLMClient:
    def __init__(self) -> None:
        self._test_handler: TestHandler | None = None

    def set_test_handler(self, handler: TestHandler | None) -> None:
        """Testing seam. Production code leaves this unset and uses the configured provider."""
        self._test_handler = handler

    async def chat(self, system: str, user: str, json_mode: bool = False, max_output_tokens: int | None = None) -> str:
        if self._test_handler is not None:
            return await self._test_handler(system, user, json_mode)
        cfg = load_provider_settings()
        try:
            async with asyncio.timeout(settings.llm_call_timeout_seconds):
                if cfg.provider == "official":
                    task = task_for_system(system)
                    if not task:
                        raise RuntimeError("This orchestration step is not supported by the hosted service yet.")
                    if cfg.official_ai_mode == "byok" and task in OFFICIAL_BYOK_LOCAL_TASKS:
                        return await self._official_byok(task, cfg, system, user, json_mode, max_output_tokens)
                    return await hosted_task(task, user, json_mode, max_output_tokens)
                if cfg.provider == "openai":
                    return await self._openai(cfg.openai_base_url, cfg.openai_model, get_secret("openai_api_key"), system, user, json_mode, max_output_tokens)
                if cfg.provider == "anthropic":
                    return await self._anthropic(cfg.anthropic_base_url, cfg.anthropic_model, get_secret("anthropic_api_key"), system, user, json_mode, max_output_tokens)
                raise RuntimeError("Configure OpenAI or Anthropic in Settings before asking for software.")
        except TimeoutError as e:
            raise RuntimeError(f"The AI provider did not finish within {settings.llm_call_timeout_seconds} seconds.") from e

    async def test_connection(self, provider: str) -> str:
        cfg = load_provider_settings()
        prompt = 'Return exactly this JSON object: {"ok":true,"message":"connected"}'
        if provider == "official":
            hosted = await hosted_task("resolve", '{"request":"connection test","options":{"installed":[],"catalog":[]}}', True, 1000)
            if cfg.official_ai_mode == "byok":
                p = cfg.official_byok_provider
                prompt = 'Return exactly this JSON object: {"ok":true,"message":"connected"}'
                if p == "openai":
                    await self._openai(cfg.openai_base_url, cfg.openai_model, get_secret("openai_api_key"), "You are a connection test.", prompt, True, 1000)
                elif p == "anthropic":
                    await self._anthropic(cfg.anthropic_base_url, cfg.anthropic_model, get_secret("anthropic_api_key"), "You are a connection test.", prompt, True, 1000)
                else:
                    raise RuntimeError("Choose OpenAI or Anthropic for Official BYOK.")
            return hosted
        if provider == "openai":
            return await self._openai(cfg.openai_base_url, cfg.openai_model, get_secret("openai_api_key"), "You are a connection test.", prompt, True, 1000)
        if provider == "anthropic":
            return await self._anthropic(cfg.anthropic_base_url, cfg.anthropic_model, get_secret("anthropic_api_key"), "You are a connection test.", prompt, True, 1000)
        raise RuntimeError("Unknown provider")


    async def _official_byok(self, task: str, cfg, system: str, user: str, json_mode: bool, max_output_tokens: int | None = None) -> str:
        provider = cfg.official_byok_provider.strip().lower()
        started = time.perf_counter()
        model = cfg.openai_model if provider == "openai" else cfg.anthropic_model if provider == "anthropic" else ""
        output = ""
        _last_usage.set((None, None))
        try:
            if provider == "openai":
                output = await self._openai(cfg.openai_base_url, cfg.openai_model, get_secret("openai_api_key"), system, user, json_mode, max_output_tokens)
            elif provider == "anthropic":
                output = await self._anthropic(cfg.anthropic_base_url, cfg.anthropic_model, get_secret("anthropic_api_key"), system, user, json_mode, max_output_tokens)
            else:
                raise RuntimeError("Choose OpenAI or Anthropic for Official BYOK.")
            asyncio.create_task(emit_model_call(
                task=task, provider=f"byok:{provider}", model=model, input_chars=len(user), output_chars=len(output),
                duration_ms=int((time.perf_counter()-started)*1000), success=True,
                input_tokens=_last_usage.get()[0], output_tokens=_last_usage.get()[1], request_text=user, response_text=output,
            ))
            return output
        except Exception as e:
            asyncio.create_task(emit_model_call(
                task=task, provider=f"byok:{provider or 'unknown'}", model=model, input_chars=len(user), output_chars=len(output),
                duration_ms=int((time.perf_counter()-started)*1000), success=False,
                error_class=type(e).__name__, error_message=str(e),
                input_tokens=_last_usage.get()[0], output_tokens=_last_usage.get()[1], request_text=user, response_text=output,
            ))
            raise

    async def _openai(self, base_url: str, model: str, api_key: str, system: str, user: str, json_mode: bool, max_output_tokens: int | None = None) -> str:
        if not api_key:
            raise RuntimeError("Add an OpenAI API key in Settings.")
        if not model:
            raise RuntimeError("Choose an OpenAI model in Settings.")
        payload: dict = {"model": model, "instructions": system, "input": user}
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        if max_output_tokens:
            payload["max_output_tokens"] = int(max_output_tokens)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        r = await _post_with_retry(f"{base_url.rstrip('/')}/responses", headers=headers, payload=payload)
        if r.status_code >= 400:
            raise RuntimeError(_provider_error("OpenAI", r))
        data = r.json()
        _record_usage(data.get("usage"), "input_tokens", "output_tokens")
        if isinstance(data.get("output_text"), str) and data["output_text"]:
            return data["output_text"]
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    chunks.append(content["text"])
        if chunks:
            return "".join(chunks)
        raise RuntimeError("OpenAI returned no text output.")

    async def _anthropic(self, base_url: str, model: str, api_key: str, system: str, user: str, json_mode: bool, max_output_tokens: int | None = None) -> str:
        if not api_key:
            raise RuntimeError("Add an Anthropic API key in Settings.")
        if not model:
            raise RuntimeError("Choose an Anthropic model in Settings.")
        if json_mode:
            system = system + "\nYour entire response must be one valid JSON object and nothing else."
        payload = {
            "model": model,
            "max_tokens": int(max_output_tokens or 12000),
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        r = await _post_with_retry(f"{base_url.rstrip('/')}/messages", headers=headers, payload=payload)
        if r.status_code >= 400:
            raise RuntimeError(_provider_error("Anthropic", r))
        data = r.json()
        _record_usage(data.get("usage"), "input_tokens", "output_tokens")
        chunks = [x.get("text", "") for x in data.get("content", []) if isinstance(x, dict) and x.get("type") == "text"]
        text = "".join(chunks).strip()
        if not text:
            raise RuntimeError("Anthropic returned no text output.")
        return text


async def _post_with_retry(url: str, *, headers: dict[str, str], payload: dict, attempts: int = 2) -> httpx.Response:
    """Bound provider I/O and retry one transient transport/server failure.

    httpx's timeout values are inactivity limits for individual I/O phases, not a
    complete orchestration watchdog. `LLMClient.chat` supplies the hard wall-clock
    deadline; this helper prevents common transient connection failures from becoming
    user-visible immediately.
    """
    timeout = httpx.Timeout(connect=20, read=90, write=60, pool=20)
    retryable_statuses = {408, 429, 500, 502, 503, 504, 529}
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            if response.status_code not in retryable_statuses or attempt == attempts - 1:
                return response
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            last_error = e
            if attempt == attempts - 1:
                raise RuntimeError(f"AI provider network request failed: {type(e).__name__}: {e}") from e
        await asyncio.sleep(0.6 * (attempt + 1))
    if last_error:
        raise RuntimeError(f"AI provider network request failed: {last_error}") from last_error
    raise RuntimeError("AI provider request failed without a response")


def _provider_error(provider: str, response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("error", data)
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("type") or str(detail)
        return f"{provider} API error ({response.status_code}): {detail}"
    except Exception:
        return f"{provider} API error ({response.status_code}): {response.text[:800]}"


llm = LLMClient()
