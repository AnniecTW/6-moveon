import subprocess
from unittest.mock import patch

from django.test import SimpleTestCase

from marketplace.charts import _render_spec_png


class ChartRendererErrorTests(SimpleTestCase):
    def test_child_stderr_is_logged_without_exposing_it_in_the_response(self):
        error = subprocess.CalledProcessError(
            1, ["python"], stderr=b"renderer dependency failed"
        )
        with patch("marketplace.charts.subprocess.run", side_effect=error):
            with self.assertLogs("marketplace.charts", level="ERROR") as logs:
                response = _render_spec_png({}, "http://localhost/")
        self.assertEqual(response.status_code, 502)
        self.assertIn("renderer dependency failed", "\n".join(logs.output))
        self.assertNotIn(b"renderer dependency failed", response.content)

    def test_timeout_is_logged_and_returns_a_controlled_error(self):
        error = subprocess.TimeoutExpired(["python"], 30, stderr=b"still rendering")
        with patch("marketplace.charts.subprocess.run", side_effect=error):
            with self.assertLogs("marketplace.charts", level="ERROR") as logs:
                response = _render_spec_png({}, "http://localhost/")
        self.assertEqual(response.status_code, 502)
        self.assertIn("still rendering", "\n".join(logs.output))

    def test_missing_interpreter_is_logged_and_returns_a_controlled_error(self):
        with patch("marketplace.charts.subprocess.run", side_effect=FileNotFoundError):
            with self.assertLogs("marketplace.charts", level="ERROR"):
                response = _render_spec_png({}, "http://localhost/")
        self.assertEqual(response.status_code, 502)
