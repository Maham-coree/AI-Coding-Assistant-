import unittest
from unittest.mock import patch

import app as app_module


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
        app_module.app.config.update(
            TESTING=True,
            SECRET_KEY="test-session-secret",
            SQLALCHEMY_DATABASE_URI="sqlite://",
            WTF_CSRF_ENABLED=False,
            RATELIMIT_ENABLED=False,
        )
        app_module.limiter.enabled = False
        with app_module.app.app_context():
            app_module.db.drop_all()
            app_module.db.create_all()

    def setUp(self):
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            app_module.db.session.remove()
            app_module.db.drop_all()
            app_module.db.create_all()

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
