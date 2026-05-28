"""Paths, ports, and infrastructure constants."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ZOO_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ZOO_DIR.parent

# Model/video root inside the Pipeline Server container
PIPE_ROOT = "/home/pipeline-server/pipelines"

# Default Pipeline Server image
DEFAULT_IMAGE = "intel/dlstreamer-pipeline-server:2026.1.0-20260505-weekly-ubuntu24"

# Default DL Streamer image (asset downloads: model conversion + video transcode)
DLSTREAMER_IMAGE = "intel/dlstreamer:2026.1.0-20260505-weekly-ubuntu24"

# REST API
REST_PORT = 8080
RTSP_PORT = 8554

# Docker Compose
COMPOSE_FILE = ZOO_DIR / "compose.yaml"
ENV_FILE = ZOO_DIR / ".env"

# Assets directory — shared bind mount between download services and pipeline-server
ASSETS_DIR = ZOO_DIR / "assets"

# Logs directory — container log captures
LOGS_DIR = ZOO_DIR / "logs"
