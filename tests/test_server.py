import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from FeimRemote.auth import TokenStore, hash_password


class FakeOllama:
    last_chat = None

    def __init__(self, host):
        self.host = host

    def chat(self, **kwargs):
        type(self).last_chat = kwargs
        return {
            "message": {
                "role": "assistant",
                "content": "Hello",
                "tool_calls": [],
            },
            "prompt_eval_count": 3,
            "eval_count": 2,
        }

    def list(self):
        return {"models": [{"model": "test-model"}]}

    def close(self):
        pass


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = server.deepMerge(server.DEFAULT_CONFIG, {})
        cls.mock_client = patch("server.ollama.Client", FakeOllama)
        cls.mock_client.start()
        cls.httpd = server.FeimAIServer(("127.0.0.1", 0), cls.config)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.mock_client.stop()

    def post(self, path, body, headers=None):
        request = Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return response.status, response.headers, response.read()

    def test_models_endpoint_returns_openai_list(self):
        client = self.httpd.ollama_client
        with urlopen(self.base_url + "/v1/models", timeout=3) as response:
            body = json.loads(response.read())
        self.assertEqual(body["object"], "list")
        self.assertEqual(body["data"][0]["id"], "test-model")
        self.assertIs(self.httpd.ollama_client, client)

    def test_chat_completion_maps_request_and_usage(self):
        status, _, raw = self.post("/v1/chat/completions", {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.2,
        })
        body = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(body["choices"][0]["message"]["content"], "Hello")
        self.assertEqual(body["usage"]["total_tokens"], 5)
        self.assertEqual(FakeOllama.last_chat["keep_alive"], "10m")

    def test_streaming_completion_uses_sse(self):
        with patch.object(FakeOllama, "chat", return_value=iter([
                {"message": {"role": "assistant", "content": "Hi", "tool_calls": []}}
        ])):
            _, headers, raw = self.post("/v1/chat/completions", {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            })
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn(b'"content": "Hi"', raw)
        self.assertIn(b"data: [DONE]", raw)

    def test_streaming_batches_content_and_emits_tool_call_once(self):
        tool_chunks = iter([
            {"message": {"role": "assistant", "content": "Hello ",
                         "tool_calls": [{"function": {
                             "name": "read_file", "arguments": {"path": "notes.txt"}}}]}},
            {"message": {"role": "assistant", "content": "there",
                         "tool_calls": [{"function": {
                             "name": "read_file", "arguments": {"start_line": 2}}}]}},
        ])
        with patch.object(FakeOllama, "chat", return_value=tool_chunks):
            _, headers, raw = self.post("/v1/chat/completions", {
                "model": "test-model",
                "messages": [{"role": "user", "content": "Read the file"}],
                "stream": True,
                "tools": [],
            })
        self.assertEqual(headers["X-Accel-Buffering"], "no")
        events = [
            json.loads(block[6:])
            for block in raw.decode("utf-8").split("\n\n")
            if block.startswith("data: {")
        ]
        content_events = [
            event for event in events
            if event.get("choices", [{}])[0].get("delta", {}).get("content")
        ]
        tool_events = [
            event for event in events
            if event.get("choices", [{}])[0].get("delta", {}).get("tool_calls")
        ]
        self.assertEqual(len(content_events), 1)
        self.assertEqual(content_events[0]["choices"][0]["delta"]["content"], "Hello there")
        self.assertEqual(len(tool_events), 1)
        call = tool_events[0]["choices"][0]["delta"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "read_file")
        self.assertEqual(json.loads(call["function"]["arguments"]), {
            "path": "notes.txt", "start_line": 2,
        })

    def test_invalid_messages_return_openai_error(self):
        request = Request(
            self.base_url + "/v1/chat/completions",
            data=b'{"model":"test-model","messages":[]}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 400)
        body = json.loads(caught.exception.read())
        self.assertIn("messages", body["error"]["message"])

    def test_api_key_is_required_when_configured(self):
        with patch.dict(os.environ, {"FEIMAI_API_KEY": "test-secret"}):
            request = Request(self.base_url + "/v1/models")
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 401)

    def test_remote_login_chat_and_per_user_history_reuse_server_client(self):
        user = {"password": hash_password("correct horse battery staple")}
        self.httpd.remote_config = {
            "enabled": True,
            "users": {"owner": user},
            "tool_permissions": {name: False for name in self.config["tools"]["ops"]},
            "history_file": str(server.ROOT / "data" / "test_remote_history.json"),
            "max_history_messages": 40,
            "max_tool_steps": 4,
            "model": "test-model",
        }
        self.httpd.remote_tokens = TokenStore(self.httpd.remote_config["users"])
        self.httpd.remote_history = {}
        self.httpd.remote_history_lock = threading.RLock()
        self.httpd.remote_user_locks = {}
        self.httpd.remote_user_locks_lock = threading.Lock()
        client = self.httpd.ollama_client
        history_path = server.Path(self.httpd.remote_config["history_file"])
        try:
            status, _, login_raw = self.post("/remote/api/login", {
                "username": "owner",
                "password": "correct horse battery staple",
            })
            self.assertEqual(status, 200)
            token = json.loads(login_raw)["token"]
            status, _, chat_raw = self.post("/remote/api/chat", {"message": "Hello"}, {
                "Authorization": f"Bearer {token}",
            })
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(chat_raw)["reply"], "Hello")
            self.assertIs(self.httpd.ollama_client, client)
            stored = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["owner"][0]["content"], "Hello")
            self.assertEqual(stored["owner"][-1]["role"], "assistant")
        finally:
            history_path.unlink(missing_ok=True)
            self.httpd.remote_history = None
            self.httpd.remote_config["enabled"] = False

    def test_remote_api_rejects_unauthenticated_history(self):
        self.httpd.remote_config = {"enabled": True}
        request = Request(self.base_url + "/remote/api/history")
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 401)
        self.httpd.remote_config["enabled"] = False

    def test_openai_tool_history_maps_to_ollama_format(self):
        messages = server.to_ollama_messages([
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call-a",
                "type": "function",
                "function": {"name": "list_dir", "arguments": "{\"path\":\".\"}"},
            }]},
            {"role": "tool", "tool_call_id": "call-a", "content": "file.txt"},
        ])
        self.assertEqual(messages[0]["tool_calls"][0]["function"]["arguments"], {"path": "."})
        self.assertEqual(messages[1]["tool_name"], "list_dir")


if __name__ == "__main__":
    unittest.main()
