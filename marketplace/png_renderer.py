"""Request-scoped PNG subprocesses. No Django, sessions, or database access."""

import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit


def _stop_process(process, *, process_tree):
    try:
        if process_tree and os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        elif process_tree and process.poll() is None:
            # Windows lacks POSIX groups. Kill the request's descendants too.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
    finally:
        if process.poll() is None:
            process.kill()


def run_process(command, payload, *, timeout, process_tree=False):
    """Synchronously collect bytes; kill and reap processes on timeout/error."""
    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=process_tree and os.name != "nt",
    ) as process:
        try:
            stdout, stderr = process.communicate(input=payload, timeout=timeout)
        except BaseException:
            try:
                _stop_process(process, process_tree=process_tree)
            finally:
                process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(
                process.returncode, command, stderr=stderr
            )
    return stdout


def render_snapshot(spec, payload, data_path):
    """Relay this authorized snapshot while a separate interpreter renders it.

    vl-convert 1.9.0 blocks Python HTTP threads during conversion in the same
    process. Its short-lived descendant leaves this relay child responsive.
    """
    parsed = urlsplit(data_path)
    if (
        not data_path.startswith("/")
        or parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Invalid local data path")

    class SnapshotHandler(BaseHTTPRequestHandler):
        timeout = 2

        def do_GET(self):
            if self.path != data_path:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    with HTTPServer(("127.0.0.1", 0), SnapshotHandler) as relay:
        thread = Thread(
            target=relay.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        thread.start()
        base_url = f"http://127.0.0.1:{relay.server_port}/"
        # Replace any supplied URL/inline values with this request's local path.
        spec["data"] = {"url": base_url.rstrip("/") + data_path}
        spec["width"] = 560
        envelope = json.dumps({"spec": spec, "allowed_base_url": base_url}).encode(
            "utf-8"
        )
        try:
            return run_process(
                [sys.executable, str(Path(__file__).resolve()), "--render"],
                envelope,
                timeout=28,
            )
        finally:
            relay.shutdown()
            thread.join()


def main():
    try:
        envelope = json.load(sys.stdin)
        if sys.argv[1:] == ["--render"]:
            import vl_convert as vlc

            png = vlc.vegalite_to_png(
                vl_spec=envelope["spec"],
                allowed_base_urls=[envelope["allowed_base_url"]],
            )
        elif not sys.argv[1:]:
            png = render_snapshot(
                envelope["spec"],
                envelope["payload"].encode("utf-8"),
                envelope["data_path"],
            )
        else:
            raise ValueError("Invalid renderer invocation")
        sys.stdout.buffer.write(png)
        return 0
    except Exception:  # noqa: BLE001 -- redact all exceptions at the CLI boundary
        # Renderer exceptions can contain chart titles/data. Never echo them.
        sys.stderr.write("PNG subprocess failed.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
