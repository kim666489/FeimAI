import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from FeimRemote.auth import TokenStore, hash_password, verify_password
from FeimRemote.cli import _validate_url


class FeimRemoteAuthTests(unittest.TestCase):
    def test_password_hash_verification(self):
        stored = hash_password("a sufficiently long passphrase")
        self.assertTrue(verify_password("a sufficiently long passphrase", stored))
        self.assertFalse(verify_password("wrong passphrase", stored))

    def test_short_password_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "12 characters"):
            hash_password("short")

    def test_login_issues_bearer_token_and_logout_revokes_it(self):
        users = {"owner": {"password": hash_password("a sufficiently long passphrase")}}
        tokens = TokenStore(users, ttl_seconds=60)
        token = tokens.login("owner", "a sufficiently long passphrase")
        self.assertIsNotNone(token)
        self.assertEqual(tokens.username_for(token), "owner")
        tokens.revoke(token)
        self.assertIsNone(tokens.username_for(token))

    def test_remote_cli_requires_https_outside_loopback(self):
        _validate_url("http://127.0.0.1:8000")
        _validate_url("https://remote.example")
        with self.assertRaisesRegex(ValueError, "Use HTTPS"):
            _validate_url("http://remote.example")


if __name__ == "__main__":
    unittest.main()
