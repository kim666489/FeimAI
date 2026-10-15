"""OpenAI-compatible HTTP API for FeimAI, backed by the configured Ollama host."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ollama
from FeimUI import DEFAULT_CONFIG, ImageGen, deepMerge
from FeimRemote.auth import TokenStore
from FeimRemote.config import load_remote_config
from FeimRemote.service import handle_delete, handle_get, handle_post

LOG = logging.getLogger("feimai.server")
MAX_BODY_BYTES = 32 * 1024 * 1024


def load_server_config() -> dict[str, Any]:
    """Load the same config used by src/app.py, with root config as fallback."""
    config_path = ROOT / "config" / "config.json"
    if not config_path.is_file():
        config_path = ROOT / "config.json"
    if not config_path.is_file():
        return deepMerge(DEFAULT_CONFIG, {})
    with config_path.open("r", encoding="utf-8") as config_file:
        loaded = json.load(config_file)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration must be a JSON object: {config_path}")
    return deepMerge(DEFAULT_CONFIG, loaded)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _openai_error(message: str, error_type: str = "invalid_request_error",
                  code: str | None = None) -> dict[str, Any]:
    return {"error": {"message": message, "type": error_type, "param": None, "code": code}}


def _extract_message_content(content: Any) -> tuple[str, list[str]]:
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        raise ValueError("message content must be a string or an array of content parts")

    text_parts: list[str] = []
    images: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text_parts.append(str(part.get("text") or ""))
        elif part.get("type") == "image_url":
            image_url = part.get("image_url") or {}
            url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
            if not isinstance(url, str) or not url.startswith("data:image/"):
                raise ValueError("only base64 data URLs are accepted for image content")
            header, separator, payload = url.partition(",")
            if not separator or ";base64" not in header:
                raise ValueError("image content must use a base64 data URL")
            try:
                base64.b64decode(payload, validate=True)
                images.append(payload)
            except ValueError as exc:
                raise ValueError("invalid base64 image content") from exc
    return "\n".join(text_parts), images


def to_ollama_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")

    converted: list[dict[str, Any]] = []
    call_names: dict[str, str] = {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        role = message.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"messages[{index}].role is not supported")
        content, images = _extract_message_content(message.get("content", ""))
        item: dict[str, Any] = {"role": role, "content": content}

        if role == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                function = call.get("function") or {}
                name = function.get("name")
                if not isinstance(name, str) or not name:
                    raise ValueError("tool call function name must be a non-empty string")
                arguments = function.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments or "{}")
                    except json.JSONDecodeError as exc:
                        raise ValueError("tool call arguments must be valid JSON") from exc
                if not isinstance(arguments, dict):
                    raise ValueError("tool call arguments must be a JSON object")
                call_id = call.get("id")
                if call_id:
                    call_names[str(call_id)] = name
                calls.append({"function": {"name": name, "arguments": arguments}})
            item["tool_calls"] = calls
        elif role == "tool":
            call_id = message.get("tool_call_id")
            tool_name = message.get("name") or call_names.get(str(call_id), "tool")
            item["tool_name"] = tool_name
        if images:
            item["images"] = images
        converted.append(item)
    return converted


def _model_options(payload: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key in ("temperature", "top_p", "top_k", "num_ctx", "seed", "stop",
                "repeat_penalty", "frequency_penalty", "presence_penalty"):
        if key in payload:
            options[key] = payload[key]
    max_tokens = payload.get("max_completion_tokens", payload.get("max_tokens"))
    if max_tokens is not None:
        options["num_predict"] = max_tokens
    return options


def _tool_calls(message: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for call in _value(message, "tool_calls", []) or []:
        function = _value(call, "function", {}) or {}
        name = _value(function, "name", "")
        if not name:
            continue
        arguments = _value(function, "arguments", {}) or {}
        calls.append({
            "id": "call_" + uuid.uuid4().hex,
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        })
    return calls


class FeimAIHandler(BaseHTTPRequestHandler):
    server_version = "FeimAI-API/1.0"

    @property
    def cfg(self) -> dict[str, Any]:
        return self.server.feimai_config  # type: ignore[attr-defined]

    @property
    def api_key(self) -> str:
        return os.environ.get("FEIMAI_API_KEY", "")

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        expected = self.api_key
        if not expected:
            return True
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        supplied = supplied or self.headers.get("X-API-Key", "")
        if supplied == expected:
            return True
        self._send_json(401, _openai_error("Invalid or missing API key", code="unauthorized"))
        return False

    def _read_json(self) -> dict[str, Any]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if size <= 0:
            raise ValueError("request body is required")
        if size > MAX_BODY_BYTES:
            raise OverflowError(f"request body exceeds {MAX_BODY_BYTES} bytes")
        try:
            payload = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if handle_get(self, path):
                return
        except Exception as exc:
            LOG.exception("FeimRemote GET failed")
            self._send_json(500, _openai_error(str(exc), "server_error", "remote_error"))
            return
        if path == "/health":
            self._send_json(200, {"status": "ok", "backend": "ollama"})
            return
        if path != "/v1/models":
            self._send_json(404, _openai_error("Not found", code="not_found"))
            return
        if not self._authorized():
            return
        try:
            models = self.server.ollama_client.list()  # type: ignore[attr-defined]
            data = []
            for model in _value(models, "models", []) or []:
                name = _value(model, "model") or _value(model, "name")
                if name:
                    data.append({"id": name, "object": "model", "created": int(time.time()),
                                 "owned_by": "ollama"})
            self._send_json(200, {"object": "list", "data": data})
        except Exception as exc:
            LOG.exception("Could not retrieve Ollama models")
            self._send_json(502, _openai_error(f"Could not retrieve Ollama models: {exc}",
                                                "server_error", "ollama_unavailable"))

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if path.startswith("/remote/api/"):
            try:
                if handle_post(self, path):
                    return
            except Exception as exc:
                LOG.exception("FeimRemote request failed")
                self._send_json(500, _openai_error(str(exc), "server_error", "remote_error"))
                return
        if path not in {"/v1/chat/completions", "/v1/images/generations"}:
            self._send_json(404, _openai_error("Not found", code="not_found"))
            return
        if not self._authorized():
            return
        try:
            payload = self._read_json()
            if path == "/v1/images/generations":
                self._generate_image(payload)
            else:
                self._chat_completion(payload)
        except OverflowError as exc:
            self._send_json(413, _openai_error(str(exc), code="request_too_large"))
        except (ValueError, TypeError, KeyError) as exc:
            self._send_json(400, _openai_error(str(exc)))
        except Exception as exc:
            LOG.exception("API request failed")
            self._send_json(502, _openai_error(str(exc), "server_error", "backend_error"))

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        try:
            if handle_delete(self, path):
                return
        except Exception as exc:
            LOG.exception("FeimRemote DELETE failed")
            self._send_json(500, _openai_error(str(exc), "server_error", "remote_error"))
            return
        self._send_json(404, _openai_error("Not found", code="not_found"))

    def _chat_completion(self, payload: dict[str, Any]) -> None:
        model = payload.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        messages = to_ollama_messages(payload.get("messages"))
        stream = payload.get("stream", False)
        if not isinstance(stream, bool):
            raise ValueError("stream must be a boolean")
        if payload.get("tool_choice") == "none":
            tools = None
        else:
            tools = payload.get("tools")
            if tools is not None and not isinstance(tools, list):
                raise ValueError("tools must be an array")
        options = _model_options(payload)
        kwargs: dict[str, Any] = {"model": model, "messages": messages,
                                  "stream": stream, "options": options}
        keep_alive = self.cfg.get("server", {}).get("ollama_keep_alive", "")
        if keep_alive:
            kwargs["keep_alive"] = keep_alive
        if tools:
            kwargs["tools"] = tools
        result = self.server.ollama_client.chat(**kwargs)  # type: ignore[attr-defined]
        if stream:
            self._stream_chat(result, model)
        else:
            self._send_chat_result(result, model)

    def _send_chat_result(self, result: Any, model: str) -> None:
        message = _value(result, "message", {}) or {}
        calls = _tool_calls(message)
        body: dict[str, Any] = {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": _value(message, "content", "") or "",
                            **({"tool_calls": calls} if calls else {})},
                "finish_reason": "tool_calls" if calls else "stop",
            }],
        }
        prompt_tokens = _value(result, "prompt_eval_count")
        completion_tokens = _value(result, "eval_count")
        if prompt_tokens is not None or completion_tokens is not None:
            prompt_tokens = int(prompt_tokens or 0)
            completion_tokens = int(completion_tokens or 0)
            body["usage"] = {"prompt_tokens": prompt_tokens,
                             "completion_tokens": completion_tokens,
                             "total_tokens": prompt_tokens + completion_tokens}
        self._send_json(200, body)

    def _stream_chat(self, result: Any, model: str) -> None:
        completion_id = "chatcmpl-" + uuid.uuid4().hex
        created = int(time.time())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def write_event(data: dict[str, Any] | str) -> None:
            encoded = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            self.wfile.write(("data: " + encoded + "\n\n").encode("utf-8"))
            self.wfile.flush()

        stream_cfg = self.cfg.get("server", {})
        flush_interval = max(0, int(stream_cfg.get("stream_flush_interval_ms", 20))) / 1000
        flush_chars = max(1, int(stream_cfg.get("stream_flush_chars", 256)))
        pending_content = ""
        last_flush = time.monotonic()
        has_tool_calls = False
        calls_by_index: dict[int, dict[str, Any]] = {}

        def flush_content(force: bool = False) -> None:
            nonlocal pending_content, last_flush
            elapsed = time.monotonic() - last_flush
            if pending_content and (force or len(pending_content) >= flush_chars
                                    or elapsed >= flush_interval):
                write_event({
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": pending_content},
                                 "finish_reason": None}],
                })
                pending_content = ""
                last_flush = time.monotonic()

        def merge_arguments(target: dict[str, Any], updates: dict[str, Any]) -> None:
            for key, value in updates.items():
                if isinstance(value, dict) and isinstance(target.get(key), dict):
                    merge_arguments(target[key], value)
                else:
                    target[key] = value

        try:
            for part in result:
                message = _value(part, "message", {}) or {}
                content = _value(message, "content", "") or ""
                if content:
                    pending_content += content
                    flush_content()
                for index, call in enumerate(_tool_calls(message)):
                    has_tool_calls = True
                    function = call["function"]
                    current = calls_by_index.setdefault(index, {
                        "id": call["id"],
                        "name": function["name"],
                        "arguments": {},
                    })
                    current["name"] = function["name"] or current["name"]
                    try:
                        arguments = json.loads(function["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}
                    if isinstance(arguments, dict):
                        merge_arguments(current["arguments"], arguments)

            flush_content(force=True)
            if calls_by_index:
                fragments = [{
                    "index": index,
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                    },
                } for index, call in sorted(calls_by_index.items())]
                write_event({
                    "id": completion_id, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"tool_calls": fragments},
                                 "finish_reason": None}],
                })
            write_event({
                "id": completion_id, "object": "chat.completion.chunk",
                "created": created, "model": model,
                "choices": [{"index": 0, "delta": {},
                             "finish_reason": "tool_calls" if has_tool_calls else "stop"}],
            })
            write_event("[DONE]")
        except (BrokenPipeError, ConnectionResetError):
            LOG.info("Client disconnected during streaming response")
        except Exception as exc:
            LOG.exception("Streaming request failed")
            write_event({"error": {"message": str(exc), "type": "server_error",
                                   "code": "backend_error"}})
            write_event("[DONE]")

    def _generate_image(self, payload: dict[str, Any]) -> None:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if payload.get("response_format", "b64_json") != "b64_json":
            raise ValueError("only response_format='b64_json' is supported")

        width = height = None
        size = payload.get("size")
        if size:
            match = re.fullmatch(r"(\d{1,5})x(\d{1,5})", str(size))
            if not match:
                raise ValueError("size must use the WIDTHxHEIGHT format")
            width, height = map(int, match.groups())
            if width > 8192 or height > 8192:
                raise ValueError("image dimensions cannot exceed 8192 pixels")
        path = ImageGen(self.cfg).generate(
            prompt.strip(), str(payload.get("negative_prompt") or ""), width, height)
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("ascii")
        self._send_json(200, {
            "created": int(datetime.now(timezone.utc).timestamp()),
            "data": [{"b64_json": encoded}],
        })


class FeimAIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config: dict[str, Any]):
        super().__init__(address, FeimAIHandler)
        self.feimai_config = config
        self.ollama_client = ollama.Client(host=config["local"]["host"])
        remote_path = ROOT / "config" / "feimremote.json"
        self.remote_config = load_remote_config(remote_path)
        self.remote_tokens = TokenStore(self.remote_config.get("users", {}))
        self.remote_history = None
        self.remote_history_lock = threading.RLock()
        self.remote_user_locks: dict[str, threading.Lock] = {}
        self.remote_user_locks_lock = threading.Lock()
        if self.remote_config["enabled"] and not self.remote_config["users"]:
            LOG.warning("FeimRemote is enabled but no users are configured")

    def server_close(self) -> None:
        try:
            self.ollama_client.close()
        finally:
            super().server_close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.environ.get("FEIMAI_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("FEIMAI_PORT", "8000"))
    except ValueError as exc:
        raise SystemExit("FEIMAI_PORT must be an integer") from exc
    if not 0 < port < 65536:
        raise SystemExit("FEIMAI_PORT must be between 1 and 65535")
    if host not in {"localhost", "127.0.0.1", "::1"} and not os.environ.get("FEIMAI_API_KEY"):
        raise SystemExit("Set FEIMAI_API_KEY before binding the API server to a non-local address")

    config = load_server_config()
    server = FeimAIServer((host, port), config)
    LOG.info("FeimAI API listening on http://%s:%s", host, port)
    LOG.info("Ollama host: %s", config["local"]["host"])
    if server.remote_config["enabled"]:
        LOG.info("FeimRemote enabled at http://%s:%s/remote",
                 host, port)
        LOG.info("Use HTTPS at the tunnel/proxy; the FeimAI server itself is HTTP")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Stopping FeimAI API server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
