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
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        script = """
import os

original_makedirs = os.makedirs
def reject_instance_directory(path, *args, **kwargs):
    normalized = os.fspath(path).replace("\\\\", "/").rstrip("/")
    if normalized.endswith("/instance"):
        raise OSError("read-only instance directory")
    return original_makedirs(path, *args, **kwargs)

os.makedirs = reject_instance_directory
import app
assert app.is_production
assert app.app.config["SQLALCHEMY_DATABASE_URI"] == %r
assert app.app.config["SESSION_COOKIE_SECURE"]
assert app.app.instance_path.replace("\\\\", "/").endswith("/tmp/instance")
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
