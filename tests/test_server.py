import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


class FakeOllama:
    def __init__(self, host):
        self.host = host

    def chat(self, **kwargs):
        self.last_chat = kwargs
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
        with urlopen(self.base_url + "/v1/models", timeout=3) as response:
            body = json.loads(response.read())
        self.assertEqual(body["object"], "list")
        self.assertEqual(body["data"][0]["id"], "test-model")

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
