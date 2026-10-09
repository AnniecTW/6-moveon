"""Real subprocess/HTTP checks, including killing an actual stalled renderer."""

import ctypes
import json
import os
import socket
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

from django.test import SimpleTestCase
from PIL import Image

from marketplace.charts import PNG_RENDERER_PATH, _render_spec_png


class PngSubprocessTests(SimpleTestCase):
    spec: ClassVar[dict] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"url": "https://example.invalid/private-api"},
        "mark": "bar",
        "encoding": {
            "x": {"field": "label", "type": "nominal"},
            "y": {"field": "amount", "type": "quantitative"},
        },
    }
    payload = b'[{"label":"Owner Only","amount":18}]'

    def setUp(self):
        directory = TemporaryDirectory(prefix="a5-png-tests-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.audit = self.directory / "audit.jsonl"

    def wrapper(self, *, hang=False):
        """Observe the real helper; no product diagnostics/test hooks needed."""
        wrapper = self.directory / "observe_helper.py"
        wrapper.write_text(
            f"""
import importlib.util, json, os
from urllib.error import HTTPError
from urllib.request import urlopen
spec = importlib.util.spec_from_file_location("observed_png", {str(PNG_RENDERER_PATH)!r})
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
def record(kind, **values):
    with open({str(self.audit)!r}, "a", encoding="utf-8") as output:
        output.write(json.dumps({{"kind":kind,"pid":os.getpid(),**values}})+"\\n")
original_server = helper.HTTPServer
class ObservedServer(original_server):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        record("relay", host=self.server_address[0], port=self.server_port)
    def server_close(self):
        super().server_close()
        record("closed")
helper.HTTPServer = ObservedServer
original_thread = helper.Thread
class ObservedThread(original_thread):
    def start(self):
        super().start()
        record("thread", ident=self.ident)
    def join(self, *args, **kwargs):
        super().join(*args, **kwargs)
        record("joined", alive=self.is_alive())
helper.Thread = ObservedThread
original_popen = helper.subprocess.Popen
def observed_popen(*args, **kwargs):
    process = original_popen(*args, **kwargs)
    record("renderer", child_pid=process.pid)
    return process
helper.subprocess.Popen = observed_popen
original_run = helper.run_process
def inspect(command, payload, **kwargs):
    envelope = json.loads(payload)
    chart = envelope["spec"]
    url = chart["data"]["url"]
    with urlopen(url, timeout=2) as response:
        body = json.load(response)
    try:
        urlopen(url+"?user_id=999", timeout=2)
    except HTTPError as error:
        wrong_path_status = error.code
    record("data", url=url, body=body, chart_data=chart["data"],
           allowed_base_url=envelope["allowed_base_url"], wrong_path=wrong_path_status)
    if {hang!r}:
        command = [command[0], "-c", "import time; time.sleep(60)"]
        kwargs["timeout"] = 60
    return original_run(command, payload, **kwargs)
helper.run_process = inspect
raise SystemExit(helper.main())
""",
            encoding="utf-8",
        )
        return wrapper

    def records(self):
        return [
            json.loads(line)
            for line in self.audit.read_text(encoding="utf-8").splitlines()
        ]

    def assert_process_stopped(self, pid):
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                try:
                    self.assertEqual(
                        kernel.WaitForSingleObject(handle, 0),
                        0,
                        f"PID {pid} still running",
                    )
                finally:
                    kernel.CloseHandle(handle)
            else:
                self.assertEqual(
                    ctypes.get_last_error(), 87, f"Cannot inspect PID {pid}"
                )
        else:
            stat = Path(f"/proc/{pid}/stat")
            if stat.exists():
                self.assertEqual(stat.read_text().split(")", 1)[1].split()[0], "Z")
            else:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def assert_resources_closed(self, records):
        for relay in (row for row in records if row["kind"] == "relay"):
            self.assertEqual(relay["host"], "127.0.0.1")
            self.assertNotEqual(relay["pid"], os.getpid())
            with self.assertRaises(OSError):
                socket.create_connection((relay["host"], relay["port"]), timeout=1)
            self.assert_process_stopped(relay["pid"])
        for renderer in (row for row in records if row["kind"] == "renderer"):
            self.assert_process_stopped(renderer["child_pid"])

    def test_real_url_transfer_and_three_sequential_renders_release_resources(self):
        with patch("marketplace.charts.PNG_RENDERER_PATH", self.wrapper()):
            for _ in range(3):
                response = _render_spec_png(
                    deepcopy(self.spec), self.payload, "/authorized.json"
                )
                self.assertEqual(response.status_code, 200, response.content)
                with Image.open(BytesIO(response.content)) as image:
                    self.assertEqual(image.format, "PNG")
                    image.verify()
        records = self.records()
        transfers = [row for row in records if row["kind"] == "data"]
        self.assertEqual(len(transfers), 3)
        for row in transfers:
            self.assertEqual(row["body"], json.loads(self.payload))
            self.assertEqual(row["chart_data"], {"url": row["url"]})
            self.assertEqual(row["wrong_path"], 404)
            self.assertEqual(row["url"], row["allowed_base_url"] + "authorized.json")
        self.assertEqual(sum(row["kind"] == "closed" for row in records), 3)
        self.assertEqual(
            [row["alive"] for row in records if row["kind"] == "joined"], [False] * 3
        )
        self.assert_resources_closed(records)

    def test_real_render_failure_closes_threads_ports_and_descendants_without_private_logs(
        self,
    ):
        spec = deepcopy(self.spec)
        spec["mark"] = "PRIVATE-INVALID-MARK"
        with (
            patch("marketplace.charts.PNG_RENDERER_PATH", self.wrapper()),
            self.assertLogs("marketplace.charts", level="ERROR") as logs,
        ):
            response = _render_spec_png(spec, self.payload, "/authorized.json")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.content, b'{"error": "Chart rendering failed."}')
        self.assertNotIn("PRIVATE", "\n".join(logs.output))
        self.assertNotIn("Owner Only", "\n".join(logs.output))
        records = self.records()
        self.assertIn("closed", [row["kind"] for row in records])
        self.assertEqual(
            [row["alive"] for row in records if row["kind"] == "joined"], [False]
        )
        self.assert_resources_closed(records)

    def test_actual_30_second_worker_timeout_kills_a_live_relay_and_stalled_descendant(
        self,
    ):
        # The real helper/HTTP thread stays live while its actual child sleeps.
        # Extend only the child's wait so Django's unchanged 30s timeout fires.
        with (
            patch("marketplace.charts.PNG_RENDERER_PATH", self.wrapper(hang=True)),
            self.assertLogs("marketplace.charts", level="ERROR") as logs,
        ):
            response = _render_spec_png(
                deepcopy(self.spec), self.payload, "/authorized.json"
            )
        self.assertEqual(response.status_code, 502)
        self.assertIn("TimeoutExpired", "\n".join(logs.output))
        records = self.records()
        self.assertEqual(sum(row["kind"] == "renderer" for row in records), 1)
        self.assert_resources_closed(records)

    def test_missing_helper_and_interpreter_fail_without_starting_a_relay(self):
        for target, replacement in (
            ("marketplace.charts.PNG_RENDERER_PATH", self.directory / "missing.py"),
            ("marketplace.charts.sys.prefix", str(self.directory / "missing-venv")),
        ):
            with (
                self.subTest(target=target),
                patch(target, replacement),
                self.assertLogs("marketplace.charts", level="ERROR"),
            ):
                response = _render_spec_png(
                    deepcopy(self.spec), self.payload, "/authorized.json"
                )
            self.assertEqual(response.status_code, 502)
        self.assertFalse(self.audit.exists())
