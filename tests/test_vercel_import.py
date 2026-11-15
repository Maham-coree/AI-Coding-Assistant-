import os
import subprocess
import sys
import unittest
from pathlib import Path


class VercelImportTests(unittest.TestCase):
    def test_import_does_not_write_instance_directory_and_requires_postgres(self):
        project_root = Path(__file__).resolve().parents[1]
        database_url = "postgresql+psycopg://test:test@localhost/test"
        environment = os.environ.copy()
        environment.update({
            "APP_ENV": "production",
            "VERCEL": "1",
            "SECRET_KEY": "test-production-secret-" + "x" * 40,
            "DATABASE_URL": database_url,
            "REDIS_URL": "redis://127.0.0.1:1/0",
            "SMTP_HOST": "smtp.example.test",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "test-user",
            "SMTP_PASSWORD": "test-only-password",
            "MAIL_DEFAULT_SENDER": "assistant@example.test",
            "PUBLIC_BASE_URL": "https://assistant.example.test",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        script = """
import os
import flask

original_makedirs = os.makedirs
attempted_paths = []
def reject_read_only_deployment_path(path, *args, **kwargs):
    normalized = os.fspath(path).replace("\\\\", "/").rstrip("/")
    attempted_paths.append(normalized)
    if normalized == "/var/task" or normalized.startswith("/var/task/"):
        raise OSError("read-only Vercel deployment directory")
    return original_makedirs(path, *args, **kwargs)

os.makedirs = reject_read_only_deployment_path
def reject_default_instance_path(self):
    raise AssertionError("Flask resolved its default /var/task instance path")
flask.Flask.auto_find_instance_path = reject_default_instance_path

import app
import api.index as vercel_entry
import json
assert app.is_production
assert app.is_vercel
assert app.app.config["SQLALCHEMY_DATABASE_URI"] == %r
assert app.app.config["SESSION_COOKIE_SECURE"]
assert app.app.instance_path.replace("\\\\", "/").endswith("/tmp/instance")
assert app.rate_limit_storage_uri == "redis://127.0.0.1:1/0"
assert app.app.config["RATELIMIT_IN_MEMORY_FALLBACK_ENABLED"]
assert app.password_reset_mail_settings()["public_base_url"] == "https://assistant.example.test"
assert not any(path == "/var/task" or path.startswith("/var/task/") for path in attempted_paths)
assert vercel_entry.app is app.app
assert os.path.isdir(os.path.join(os.path.dirname(app.__file__), "templates"))
assert os.path.isdir(os.path.join(os.path.dirname(app.__file__), "static"))
with open("vercel.json", encoding="utf-8") as config_file:
    config = json.load(config_file)
assert "api/index.py" in config["functions"]
assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
""" % database_url

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=project_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
