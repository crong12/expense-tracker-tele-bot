import os
import subprocess
import sys
from pathlib import Path


def test_integration_conftest_import_does_not_load_database_or_config():
    conftest = Path(__file__).parent / "integration" / "conftest.py"
    script = f"""
import importlib.util
import sys
import types

blocked_config = types.ModuleType('config')
def blocked_getattr(name):
    raise AssertionError(f'config accessed during collection: {{name}}')
blocked_config.__getattr__ = blocked_getattr
sys.modules['config'] = blocked_config

spec = importlib.util.spec_from_file_location('collection_safe_integration_conftest', {str(conftest)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert 'database' not in sys.modules
"""
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    environment.pop("TEST_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
