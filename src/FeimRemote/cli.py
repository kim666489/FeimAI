"""Interactive command-line client for a FeimRemote Host."""

import argparse
import getpass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def _request(base_url: str, path: str, body: dict | None = None,
             token: str = "") -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base_url.rstrip("/") + path, data=data, headers=headers,
                      method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"FeimRemote HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not connect to FeimRemote: {exc.reason}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("FeimRemote returned an invalid response")
    return payload


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Host URL must start with http:// or https://")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use HTTPS for remote Hosts; plain HTTP is allowed only on loopback")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with a FeimRemote Host")
    parser.add_argument("--url", required=True, help="Host base URL, e.g. https://your-tunnel.example")
    parser.add_argument("--username", help="FeimRemote account name")
    parser.add_argument("--message", help="Send one message and exit")
    args = parser.parse_args(argv)
    try:
        _validate_url(args.url)
        username = args.username or input("Username: ").strip()
        password = getpass.getpass("Password: ")
        result = _request(args.url, "/remote/api/login",
                          {"username": username, "password": password})
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Login response did not contain a token")
        if args.message:
            result = _request(args.url, "/remote/api/chat", {"message": args.message}, token)
            print(result.get("reply", ""))
            return 0

        history = _request(args.url, "/remote/api/history", token=token)
        for message in history.get("messages", []):
            role = "You" if message.get("role") == "user" else "FeimAI"
            print(f"{role}: {message.get('content', '')}")
        print("Connected. Type /quit to exit.")
        while True:
            try:
                message = input("You> ").strip()
            except EOFError:
                break
            if message.casefold() in {"/quit", "/exit"}:
                break
            if not message:
                continue
            result = _request(args.url, "/remote/api/chat", {"message": message}, token)
            print(f"FeimAI> {result.get('reply', '')}")
        return 0
    except (ValueError, RuntimeError) as exc:
        print(f"FeimRemote: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
