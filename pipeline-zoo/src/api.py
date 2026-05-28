"""REST API client — pipeline server + FPS monitoring."""

import re
import threading
import time
from datetime import datetime
from pathlib import Path

from src.config import LOGS_DIR
from src.docker import (
    compose_logs, compose_logs_stream, is_service_running, wait_for_healthy,
)
from src.models import PipelineZooError

try:
    import requests as _requests
except ImportError:
    _requests = None


def _check_requests():
    if _requests is None:
        raise PipelineZooError(
            "'requests' package required. Install: pip install requests")


def _base_url(port):
    return f"http://localhost:{port}"


# =========================================================================== #
#  Pipeline Server REST API                                                   #
# =========================================================================== #

def wait_for_ready(port, timeout=90):
    """Wait for the pipeline server to become ready."""
    return wait_for_healthy("pipeline-server", timeout=timeout)


def api_list_pipelines(port):
    """GET /pipelines"""
    _check_requests()
    resp = _requests.get(f"{_base_url(port)}/pipelines", timeout=10)
    resp.raise_for_status()
    return resp.json()


def api_start_pipeline(port, pipeline_name, request_body):
    """POST /pipelines/user_defined_pipelines/{name}"""
    _check_requests()
    url = f"{_base_url(port)}/pipelines/user_defined_pipelines/{pipeline_name}"
    resp = _requests.post(url, json=request_body, timeout=30)
    resp.raise_for_status()
    return resp.text.strip().strip('"')


def api_get_status(port, instance_id):
    """GET /pipelines/{instance_id}/status"""
    _check_requests()
    resp = _requests.get(
        f"{_base_url(port)}/pipelines/{instance_id}/status", timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return None


def api_get_all_status(port):
    """GET /pipelines/status"""
    _check_requests()
    resp = _requests.get(f"{_base_url(port)}/pipelines/status", timeout=10)
    resp.raise_for_status()
    return resp.json()


def api_stop_pipeline(port, instance_id):
    """DELETE /pipelines/{instance_id}"""
    _check_requests()
    resp = _requests.delete(
        f"{_base_url(port)}/pipelines/{instance_id}", timeout=10)
    return resp.status_code in (200, 204)


# =========================================================================== #
#  FPS extraction                                                             #
# =========================================================================== #

class LogCapture:
    """Background thread that tails container logs, saves to file, and extracts FPS.

    Streams all compose logs for a service to both a log file and stdout,
    while also parsing FPS from gvafpscounter lines.

    Usage:
        cap = LogCapture("pipeline-server", pipeline_name="light_gpu_npu")
        cap.start()
        ...
        cap.stop()
        print(cap.fps, cap.log_path)
    """

    def __init__(self, service, pipeline_name=None, print_logs=True):
        self._service = service
        self._print_logs = print_logs
        self._latest_fps = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._log_path = None
        self._log_file = None

        # Prepare log file
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_part = f"_{pipeline_name}" if pipeline_name else ""
        self._log_path = LOGS_DIR / f"{service}{name_part}_{ts}.log"

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def fps(self):
        with self._lock:
            return self._latest_fps

    def start(self):
        """Start tailing logs in a background thread."""
        self._log_file = open(self._log_path, "w")
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        print(f"  Logging {self._service} → {self._log_path}")

    def _read_loop(self):
        try:
            for line in compose_logs_stream(self._service):
                if self._stop_event.is_set():
                    break
                line_stripped = line.rstrip()
                if not line_stripped:
                    continue

                # Write to log file
                self._log_file.write(line_stripped + "\n")
                self._log_file.flush()

                # Print to stdout (filtered to important lines)
                if self._print_logs:
                    # Always show errors/warnings and FPS lines
                    lower = line_stripped.lower()
                    if any(k in lower for k in (
                        "error", "warning", "fpscounter",
                        "pipeline", "state", "critical",
                    )):
                        print(f"    [{self._service}] {line_stripped}")

                # Extract FPS
                if "FpsCounter" in line_stripped:
                    m = re.search(r"total=(\d+\.?\d*)", line_stripped)
                    if m:
                        with self._lock:
                            self._latest_fps = float(m.group(1))
        except Exception as exc:
            if self._log_file:
                self._log_file.write(f"\n[LogCapture error: {exc}]\n")
        finally:
            if self._log_file:
                self._log_file.close()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
