import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from marketplace.charts import _render_spec_png


class ChartRendererErrorTests(SimpleTestCase):
    def test_private_child_stderr_is_not_exposed_in_logs_or_response(self):
        error = subprocess.CalledProcessError(
            1, ["python"], stderr=b"renderer dependency failed"
        )
        with patch("marketplace.charts.run_process", side_effect=error), \
                self.assertLogs("marketplace.charts", level="ERROR") as logs:
            response = _render_spec_png({}, b"[]", "/data.json")
        self.assertEqual(response.status_code, 502)
        self.assertIn("CalledProcessError", "\n".join(logs.output))
        self.assertNotIn("renderer dependency failed", "\n".join(logs.output))
        self.assertNotIn(b"renderer dependency failed", response.content)

    def test_timeout_is_logged_and_returns_a_controlled_error(self):
        error = subprocess.TimeoutExpired(["python"], 30, stderr=b"still rendering")
        with patch("marketplace.charts.run_process", side_effect=error), \
                self.assertLogs("marketplace.charts", level="ERROR") as logs:
            response = _render_spec_png({}, b"[]", "/data.json")
        self.assertEqual(response.status_code, 502)
        self.assertIn("TimeoutExpired", "\n".join(logs.output))
        self.assertNotIn("still rendering", "\n".join(logs.output))

    def test_missing_interpreter_is_logged_and_returns_a_controlled_error(self):
        with patch("marketplace.charts.run_process", side_effect=FileNotFoundError), \
                self.assertLogs("marketplace.charts", level="ERROR"):
            response = _render_spec_png({}, b"[]", "/data.json")
        self.assertEqual(response.status_code, 502)
