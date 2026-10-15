"""FeimRemote web API, authenticated chat, and host-side tool execution."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .auth import TokenStore

LOG = logging.getLogger("feimai.remote")
_USER_ID = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_ATTEMPTS = 6
_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_LOGIN_LOCK = threading.Lock()

_WEB_APP = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FeimRemote</title><style>
body{font:16px system-ui;background:#17191d;color:#eee;max-width:820px;margin:2rem auto;padding:0 1rem}
input,textarea,button{font:inherit;border-radius:6px;border:1px solid #555;padding:.7rem;background:#252930;color:#eee}
input,textarea{box-sizing:border-box;width:100%;margin:.35rem 0 1rem}button{cursor:pointer;background:#087eb5;margin:.2rem}
#messages{white-space:pre-wrap;min-height:45vh;border:1px solid #393d43;padding:1rem;border-radius:8px;overflow-wrap:anywhere}
.row{display:flex;gap:.5rem}.row button{white-space:nowrap}.hidden{display:none}.small{color:#aaa;font-size:.9rem}
</style></head><body>
<h1>FeimRemote</h1><p class="small">Remote requests use the Host's existing FeimAI/Ollama server. Host tool permissions apply.</p>
<section id="login"><label>Username<input id="username" autocomplete="username"></label>
<label>Password<input id="password" type="password" autocomplete="current-password"></label>
<button id="loginButton">Sign in</button></section>
<section id="chat" class="hidden"><div class="row"><button id="logoutButton">Sign out</button>
<button id="clearButton">Clear my chat history</button><button id="voiceButton">🎙 Speak</button></div>
<div id="messages"></div><label for="prompt">Message FeimAI on the Host</label>
<textarea id="prompt" rows="3" placeholder="Type a request for the Host"></textarea>
<button id="sendButton">Send</button><p id="status" class="small"></p></section>
<script>
let token=sessionStorage.getItem("feimremote_token")||"";
const $=id=>document.getElementById(id);
function status(text){$("status").textContent=text}
function authHeaders(){return {"Authorization":"Bearer "+token,"Content-Type":"application/json"}}
function showChat(yes){$("login").classList.toggle("hidden",yes);$("chat").classList.toggle("hidden",!yes)}
function addLine(role,text){const p=document.createElement("p");p.textContent=role+": "+text;$("messages").appendChild(p)}
async function login(){try{const r=await fetch("/remote/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:$("username").value,password:$("password").value})});const d=await r.json();if(!r.ok)throw Error(d.error||"Sign-in failed");token=d.token;sessionStorage.setItem("feimremote_token",token);$("password").value="";showChat(true);await loadHistory()}catch(e){alert(e.message)}}
async function loadHistory(){const r=await fetch("/remote/api/history",{headers:authHeaders()});if(r.status===401){logout(false);return}const d=await r.json();$("messages").textContent="";for(const m of d.messages||[])addLine(m.role==="user"?"You":"FeimAI",m.content)}
async function send(){const text=$("prompt").value.trim();if(!text)return;$("prompt").value="";addLine("You",text);$("sendButton").disabled=true;status("Sending to Host...");try{const r=await fetch("/remote/api/chat",{method:"POST",headers:authHeaders(),body:JSON.stringify({message:text})});const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");addLine("FeimAI",d.reply);status("")}catch(e){status(e.message)}finally{$("sendButton").disabled=false}}
async function logout(callServer=true){if(callServer&&token)await fetch("/remote/api/logout",{method:"POST",headers:authHeaders()}).catch(()=>{});token="";sessionStorage.removeItem("feimremote_token");showChat(false)}
async function clearHistory(){if(!confirm("Clear your saved FeimRemote chat history?"))return;const r=await fetch("/remote/api/history",{method:"DELETE",headers:authHeaders()});if(!r.ok){status("Could not clear history");return}$("messages").textContent=""}
$("loginButton").onclick=login;$("sendButton").onclick=send;$("logoutButton").onclick=()=>logout();$("clearButton").onclick=clearHistory;
$("prompt").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();send()}});
if(token){showChat(true);loadHistory()}
const SpeechRecognition=window.SpeechRecognition||window.webkitSpeechRecognition;
if(!SpeechRecognition){$("voiceButton").disabled=true;$("voiceButton").title="Speech recognition is not supported in this browser"}
else $("voiceButton").onclick=()=>{const rec=new SpeechRecognition();rec.lang="th-TH";rec.interimResults=false;rec.onstart=()=>status("Listening in this browser...");rec.onerror=e=>status("Voice input error: "+e.error);rec.onresult=e=>{$("prompt").value=e.results[0][0].transcript;status("Speech recognized. Review it, then press Send.")};rec.onend=()=>{if($("status").textContent==="Listening in this browser...")status("")};rec.start()}
</script></body></html>"""


def _send_json(handler: Any, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _json_body(handler: Any) -> dict[str, Any]:
    try:
        size = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("invalid Content-Length") from exc
    if size <= 0 or size > 1024 * 1024:
        raise ValueError("request body must be between 1 byte and 1 MiB")
    payload = json.loads(handler.rfile.read(size))
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    return payload


def _too_many_attempts(address: str) -> bool:
    now = time.monotonic()
    with _LOGIN_LOCK:
        attempts = _LOGIN_ATTEMPTS[address]
        while attempts and attempts[0] < now - _LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
            return True
        attempts.append(now)
    return False


def _token_username(handler: Any) -> str | None:
    authorization = handler.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    return handler.server.remote_tokens.username_for(authorization[7:].strip())


def handle_get(handler: Any, path: str) -> bool:
    if path == "/remote":
        config = handler.server.remote_config
        if not config.get("enabled"):
            _send_json(handler, 404, {"error": "FeimRemote is disabled on this Host"})
            return True
        page = _WEB_APP.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(page)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "no-referrer")
        handler.end_headers()
        handler.wfile.write(page)
        return True
    if not path.startswith("/remote/api/"):
        return False
    if not handler.server.remote_config.get("enabled"):
        _send_json(handler, 404, {"error": "FeimRemote is disabled on this Host"})
        return True
    if path == "/remote/api/history":
        username = _token_username(handler)
        if not username:
            _send_json(handler, 401, {"error": "Sign in required"})
            return True
        _send_json(handler, 200, {"messages": _load_history(handler.server, username)})
        return True
    return False


def handle_post(handler: Any, path: str) -> bool:
    if not path.startswith("/remote/api/"):
        return False
    config = handler.server.remote_config
    if not config.get("enabled"):
        _send_json(handler, 404, {"error": "FeimRemote is disabled on this Host"})
        return True

    if path == "/remote/api/login":
        try:
            payload = _json_body(handler)
        except (ValueError, json.JSONDecodeError) as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return True
        username = payload.get("username", "")
        password = payload.get("password", "")
        address = handler.client_address[0]
        if not isinstance(username, str) or not isinstance(password, str):
            _send_json(handler, 400, {"error": "Username and password must be strings"})
            return True
        if not _USER_ID.fullmatch(username):
            _send_json(handler, 401, {"error": "Invalid username or password"})
            return True
        if _too_many_attempts(address):
            _send_json(handler, 429, {"error": "Too many sign-in attempts; wait one minute"})
            return True
        token = handler.server.remote_tokens.login(username, password)
        if not token:
            _send_json(handler, 401, {"error": "Invalid username or password"})
            return True
        with _LOGIN_LOCK:
            _LOGIN_ATTEMPTS.pop(address, None)
        _send_json(handler, 200, {"token": token, "username": username})
        return True

    username = _token_username(handler)
    if not username:
        _send_json(handler, 401, {"error": "Sign in required"})
        return True
    if path == "/remote/api/logout":
        authorization = handler.headers.get("Authorization", "")
        handler.server.remote_tokens.revoke(authorization[7:].strip())
        _send_json(handler, 200, {"ok": True})
        return True
    if path == "/remote/api/chat":
        try:
            payload = _json_body(handler)
        except (ValueError, json.JSONDecodeError) as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return True
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            _send_json(handler, 400, {"error": "message must be a non-empty string"})
            return True
        if len(message) > 12_000:
            _send_json(handler, 413, {"error": "message exceeds 12000 characters"})
            return True
        try:
            reply = _chat(handler.server, username, message.strip())
        except Exception as exc:
            LOG.exception("FeimRemote chat failed for user %s", username)
            _send_json(handler, 502, {"error": f"Remote chat failed: {exc}"})
            return True
        _send_json(handler, 200, {"reply": reply})
        return True
    _send_json(handler, 404, {"error": "Unknown FeimRemote endpoint"})
    return True


def handle_delete(handler: Any, path: str) -> bool:
    if path != "/remote/api/history":
        return False
    if not handler.server.remote_config.get("enabled"):
        _send_json(handler, 404, {"error": "FeimRemote is disabled on this Host"})
        return True
    username = _token_username(handler)
    if not username:
        _send_json(handler, 401, {"error": "Sign in required"})
        return True
    with _user_lock(handler.server, username):
        with handler.server.remote_history_lock:
            histories = dict(_history_store(handler.server))
            histories.pop(username, None)
            _save_history(handler.server, histories)
    _send_json(handler, 200, {"ok": True})
    return True


def _history_store(server: Any) -> dict[str, list[dict[str, str]]]:
    cached = getattr(server, "remote_history", None)
    if cached is not None:
        return cached
    path = Path(server.remote_config["history_file"]).expanduser()
    if path.is_file():
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            raise ValueError(f"FeimRemote history must be an object: {path}")
        cached = {
            username: messages for username, messages in data.items()
            if isinstance(username, str) and isinstance(messages, list)
            and all(isinstance(m, dict) and m.get("role") in {"user", "assistant"}
                    and isinstance(m.get("content"), str) for m in messages)
        }
    else:
        cached = {}
    server.remote_history = cached
    return cached


def _save_history(server: Any, histories: dict[str, list[dict[str, str]]]) -> None:
    path = Path(server.remote_config["history_file"]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with server.remote_history_lock:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(histories, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
        server.remote_history = histories


def _load_history(server: Any, username: str) -> list[dict[str, str]]:
    with server.remote_history_lock:
        return list(_history_store(server).get(username, []))


def _user_lock(server: Any, username: str) -> threading.Lock:
    with server.remote_user_locks_lock:
        return server.remote_user_locks.setdefault(username, threading.Lock())


def _chat(server: Any, username: str, message: str) -> str:
    with _user_lock(server, username):
        return _chat_for_user(server, username, message)


def _chat_for_user(server: Any, username: str, message: str) -> str:
    from FeimUI import ToolBox, _get

    remote_cfg = server.remote_config
    main_cfg = server.feimai_config
    with server.remote_history_lock:
        history = list(_history_store(server).get(username, []))
    history.append({"role": "user", "content": message})

    host_cfg = json.loads(json.dumps(main_cfg))
    host_tools = host_cfg["tools"]
    permissions = remote_cfg["tool_permissions"]
    for operation, settings in host_tools["ops"].items():
        allowed = bool(permissions.get(operation, False))
        settings["enabled"] = allowed
        settings["confirm"] = False
    host_tools["enabled"] = any(permissions.values())
    host_cfg["modules"]["enabled"] = False

    toolbox = ToolBox(host_cfg, lambda *_: False)
    tools = toolbox.schemas()
    model = (remote_cfg.get("model") or main_cfg.get("api", {}).get("model")
             or main_cfg.get("local", {}).get("model", ""))
    if not model:
        models = server.ollama_client.list()
        entries = _get(models, "models", []) or []
        model = _get(entries[0], "model") or _get(entries[0], "name") if entries else ""
    if not model:
        raise RuntimeError("No Ollama model is available; configure one in FeimRemote Settings")

    system = main_cfg.get("prompt", "").strip()
    if tools:
        system += (
            "\nOnly use the host tools when the user explicitly asks for a host action. "
            "Never claim a host action succeeded until its tool result confirms it. "
            "The host has granted only the tools in this request.")
    messages = ([{"role": "system", "content": system}] if system else []) + history
    max_steps = max(1, min(10, int(remote_cfg.get("max_tool_steps", 4))))
    reply = ""

    for step in range(max_steps):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": main_cfg.get("options", {}),
            "keep_alive": main_cfg.get("server", {}).get("ollama_keep_alive", "10m"),
        }
        if tools:
            kwargs["tools"] = tools
        result = server.ollama_client.chat(**kwargs)
        assistant = _get(result, "message", {}) or {}
        content = _get(assistant, "content", "") or ""
        calls = _get(assistant, "tool_calls", []) or []
        assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
        normalized_calls = []
        for call in calls:
            function = _get(call, "function", {}) or {}
            name = _get(function, "name", "")
            arguments = _get(function, "arguments", {}) or {}
            if not isinstance(arguments, dict):
                raise ValueError(f"Invalid tool arguments returned for {name}")
            normalized_calls.append({"name": name, "arguments": arguments})
        if normalized_calls:
            assistant_message["tool_calls"] = [
                {"function": {"name": call["name"], "arguments": call["arguments"]}}
                for call in normalized_calls
            ]
            messages.append(assistant_message)
            toolbox_names = {item["function"]["name"] for item in tools or []}
            for call in normalized_calls:
                name, arguments = call["name"], call["arguments"]
                if name not in toolbox_names:
                    messages.append({"role": "tool", "tool_name": name,
                                     "content": f"ERROR: tool '{name}' is not permitted"})
                    continue
                outcome = toolbox.call(name, arguments)
                messages.append({"role": "tool", "tool_name": name, "content": outcome})
            continue
        reply = content
        break
    else:
        if normalized_calls:
            reply = "Stopped after reaching the FeimRemote tool-step limit."

    history.extend([
        {"role": "assistant", "content": reply or "(No response)"},
    ])
    limit = max(2, int(remote_cfg.get("max_history_messages", 40)))
    history = history[-limit:]
    with server.remote_history_lock:
        stored = dict(_history_store(server))
        stored[username] = history
        _save_history(server, stored)
    return reply
