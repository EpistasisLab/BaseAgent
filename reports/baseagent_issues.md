# BaseAgent Issues Found During CardioKB Build (2026-05-16)

## 1. `AnthropicFoundry` env var conflict (llm.py:531-570)
**Severity:** Blocker
**Error:** `ValueError: base_url and resource are mutually exclusive`
**Root cause:** SDK v0.95.0's `AnthropicFoundry` auto-reads both `ANTHROPIC_FOUNDRY_BASE_URL` and `ANTHROPIC_FOUNDRY_RESOURCE` from environment. If a user has both set (e.g., `ANTHROPIC_FOUNDRY_RESOURCE` from an older Azure setup in their shell profile), the constructor rejects the combination — even though `llm.py` only passes `base_url` explicitly.
**Workaround:** User must `unset ANTHROPIC_FOUNDRY_RESOURCE` before running.
**Fix suggestion:** In `_build_model_kwargs` for `AnthropicFoundry`, explicitly pass `resource=None` to override env auto-detection, or `os.environ.pop('ANTHROPIC_FOUNDRY_RESOURCE', None)` before constructing the client.

## 2. `temperature` not stripped for Claude Opus 4.7 (llm.py:386-393)
**Severity:** Blocker
**Error:** `Error code: 400 - temperature is deprecated for this model`
**Root cause:** `_build_model_kwargs` always passes `temperature` from config (default `0.7`). Claude Opus 4.7 (a thinking model) rejects any `temperature` value. There's special handling for `gpt-5` but not for Opus 4.7.
**Workaround:** Patched `llm.py` to pop temperature when model contains `opus-4-7`.
**Fix suggestion:** Add model-aware temperature handling similar to the `gpt-5` block. Consider a general approach: strip `temperature` for any model that returns a 400 on it, or maintain a list of thinking models (`opus-4-7`, future ones) that don't accept it.

## 3. Class-level property patch on `ChatAnthropic._client` (llm.py:566-567)
**Severity:** Warning (latent bug)
**Description:** The `AnthropicFoundry` special case patches `chat.__class__._client = property(...)` — this modifies the **class**, not the instance. Every subsequent `ChatAnthropic` instance (across all agents) shares the last-patched property. In a multi-agent setup with 8+ agents, each agent overwrites the previous agent's client property. This works by accident because the closure captures the correct credentials each time and the cache dict is per-closure, but it's fragile.
**Fix suggestion:** Use instance-level patching or a custom subclass instead of modifying `ChatAnthropic.__class__`.
