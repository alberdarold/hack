"""Regolo (OpenAI-compatible) helpers: model selection, a tool-calling agent
loop, and a no-tools grounded synthesis fallback.

Design notes:
- The SDK default timeout is ~600s, which would blow the /ask ceiling, so every
  call gets an explicit per-request timeout and the agent loop also tracks a
  wall-clock budget.
- Some Regolo reasoning models return an empty `content` with the text in
  `reasoning_content`; both are handled.
- Nothing here raises to the caller: helpers return None so the agent can fall
  back to a deterministic path and still emit an honest HTTP-200 answer.
"""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Any, Callable

from openai import OpenAI

_SYSTEM_PROMPT = (
    "You are the company brain for Al Dente S.r.l. Answer ONLY from the provided "
    "sources (CRM/ERP/calls facts and KB documents). If the sources do not support "
    "an answer, say the information is not available - never invent customers, "
    "numbers, prices, lots, or policies. Be concise and technical."
)

_AGENT_SYSTEM_PROMPT = (
    "You are the company brain for Al Dente S.r.l., a pasta maker selling to "
    "supermarkets (GDO), distributors, and restaurants (horeca). Answer the user's "
    "question using ONLY the provided tools, which read the company's CRM, ERP, call "
    "logs, and knowledge base.\n"
    "Rules:\n"
    "- Never invent customers, numbers, prices, lots, suppliers, or policies. If a tool "
    "reports something is not found or not available, say so plainly.\n"
    "- Verify premises: when the question names a customer, SKU, or lot, confirm it exists "
    "via a tool before answering. Resolve a customer first to get its id, then use that id.\n"
    "- Report figures (counts, totals, prices) exactly as the tools return them; never "
    "recompute or estimate numbers yourself.\n"
    "- When an official document and a phone call disagree, the official document wins.\n"
    "- Prefer the fewest, most targeted tool calls. Once you have enough facts, give a "
    "concise, technical final answer that states the concrete numbers."
)

# Known tool-calling-capable Regolo model ids, in preference order. The /models
# probe intersects this with what is actually live on the account.
_PREFERRED_MODELS = (
    "gpt-oss-120b",
    "Llama-3.3-70B-Instruct",
    "mistral-small-3.2-24B-instruct-2506",
    "Qwen3-32B",
)


def _timeout() -> float:
    raw = os.getenv("LLM_TIMEOUT", "15")
    try:
        return float(raw)
    except ValueError:
        return 15.0


def _agent_budget() -> float:
    """Wall-clock budget for the whole tool-calling loop (kept under /ask's 30s)."""
    raw = os.getenv("LLM_AGENT_BUDGET", "22")
    try:
        return float(raw)
    except ValueError:
        return 22.0


def _max_steps() -> int:
    raw = os.getenv("LLM_MAX_STEPS", "5")
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def _client() -> OpenAI | None:
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    if not (api_key and base_url):
        return None
    try:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=_timeout())
    except Exception:
        return None


@lru_cache(maxsize=1)
def _live_model_ids() -> tuple[str, ...]:
    """Live model ids from GET {LLM_BASE_URL}/models (empty tuple on any failure)."""
    client = _client()
    if client is None:
        return ()
    try:
        listing = client.models.list()
        return tuple(str(model.id) for model in listing.data if getattr(model, "id", None))
    except Exception:
        return ()


@lru_cache(maxsize=1)
def select_model() -> str | None:
    """Pick the model that powers the agent loop.

    Order: explicit env MODEL > first live id from the preference list > first
    live id of any kind > env MODEL_FALLBACK. Returns None if nothing is usable.
    """
    env_model = (os.getenv("MODEL") or "").strip()
    if env_model:
        return env_model
    live = _live_model_ids()
    for candidate in _PREFERRED_MODELS:
        if candidate in live:
            return candidate
    if live:
        return live[0]
    return (os.getenv("MODEL_FALLBACK") or "").strip() or None


def _candidate_models() -> list[str]:
    ordered = [select_model(), (os.getenv("MODEL_FALLBACK") or "").strip()]
    result: list[str] = []
    for model in ordered:
        model = (model or "").strip()
        if model and model not in result:
            result.append(model)
    return result


def _content_of(message: Any) -> str | None:
    content = getattr(message, "content", None) or getattr(message, "reasoning_content", None)
    if content and str(content).strip():
        return str(content).strip()
    return None


def _assistant_tool_message(message: Any, tool_calls: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ],
    }


def run_agent(
    question: str,
    tool_specs: list[dict[str, Any]],
    dispatch: Callable[[str, dict[str, Any]], str],
    *,
    budget_s: float | None = None,
    max_steps: int | None = None,
) -> str | None:
    """Run a Regolo tool-calling loop and return the final answer text, or None.

    `dispatch(name, args)` executes a tool and returns its result as a string.
    """
    client = _client()
    model = select_model()
    if client is None or not model or not tool_specs:
        return None

    deadline = time.monotonic() + (budget_s if budget_s is not None else _agent_budget())
    steps = max_steps if max_steps is not None else _max_steps()
    per_call_timeout = _timeout()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    try:
        for step in range(steps):
            time_left = deadline - time.monotonic()
            if time_left <= 1.0:
                break
            call_timeout = min(per_call_timeout, max(time_left, 1.0))
            allow_tools = step < steps - 1
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": 0,
                "timeout": call_timeout,
            }
            if allow_tools:
                kwargs["tools"] = tool_specs
                kwargs["tool_choice"] = "auto"
            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if allow_tools and tool_calls:
                messages.append(_assistant_tool_message(message, tool_calls))
                for call in tool_calls:
                    name = call.function.name
                    try:
                        args = json.loads(call.function.arguments or "{}")
                        if not isinstance(args, dict):
                            args = {}
                    except (TypeError, ValueError):
                        args = {}
                    try:
                        result = dispatch(name, args)
                    except Exception as exc:  # never break the loop on a tool error
                        result = f"tool_error: {type(exc).__name__}"
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": name,
                            "content": result if isinstance(result, str) else json.dumps(result),
                        }
                    )
                continue
            answer = _content_of(message)
            if answer:
                return answer
            messages.append(
                {"role": "user", "content": "Give your final answer now using the facts you gathered."}
            )
        return _final_synthesis(client, model, messages, deadline, per_call_timeout)
    except Exception:
        return _salvage(messages)


def _final_synthesis(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    deadline: float,
    per_call_timeout: float,
) -> str | None:
    time_left = deadline - time.monotonic()
    if time_left <= 0.5:
        return _salvage(messages)
    final_messages = [
        *messages,
        {"role": "user", "content": "Based only on the gathered facts, give your final answer now."},
    ]
    try:
        response = client.chat.completions.create(
            model=model,
            messages=final_messages,
            temperature=0,
            timeout=min(per_call_timeout, max(time_left, 1.0)),
        )
        answer = _content_of(response.choices[0].message)
        if answer:
            return answer
    except Exception:
        pass
    return _salvage(messages)


def _salvage(messages: list[dict[str, Any]]) -> str | None:
    """Last resort: stitch together the tool outputs we already gathered."""
    facts = [
        str(m.get("content"))
        for m in messages
        if m.get("role") == "tool" and m.get("content") and not str(m.get("content")).startswith("tool_error")
    ]
    if facts:
        return " ".join(facts)[:1500]
    return None


def grounded_answer(question: str, context: str) -> str | None:
    """No-tools synthesis from pre-gathered context, or None if unavailable.

    Used by the deterministic fallback path when tool-calling is not in play.
    """
    client = _client()
    models = _candidate_models()
    if client is None or not models or not context:
        return None

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Question: {question}\n\nSources:\n{context}"},
    ]
    for model in models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                max_tokens=400,
                timeout=_timeout(),
            )
            answer = _content_of(response.choices[0].message)
            if answer:
                return answer
        except Exception:
            continue
    return None
