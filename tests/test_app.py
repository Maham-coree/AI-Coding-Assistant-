import hashlib
import os
import smtplib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine import URL


_TEST_DATABASE_DIRECTORY = tempfile.TemporaryDirectory(prefix="ai-coding-assistant-tests-")
_TEST_DATABASE_PATH = Path(_TEST_DATABASE_DIRECTORY.name) / "tests.sqlite3"
_TEST_DATABASE_URL = URL.create(
    "sqlite",
    database=str(_TEST_DATABASE_PATH),
).render_as_string(hide_password=False)

os.environ.update({
    "APP_ENV": "testing",
    "DATABASE_URL": _TEST_DATABASE_URL,
    "SECRET_KEY": "isolated-test-session-secret",
    "REDIS_URL": "",
    "GEMINI_API_KEY": "",
    "GOOGLE_API_KEY": "",
    "SMTP_HOST": "",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "MAIL_DEFAULT_SENDER": "",
    "PUBLIC_BASE_URL": "http://127.0.0.1:5000",
})
os.environ.pop("VERCEL", None)
os.environ.pop("RENDER", None)

import app as app_module


def assert_isolated_test_database():
    if app_module.app.config.get("SQLALCHEMY_DATABASE_URI") != _TEST_DATABASE_URL:
        raise RuntimeError("Refusing to run tests: configured database is not the isolated test database.")

    with app_module.app.app_context():
        database_url = app_module.db.engine.url
        if (
            database_url.get_backend_name() != "sqlite"
            or Path(database_url.database).resolve() != _TEST_DATABASE_PATH.resolve()
        ):
            raise RuntimeError("Refusing to run tests: SQLAlchemy is not bound to the isolated test database.")


assert_isolated_test_database()


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        text = "```python\nprint('generated')\n```" if "You are an expert software engineer" in kwargs["contents"] else "A safe **test response**."
        return type("Response", (), {"text": text})()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeModels()


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert_isolated_test_database()
        app_module.app.config.update(
            TESTING=True,
            SECRET_KEY="test-session-secret",
            WTF_CSRF_ENABLED=False,
            RATELIMIT_ENABLED=False,
        )
        app_module.limiter.enabled = False
        with app_module.app.app_context():
            app_module.db.drop_all()
            app_module.db.create_all()

    def setUp(self):
        assert_isolated_test_database()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            app_module.db.session.remove()
            app_module.db.drop_all()
            app_module.db.create_all()

    @classmethod
    def tearDownClass(cls):
        assert_isolated_test_database()
        with app_module.app.app_context():
            app_module.db.session.remove()
            app_module.db.engine.dispose()
        _TEST_DATABASE_DIRECTORY.cleanup()

    def test_database_safety_guard_rejects_non_test_database_before_access(self):
        with patch.dict(app_module.app.config, {"SQLALCHEMY_DATABASE_URI": "postgresql://"}):
            with self.assertRaisesRegex(RuntimeError, "isolated test database"):
                assert_isolated_test_database()

    def register(self, email="one@example.com", name="Test User", password="StrongPassword123"):
        return self.client.post("/register", data={
            "name": name,
            "email": email,
            "password": password,
            "confirm_password": password,
        })

    def test_registration_validation_hash_and_duplicate(self):
        response = self.client.post("/register", data={
            "name": "Test User",
            "email": "not-an-email",
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"valid email", response.data)

        self.register()
        with app_module.app.app_context():
            user = app_module.User.query.filter_by(email="one@example.com").one()
            self.assertNotEqual(user.password_hash, "StrongPassword123")
            self.assertTrue(app_module.check_password_hash(user.password_hash, "StrongPassword123"))
            self.assertEqual(len(user.prompt_templates), 7)

        duplicate_client = app_module.app.test_client()
        response = duplicate_client.post("/register", data={
            "name": "Another User",
            "email": "ONE@EXAMPLE.COM",
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        })
        self.assertIn(b"already exists", response.data)

    def test_login_logout_and_protected_workspace(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)
        self.assertEqual(self.client.get("/api/conversations").status_code, 401)

        health = self.client.get("/health").get_json()
        self.assertEqual(set(health), {"status", "provider_configured"})

        self.register()
        self.client.post("/logout")
        bad_login = self.client.post("/login", data={"email": "one@example.com", "password": "wrong"})
        self.assertIn(b"Invalid email or password", bad_login.data)
        good_login = self.client.post("/login", data={
            "email": "one@example.com",
            "password": "StrongPassword123",
        })
        self.assertEqual(good_login.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        for path in ("/prompts", "/snippets", "/analytics", "/settings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_workspace_fields_modes_generate_and_saved_snippets_are_preserved(self):
        self.register()
        workspace = self.client.get("/").get_data(as_text=True)
        for label in ("Build an API", "Explain code", "Fix bug", "Improve query"):
            with self.subTest(label=label):
                self.assertNotIn(label, workspace)
        self.assertNotIn('class="prompt-chips"', workspace)
        self.assertNotIn('class="example-button"', workspace)
        self.assertIn('id="userInput"', workspace)
        self.assertIn('id="codeInput"', workspace)
        self.assertIn('id="askBtn"', workspace)
        for mode in ("generate", "explain", "debug", "optimize", "convert"):
            with self.subTest(mode=mode):
                self.assertIn(f'data-mode="{mode}"', workspace)
        self.assertNotIn("Clear form", workspace)
        self.assertNotIn("Save code snippet", workspace)

        snippets = self.client.get("/snippets").get_data(as_text=True)
        self.assertIn('id="createSnippetForm"', snippets)
        self.assertIn("Add snippet", snippets)

    def test_password_reset_request_is_generic_and_token_is_hashed_and_single_use(self):
        self.register()
        self.client.post("/logout")
        sent_urls = []
        mail_settings = {
            "host": "smtp.example.test",
            "port": 587,
            "username": "test-user",
            "password": "test-password",
            "sender": "assistant@example.test",
            "public_base_url": "https://assistant.example.test",
        }
        with (
            patch.object(app_module, "password_reset_mail_settings", return_value=mail_settings),
            patch.object(
                app_module,
                "send_password_reset_email",
                side_effect=lambda _recipient, reset_url, _settings: sent_urls.append(reset_url),
            ),
        ):
            known_email = self.client.post(
                "/forgot-password",
                data={"email": "one@example.com"},
                follow_redirects=True,
            )
            unknown_email = self.client.post(
                "/forgot-password",
                data={"email": "missing@example.com"},
                follow_redirects=True,
            )

        generic_response = (
            b"If an account exists for that email address, we will process the reset request. "
            b"If no message arrives, try again later."
        )
        self.assertIn(generic_response, known_email.data)
        self.assertIn(generic_response, unknown_email.data)
        self.assertEqual(len(sent_urls), 1)
        self.assertTrue(sent_urls[0].startswith("https://assistant.example.test/reset-password?"))

        reset_url = urlsplit(sent_urls[0])
        token = parse_qs(reset_url.query)["token"][0]
        with app_module.app.app_context():
            record = app_module.PasswordResetToken.query.one()
            self.assertEqual(record.token_hash, hashlib.sha256(token.encode("utf-8")).hexdigest())
            self.assertNotEqual(record.token_hash, token)

        reset_page = self.client.get(f"{reset_url.path}?{reset_url.query}")
        self.assertEqual(reset_page.status_code, 200)
        self.assertIn(b'name="confirm_password"', reset_page.data)
        changed = self.client.post("/reset-password", data={
            "token": token,
            "password": "NewStrongPassword456",
            "confirm_password": "NewStrongPassword456",
        })
        self.assertEqual(changed.status_code, 302)
        with app_module.app.app_context():
            user = app_module.User.query.filter_by(email="one@example.com").one()
            record = app_module.PasswordResetToken.query.one()
            self.assertIsNotNone(record.used_at)
            self.assertTrue(app_module.check_password_hash(user.password_hash, "NewStrongPassword456"))

        reused = self.client.post("/reset-password", data={
            "token": token,
            "password": "AnotherStrongPassword789",
            "confirm_password": "AnotherStrongPassword789",
        })
        self.assertIn(b"invalid or expired", reused.data)
        self.assertEqual(self.client.post("/login", data={
            "email": "one@example.com",
            "password": "StrongPassword123",
        }).status_code, 200)
        self.assertEqual(self.client.post("/login", data={
            "email": "one@example.com",
            "password": "NewStrongPassword456",
        }).status_code, 302)

    def test_password_reset_request_without_mail_configuration_remains_generic(self):
        self.register()
        self.client.post("/logout")
        with patch.object(app_module, "password_reset_mail_settings", return_value=None):
            known_email = self.client.post(
                "/forgot-password",
                data={"email": "one@example.com"},
                follow_redirects=True,
            )
            unknown_email = self.client.post(
                "/forgot-password",
                data={"email": "missing@example.com"},
                follow_redirects=True,
            )

        generic_response = (
            b"If an account exists for that email address, we will process the reset request. "
            b"If no message arrives, try again later."
        )
        self.assertIn(generic_response, known_email.data)
        self.assertIn(generic_response, unknown_email.data)
        with app_module.app.app_context():
            self.assertEqual(app_module.PasswordResetToken.query.count(), 0)

    def test_password_reset_mail_settings_read_environment_and_require_https_in_production(self):
        settings_env = {
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "465",
            "SMTP_USERNAME": "test-user",
            "SMTP_PASSWORD": "test-only-password",
            "MAIL_DEFAULT_SENDER": "assistant@example.test",
            "PUBLIC_BASE_URL": "https://assistant.example.test",
        }
        with patch.dict(os.environ, settings_env), patch.object(app_module, "is_production", True):
            settings = app_module.password_reset_mail_settings()
            self.assertEqual(settings["host"], "smtp.example.test")
            self.assertEqual(settings["port"], 465)
            self.assertEqual(settings["public_base_url"], "https://assistant.example.test")

            with patch.dict(os.environ, {"PUBLIC_BASE_URL": "http://assistant.example.test"}):
                self.assertIsNone(app_module.password_reset_mail_settings())

    def test_password_reset_email_uses_implicit_tls_on_port_465(self):
        settings = {
            "host": "smtp.example.test",
            "port": 465,
            "username": "test-user",
            "password": "test-only-password",
            "sender": "assistant@example.test",
            "public_base_url": "https://assistant.example.test",
        }
        with patch.object(app_module.smtplib, "SMTP_SSL") as smtp_factory:
            smtp = smtp_factory.return_value.__enter__.return_value
            app_module.send_password_reset_email(
                "one@example.com",
                "https://assistant.example.test/reset-password?token=redacted-test-token",
                settings,
            )

        smtp_factory.assert_called_once()
        smtp.starttls.assert_not_called()
        smtp.login.assert_called_once_with("test-user", "test-only-password")

    def test_password_reset_email_failure_keeps_generic_response_and_consumes_token(self):
        self.register()
        self.client.post("/logout")
        settings = {
            "host": "smtp.example.test",
            "port": 587,
            "username": "test-user",
            "password": "test-only-password",
            "sender": "assistant@example.test",
            "public_base_url": "https://assistant.example.test",
        }
        with patch.object(app_module, "password_reset_mail_settings", return_value=settings), patch.object(
            app_module,
            "send_password_reset_email",
            side_effect=smtplib.SMTPAuthenticationError(535, b"private provider detail"),
        ), patch.object(app_module.app.logger, "error") as log_error:
            response = self.client.post(
                "/forgot-password",
                data={"email": "one@example.com"},
                follow_redirects=True,
            )

        generic_response = (
            b"If an account exists for that email address, we will process the reset request. "
            b"If no message arrives, try again later."
        )
        self.assertIn(generic_response, response.data)
        self.assertNotIn(b"email was sent", response.data.lower())
        log_error.assert_called_once_with(
            "Password reset email delivery failed (%s).",
            "SMTPAuthenticationError",
        )
        with app_module.app.app_context():
            record = app_module.PasswordResetToken.query.one()
            self.assertIsNotNone(record.used_at)

    def test_expired_password_reset_token_is_rejected(self):
        self.register()
        with app_module.app.app_context():
            user = app_module.User.query.filter_by(email="one@example.com").one()
            app_module.db.session.add(app_module.PasswordResetToken(
                user_id=user.id,
                token_hash=app_module.hash_password_reset_token("expired-token"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            ))
            app_module.db.session.commit()

        response = self.client.get("/reset-password?token=expired-token")
        self.assertIn(b"invalid or expired", response.data)
        self.assertNotIn(b'name="password"', response.data)

    def test_reset_email_uses_authenticated_tls_smtp(self):
        settings = {
            "host": "smtp.example.test",
            "port": 587,
            "username": "test-user",
            "password": "test-password",
            "sender": "assistant@example.test",
            "public_base_url": "https://assistant.example.test",
        }
        with patch.object(app_module.smtplib, "SMTP") as smtp_factory:
            smtp = smtp_factory.return_value.__enter__.return_value
            app_module.send_password_reset_email(
                "one@example.com",
                "https://assistant.example.test/reset-password?token=test-token",
                settings,
            )

        smtp_factory.assert_called_once_with("smtp.example.test", 587, timeout=10)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("test-user", "test-password")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "one@example.com")
        self.assertIn("test-token", message.get_content())

    def test_csrf_rejects_authentication_post_without_token(self):
        self.register()
        self.client.post("/logout")
        app_module.app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = self.client.post("/login", data={
                "email": "one@example.com",
                "password": "StrongPassword123",
            })
            self.assertEqual(response.status_code, 400)
        finally:
            app_module.app.config["WTF_CSRF_ENABLED"] = False

    def test_each_user_only_sees_owned_conversations_templates_snippets_and_analytics(self):
        self.register()
        conversation = self.client.post("/api/conversations", json={"title": "Private chat"}).get_json()["conversation"]
        renamed = self.client.patch(f"/api/conversations/{conversation['id']}", json={"title": "Renamed private chat"})
        self.assertEqual(renamed.get_json()["conversation"]["title"], "Renamed private chat")
        snippet = self.client.post("/api/snippets", json={
            "title": "Private snippet",
            "code": "print('private')",
            "language": "python",
        }).get_json()
        template = self.client.post("/prompts", data={
            "title": "Private template",
            "description": "Owned",
            "prompt": "Only for this account",
            "category": "Code Review",
            "mode": "optimize",
            "language": "python",
        })
        self.assertEqual(template.status_code, 302)
        with app_module.app.app_context():
            template_id = app_module.PromptTemplate.query.filter_by(title="Private template").one().id

        self.client.post("/logout")
        second_client = app_module.app.test_client()
        second_client.post("/register", data={
            "name": "Second User",
            "email": "two@example.com",
            "password": "OtherPassword123",
            "confirm_password": "OtherPassword123",
        })
        self.assertEqual(second_client.get("/").status_code, 200)
        self.assertEqual(second_client.get("/api/conversations").get_json()["conversations"], [])
        self.assertEqual(second_client.get("/api/snippets").get_json()["snippets"], [])
        self.assertEqual(second_client.get(f"/api/conversations/{conversation['id']}").status_code, 404)
        self.assertEqual(second_client.get(f"/api/prompt-templates/{template_id}").status_code, 404)
        self.assertEqual(second_client.get(f"/prompts/{template_id}/edit").status_code, 404)
        self.assertEqual(second_client.get(f"/snippets/{snippet['id']}/edit").status_code, 404)
        analytics_page = second_client.get("/analytics")
        self.assertEqual(analytics_page.status_code, 200)
        self.assertIn(b'<span class="metric-label">AI requests</span><strong>0</strong>', analytics_page.data)
        self.assertNotIn(b"Private chat", analytics_page.data)
        self.assertIsNotNone(snippet["id"])
        self.client.post("/login", data={"email": "one@example.com", "password": "StrongPassword123"})
        self.assertEqual(self.client.delete(f"/api/conversations/{conversation['id']}").status_code, 200)

    def test_all_ai_modes_persist_user_scoped_activity(self):
        self.register()
        conversation = self.client.post("/api/conversations", json={}).get_json()["conversation"]
        fake_client = FakeGeminiClient()
        with patch.object(app_module, "get_gemini_client", return_value=fake_client):
            for mode in ("generate", "explain", "debug", "optimize", "convert"):
                response = self.client.post("/chat", data={
                    "conversation_id": conversation["id"],
                    "mode": mode,
                    "language": "python",
                    "user_input": f"Please {mode} this code",
                    "code_input": "print('hello')",
                }, headers={"Accept": "application/json"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["status"], "ok")

        self.assertEqual(len(fake_client.models.calls), 5)
        with app_module.app.app_context():
            user_id = app_module.User.query.filter_by(email="one@example.com").one().id
            messages = app_module.Message.query.filter_by(owner_id=user_id, role="user").all()
            self.assertEqual({message.mode for message in messages}, {"generate", "explain", "debug", "optimize", "convert"})
            self.assertEqual(len(messages), 5)
        analytics_response = self.client.get("/analytics")
        self.assertEqual(analytics_response.status_code, 200)
        self.assertIn(b'<span class="metric-label">AI requests</span><strong>5</strong>', analytics_response.data)
        self.assertIn(b'<span class="metric-label">Code responses</span><strong>1</strong>', analytics_response.data)
        self.assertIn(b'<span class="metric-label">Debug requests</span><strong>1</strong>', analytics_response.data)

    def test_chat_reports_missing_or_unavailable_gemini_configuration(self):
        self.register()
        with patch.dict(app_module.os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
            missing_key = self.client.post("/chat", data={
                "mode": "generate",
                "user_input": "A test prompt",
            }, headers={"Accept": "application/json"})
        self.assertEqual(missing_key.status_code, 401)
        self.assertIn("key is missing or unavailable", missing_key.get_json()["error"])

        fake_client = FakeGeminiClient()
        with patch.object(
            fake_client.models,
            "generate_content",
            side_effect=RuntimeError("private provider error"),
        ), patch.object(app_module, "get_gemini_client", return_value=fake_client):
            unavailable = self.client.post("/chat", data={
                "mode": "generate",
                "user_input": "A second test prompt",
            }, headers={"Accept": "application/json"})
        self.assertEqual(unavailable.status_code, 502)
        self.assertEqual(unavailable.get_json()["error"], "Gemini is temporarily unavailable. Please try again shortly.")
        self.assertNotIn("private provider error", unavailable.get_data(as_text=True))

    def test_redis_rate_limit_settings_and_outage_fallback(self):
        self.assertEqual(app_module.rate_limit_storage_uri, "memory://")
        self.assertFalse(app_module.app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"])

        environment = os.environ.copy()
        environment.pop("VERCEL", None)
        environment.update({
            "APP_ENV": "development",
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        script = """
import app
app.app.config["WTF_CSRF_ENABLED"] = False
assert app.rate_limit_storage_uri == "redis://127.0.0.1:1/0"
assert app.app.config["RATELIMIT_STORAGE_URI"] == "redis://127.0.0.1:1/0"
assert app.app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"] is True
assert app.app.config["RATELIMIT_STORAGE_OPTIONS"] == {
    "socket_connect_timeout": 1,
    "socket_timeout": 1,
}

@app.app.post("/rate-limit-probe")
@app.limiter.limit("1 per minute")
def rate_limit_probe():
    return "ok"

client = app.app.test_client()
assert client.post("/rate-limit-probe").status_code == 200
assert client.post("/rate-limit-probe").status_code == 429
assert app.limiter._storage_dead
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_prompt_and_snippet_create_edit_search_and_delete(self):
        self.register()
        created = self.client.post("/prompts", data={
            "title": "My reusable prompt",
            "description": "First version",
            "prompt": "Explain a Python function",
            "category": "Code Explanation",
            "mode": "explain",
            "language": "python",
        })
        self.assertEqual(created.status_code, 302)
        with app_module.app.app_context():
            template_id = app_module.PromptTemplate.query.filter_by(title="My reusable prompt").one().id
        edited = self.client.post(f"/prompts/{template_id}/edit", data={
            "title": "My reusable prompt",
            "description": "Updated description",
            "prompt": "Explain a TypeScript function",
            "category": "Code Explanation",
            "mode": "explain",
            "language": "typescript",
        })
        self.assertEqual(edited.status_code, 302)
        search = self.client.get("/prompts?q=TypeScript")
        self.assertIn(b"My reusable prompt", search.data)
        self.assertEqual(self.client.get(f"/api/prompt-templates/{template_id}").get_json()["language"], "typescript")

        snippet = self.client.post("/api/snippets", json={
            "title": "Utility",
            "code": "def add(a, b): return a + b",
            "language": "python",
        }).get_json()
        self.assertEqual(self.client.get("/snippets").status_code, 200)
        self.assertEqual(self.client.post(f"/snippets/{snippet['id']}/edit", data={
            "title": "Updated utility",
            "code": "def add(a, b):\n    return a + b",
            "language": "python",
        }).status_code, 302)
        self.assertIn(b"Updated utility", self.client.get("/snippets").data)
        self.assertEqual(self.client.post(f"/snippets/{snippet['id']}/delete").status_code, 302)
        self.assertEqual(self.client.post(f"/prompts/{template_id}/delete").status_code, 302)
        self.assertEqual(self.client.get(f"/api/prompt-templates/{template_id}").status_code, 404)

    def test_markdown_is_sanitized_and_legacy_import_is_not_counted(self):
        rendered = app_module.render_markdown('<script>alert(1)</script>\n\n**safe**')
        self.assertNotIn("<script>", rendered)
        self.assertIn("<strong>safe</strong>", rendered)

        self.register()
        response = self.client.post("/api/conversations/import", json={"chats": [{
            "id": "old-chat",
            "title": "Old chat",
            "messages": [{"role": "user", "content": "old prompt", "mode": "debug"}],
        }]})
        self.assertEqual(response.get_json()["imported"], 1)
        with app_module.app.app_context():
            message = app_module.Message.query.filter_by(role="user").one()
            self.assertFalse(message.analytics_eligible)


if __name__ == "__main__":
    unittest.main()
