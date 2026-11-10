"""LLM client: Ollama (local, first choice) -> Gemini / Google AI Studio (fallback).  No third-party packages.

Configuration (environment variables, all optional):
  LLM_PROVIDER   auto (default) | ollama | gemini | none
  OLLAMA_HOST    default http://localhost:11434
  OLLAMA_MODEL   default: first installed of qwen2.5, llama3.1, llama3.2, gemma2, gemma3, mistral, else first installed
  GEMINI_API_KEY (or GOOGLE_API_KEY)     GEMINI_MODEL default gemini-2.5-flash

The LLM is used for exactly two language jobs (see planner.py / compose.py); every fact, count, percentage and
ranking is computed by code from the database.  If no provider answers, the chatbot falls back to its rule-based mode.
"""
import json
import os
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
PREFERRED = ("qwen2.5", "llama3.1", "llama3.2", "gemma2", "gemma3", "mistral")
_state = {"ollama_ok": None, "last": None}


def _http(url, body=None, timeout=60):
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _provider_mode():
    return os.environ.get("LLM_PROVIDER", "auto").lower()


def ollama_model():
    """Model name to use, or None if Ollama is not reachable / has no models."""
    if _state["ollama_ok"] is False:
        return None
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        names = [m["name"] for m in _http(host + "/api/tags", timeout=3).get("models", [])]
    except Exception:
        _state["ollama_ok"] = False
        return None
    _state["ollama_ok"] = bool(names)
    want = os.environ.get("OLLAMA_MODEL")
    if want:
        return want
    for p in PREFERRED:
        for n in names:
            if n.startswith(p):
                return n
    return names[0] if names else None


def gemini_key():
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def status():
    mode = _provider_mode()
    if mode == "none":
        return "LLM off (LLM_PROVIDER=none) - rule-based mode"
    parts = []
    if mode in ("auto", "ollama"):
        m = ollama_model()
        parts.append(f"ollama:{m}" if m else "ollama: not reachable")
    if mode in ("auto", "gemini"):
        parts.append("gemini: key set (fallback)" if gemini_key() else "gemini: no key")
    return "LLM providers -> " + " | ".join(parts)


def available():
    mode = _provider_mode()
    if mode == "none":
        return False
    if mode in ("auto", "ollama") and ollama_model():
        return True
    return mode in ("auto", "gemini") and bool(gemini_key())


def _ollama(prompt, system, json_mode, timeout):
    model = ollama_model()
    if not model:
        return None
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": model, "messages": msgs, "stream": False, "options": {"temperature": 0}}
    if json_mode:
        body["format"] = "json"
    out = _http(host + "/api/chat", body, timeout)["message"]["content"].strip()
    _state["last"] = f"ollama:{model}"
    return out


def _gemini(prompt, system, json_mode, timeout):
    key = gemini_key()
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    cfg = {"temperature": 0}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = _http(GEMINI_URL.format(model=model, key=key), body, timeout)
    _state["last"] = f"gemini:{model}"
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate(prompt, system=None, json_mode=False, timeout=120):
    """Try Ollama, then Gemini.  Returns text, or None if every provider failed."""
    mode = _provider_mode()
    if mode == "none":
        return None
    order = []
    if mode in ("auto", "ollama"):
        order.append(_ollama)
    if mode in ("auto", "gemini"):
        order.append(_gemini)
    for fn in order:
        try:
            out = fn(prompt, system, json_mode, timeout)
            if out:
                return out
        except Exception:
            continue
    return None


def last_provider():
    return _state["last"]
