# Pipeline Zoo

Run pre-optimized DL Streamer video-analytics pipelines on Intel Edge AI platforms (GPU, NPU) via [DL Streamer Pipeline Server](https://github.com/open-edge-platform/edge-ai-libraries/tree/main/microservices/dlstreamer-pipeline-server).

## Overview

Pipeline Zoo is a single CLI tool (`pipeline-zoo.py`) that:

1. **Discovers** pipeline definitions organized as `{use_case}/{mode}/` directories with per-platform parameter variants (e.g. `video-analytics-pipeline/light`, `license-plate-recognition/default`).
2. **Auto-downloads** required models and videos on first run via Docker-based conversion scripts or direct HTTP download.
3. **Renders** GStreamer pipeline strings by substituting model paths, video paths, and device parameters into templates.
4. **Launches** a DL Streamer Pipeline Server container via Docker Compose with the generated config.
5. **Runs** one or more pipeline instances via REST API and monitors FPS in real time.

No manual model download, config authoring, or Docker command construction required.

### Architecture

```
pipeline-zoo.py  (CLI entry point)
  │
  └── src/       (core library)
        ├── runner.py      ── orchestrates the full lifecycle
        ├── rendering.py   ── discovers pipelines, renders templates
        ├── assets.py      ── model routing table, downloads, path resolution
        ├── docker.py      ── Docker Compose operations
        ├── api.py         ── Pipeline Server REST client
        ├── hardware.py    ── GPU/NPU detection
        ├── config.py      ── paths and constants
        └── models.py      ── dataclasses (PipelineConfig, PipelineResult, etc.)

Docker Compose (compose.yaml):
  ├── assets-download  ── DL Streamer container for model conversion + video transcoding
  │     writes to → ./assets/models/ and ./assets/video/
  │
  └── pipeline-server  ── DL Streamer Pipeline Server (REST API + RTSP)
        reads from → ./assets/ (mounted read-only at /home/pipeline-server/pipelines/)
```

One-way data flow: `assets-download` writes prepared assets to `./assets/`, `pipeline-server` reads from it.

## Quick Start

### Prerequisites

- Docker with Docker Compose v2 and GPU access (`/dev/dri`)
- Python 3.8+ with `pip`
- Intel GPU (required) and optionally Intel NPU (`/dev/accel`)

### Install dependencies

```bash
cd pipeline-zoo
pip install -r requirements.txt
```

### Usage

```bash
# List all available pipelines (pick one interactively, or press Enter / 0 to exit)
python3 pipeline-zoo.py --list

# Run a specific pipeline (auto-detects platform and device)
python3 pipeline-zoo.py video-analytics-pipeline/light

# Run with an explicit params file
python3 pipeline-zoo.py video-analytics-pipeline/light --params-file ARL/params_gpu.j2

# Dry run — show config, Docker Compose command, and REST request without executing
python3 pipeline-zoo.py video-analytics-pipeline/light --dry-run

# Run with options
python3 pipeline-zoo.py video-analytics-pipeline/medium --params-file ARL/params_gpu_npu.j2 \
    --num-instances 2 --duration 60

# Run the license-plate-recognition pipeline on GPU
python3 pipeline-zoo.py license-plate-recognition/default --params-file ARL/params_gpu.j2

# Save the generated Pipeline Server config to a file
python3 pipeline-zoo.py video-analytics-pipeline/heavy --dry-run --save-config

# Override the detection model (swap yolov11m → yolov11n on heavy pipeline)
python3 pipeline-zoo.py video-analytics-pipeline/heavy \
    --detection-model Ultralytics/yolov11n

# Override multiple assets at once
python3 pipeline-zoo.py video-analytics-pipeline/heavy --dry-run \
    --detection-model Ultralytics/yolov11n \
    --classification-model-0 pytorch/mobilenet-v2

# Remove all runtime artifacts (logs, assets, .env, Docker volumes and images)
python3 pipeline-zoo.py --cleanup
```

### Example: `--list`

```
  Detected hardware: GPU, NPU

     #  PIPELINE                       MODE       PLATFORMS
  ----  ------------------------------ ---------- --------------------
     1  license-plate-recognition      default    ARL[gpu,gpu_npu]
     2  video-analytics-pipeline       heavy      ARL[gpu,gpu_npu]
     3  video-analytics-pipeline       light      ARL[gpu,gpu_npu]
     4  video-analytics-pipeline       medium     ARL[gpu,gpu_npu]

  Select pipeline [1-4] (0 or Enter to exit):
```

## CLI Reference

```
usage: pipeline-zoo [-h] [--list] [--cleanup] [--dry-run] [--params-file PATH]
                    [--num-instances N] [--duration S] [--port PORT]
                    [--image IMAGE] [--save-config [PATH]]
                    [--detection-model ID] [--classification-model-0 ID]
                    [--classification-model-1 ID] [--input-video URL]
                    [pipeline]
```

| Flag / Argument | Description |
|-----------------|-------------|
| `pipeline` | Pipeline path in `use_case/mode` format (e.g. `video-analytics-pipeline/light`) |
| `--list` | List available pipelines and pick one to run (0 or Enter to exit) |
| `--cleanup` | Remove all runtime artifacts (logs, assets, .env, Docker volumes and images) |
| `--dry-run` | Show generated config, compose info, and REST request without executing |
| `--params-file PATH` | Path to a params `.j2` file relative to the pipeline dir (e.g. `ARL/params_gpu_npu.j2`). Auto-detected if omitted. |
| `--num-instances N` | Number of concurrent pipeline instances (default: 2) |
| `--duration S` | Monitoring duration in seconds (default: 120) |
| `--port PORT` | Pipeline Server REST API port (default: 8080) |
| `--image IMAGE` | Pipeline Server Docker image (default: `intel/dlstreamer-pipeline-server:2026.1.0-20260505-weekly-ubuntu24`) |
| `--save-config [PATH]` | Save the generated `config.json` to a file (default: `config_{name}.json`) |
| `--detection-model ID` | Override detection model asset (e.g. `Ultralytics/yolov11n`) |
| `--classification-model-0 ID` | Override first classification model asset |
| `--classification-model-1 ID` | Override second classification model asset |
| `--input-video URL` | Override input video (Pexels URL or local filename) |

## Directory Layout

```
pipeline-zoo/
├── pipeline-zoo.py                          # CLI entry point (argparse, commands)
├── compose.yaml                             # Docker Compose (assets-download + pipeline-server)
├── requirements.txt                         # Python dependencies (jinja2, requests, python-on-whales)
├── README.md
│
├── src/                                     # Core library — all logic lives here
│   ├── __init__.py                          # Package marker + __version__
│   ├── config.py                            # Paths and constants (PIPE_ROOT, images, ports)
│   ├── models.py                            # Dataclasses: PipelineConfig, PipelineResult, PipelineZooError
│   ├── hardware.py                          # GPU/NPU detection, platform/device auto-selection
│   ├── assets.py                            # Model routing table (_MODELS), download, path resolution
│   ├── rendering.py                         # Pipeline discovery, Jinja2 rendering, config generation
│   ├── docker.py                            # Docker Compose lifecycle (.env, up, down, exec, logs)
│   ├── api.py                               # Pipeline Server REST client + LogCapture
│   └── runner.py                            # Top-level facade: list, resolve, dry-run, run, cleanup
│
├── docker/                                  # Support scripts for the assets-download container
│   ├── entrypoint.sh                        # Container entrypoint
│   ├── video_download.py                    # Video download + H.265 transcode via VA-API
│   └── .dockerignore
│
├── video-analytics-pipeline/                # Pipeline: object detection + classification
│   ├── light/                               # Mode: single classifier, fastest throughput
│   │   ├── pipeline.json                    #   detect → track → 1× classify
│   │   └── ARL/                             #   Arrow Lake platform
│   │       ├── params_gpu.j2               #     All inference on GPU
│   │       └── params_gpu_npu.j2           #     Detection on GPU, classification on NPU
│   ├── medium/                              # Mode: dual classifiers, balanced
│   │   ├── pipeline.json                    #   detect → track → 2× classify
│   │   └── ARL/
│   │       ├── params_gpu.j2
│   │       └── params_gpu_npu.j2
│   └── heavy/                               # Mode: larger detection model, highest accuracy
│       ├── pipeline.json                    #   detect → track → 2× classify
│       └── ARL/
│           ├── params_gpu.j2
│           └── params_gpu_npu.j2
│
├── license-plate-recognition/               # Pipeline: license plate detection + OCR
│   └── default/                             # Mode: detect → track → OCR classify
│       ├── pipeline.json                    #   MP4 input via decodebin3
│       └── ARL/
│           ├── params_gpu.j2               #   Both models on GPU
│           └── params_gpu_npu.j2           #   Detection on GPU, OCR on NPU
│
├── assets/                                  # Shared volume — models + videos (auto-created)
│   ├── models/                              #   OpenVINO IR files (.xml + .bin)
│   │   ├── yolo11n/                         #   Ultralytics/yolov11n
│   │   ├── yolo11m/                         #   Ultralytics/yolov11m
│   │   ├── yolo-v5m/                        #   dlstreamer/yolov5m
│   │   ├── resnet-50/                       #   google/resnet-v1-50-tf
│   │   ├── mobilenet-v2/                    #   pytorch/mobilenet-v2
│   │   ├── yolov8-lpr/                      #   public/yolov8_license_plate_detector
│   │   └── ppocr-v4/                        #   public/ch_PP-OCRv4_rec_infer
│   └── video/                               #   Input videos
│       ├── 18856748.h265                    #   Bears (H.265 transcoded)
│       └── license-plate-detection.mp4      #   License plates (MP4)
│
├── logs/                                    # Container log captures (auto-created)
└── .env                                     # Auto-generated compose environment (gitignored)
```

## Source Modules

### `pipeline-zoo.py` — CLI Entry Point

Thin argument parser and command dispatcher. Defines three commands:
- **`cmd_list`** — interactive pipeline selector (`--list`)
- **`cmd_run`** — launch pipeline with Docker Compose + REST API
- **`cmd_cleanup`** — remove runtime artifacts

All logic is delegated to `src/` modules.

### `src/config.py` — Paths and Constants

Centralizes all path and image constants:

| Constant | Value | Purpose |
|----------|-------|---------|
| `PIPE_ROOT` | `/home/pipeline-server/pipelines` | In-container mount point for assets |
| `ASSETS_DIR` | `./assets` | Host-side shared volume |
| `COMPOSE_FILE` | `./compose.yaml` | Docker Compose file |
| `DEFAULT_IMAGE` | `intel/dlstreamer-pipeline-server:2026.1.0-…` | Pipeline Server image |
| `DLSTREAMER_IMAGE` | `intel/dlstreamer:2026.1.0-…` | Assets-download image |
| `REST_PORT` | `8080` | Pipeline Server REST API |
| `RTSP_PORT` | `8554` | Pipeline Server RTSP output |

### `src/models.py` — Data Classes

| Class | Purpose |
|-------|---------|
| `PipelineZooError` | Recoverable error with user-friendly message |
| `PlatformConfig` | Platform name, available devices, path to params dir |
| `PipelineConfig` | Use case, mode, pipeline directory, dict of `PlatformConfig` |
| `PipelineResult` | Execution results: pipeline ID, device, FPS, log path, instance IDs |

### `src/hardware.py` — Hardware Detection

| Function | Description |
|----------|-------------|
| `detect_hardware()` | Returns `(has_gpu, has_npu)` by probing `/dev/dri` and `/dev/accel` |
| `detect_platform(pipeline)` | Selects best `PlatformConfig` for detected hardware |
| `detect_device(platform)` | Picks `gpu_npu` if NPU available, else `gpu` |
| `resolve_cores(taskset)` | Resolves CPU core pinning via helper script |

### `src/assets.py` — Model Routing Table and Downloads

The core of asset management. Contains:

**`_MODELS` dict** — a thin routing table where each entry describes how to obtain a model:

```python
_MODELS = {
    "Ultralytics/yolov11n": {
        "downloader":  [venv, "yolo_downloader.py", ...],  # conversion script
        "cache_dir":   "models/yolo11n",                   # relative to assets/
        "xml":         "yolo11n_int8.xml",                  # model filename
    },
    "dlstreamer/yolov5m": {
        "urls": [...],                                      # direct HTTP download
        "cache_dir":   "models/yolo-v5m",
        "xml":         "yolov5m-640_INT8.xml",
        "model_proc":  "yolo-v5.json",
    },
    "public/yolov8_license_plate_detector": {
        "cache_dir":   "models/yolov8-lpr",                # pre-cached, no downloader
        "xml":         "yolov8_license_plate_detector.xml",
    },
    ...
}
```

Everything else is derived by helpers — no duplication of paths across modes.

**Key functions:**

| Function | Description |
|----------|-------------|
| `get_model_path_vars(asset_id)` | Returns `{model-path, model-dir}` relative to `PIPE_ROOT` |
| `get_model_labels(asset_id)` | Returns labels file path or `None` |
| `resolve_video(url_or_path)` | Pexels URL → H.265 paths; local filename → direct path |
| `ensure_assets(pipeline_dir, mode, ...)` | Checks cache, downloads missing models/videos |
| `apply_asset_overrides(args, data)` | Applies `--detection-model` etc. CLI overrides |

**`ASSET_KEY_PREFIX`** — maps `pipeline.json` asset keys to variable-name prefixes used in templates:

```python
ASSET_KEY_PREFIX = {
    "detection_model":        "det",        # → ${det-model-path}
    "classification_model":   "class",      # → ${class-model-path}
    "classification_model_0": "class1",     # → ${class1-model-path}
    "classification_model_1": "class2",     # → ${class2-model-path}
    "input_video":            "video",      # → ${video-path}
}
```

### `src/rendering.py` — Pipeline Discovery and Template Rendering

| Function | Description |
|----------|-------------|
| `discover_pipelines()` | Scans `{use_case}/{mode}/pipeline.json` directories, returns sorted `PipelineConfig` list |
| `render_pipeline(pipeline_dir, params_file)` | Loads `pipeline.json`, substitutes device params + path vars, returns GStreamer pipeline string |
| `generate_config_json(...)` | Renders pipeline, adapts for Pipeline Server (replaces `fakesink` with `gvametaconvert ! gvametapublish ! appsink`) |
| `build_path_vars(assets, mode)` | Assembles `{prefix}-{suffix}` path variables from the `_MODELS` routing table |
| `parse_j2_params(j2_text)` | Extracts `{% set var = "value" %}` assignments from Jinja2 templates |

**Variable substitution** works in two passes:
1. **Device parameters** from `params_*.j2` — e.g. `${classify_0_device}` → `GPU`
2. **Path variables** from `build_path_vars()` — e.g. `${det-model-path}` → `models/yolo11n/yolo11n_int8.xml`

All path variables are prefixed with `PIPE_ROOT` at render time (e.g. `/home/pipeline-server/pipelines/models/yolo11n/yolo11n_int8.xml`).

### `src/docker.py` — Docker Compose Lifecycle

| Function | Description |
|----------|-------------|
| `generate_env_file(...)` | Writes `.env` with config path, image, ports, GPU render group, core pinning |
| `compose_up(profile)` | Starts a compose profile (`download` or `pipeline`) |
| `compose_down()` | Stops and removes all services |
| `compose_stop(service)` | Stops a specific service |
| `compose_logs(service)` | Gets container logs (tail) |
| `compose_logs_stream(service)` | Streams logs line by line |
| `is_service_running(service)` | Checks if a service container is running |
| `wait_for_healthy(service)` | Waits for healthcheck to pass (up to 90s) |
| `docker_exec(container, cmd)` | Runs a command inside a running container |
| `exec_video_download(args)` | Runs `video_download.py` in the assets-download container |
| `ensure_image(image)` | Pulls Docker image if not present locally |
| `validate_compose()` | Validates compose.yaml + .env |
| `remove_zoo_containers()` | Removes stopped pipeline-zoo containers |
| `remove_volume(name)` | Removes a Docker volume by name |
| `remove_image(image)` | Removes a Docker image by name |

Uses `python-on-whales` for all Docker operations (no subprocess/shell).

### `src/api.py` — Pipeline Server REST Client

| Function | Description |
|----------|-------------|
| `wait_for_ready(port)` | Polls `GET /pipelines` until the server is ready (up to 90s) |
| `api_list_pipelines(port)` | `GET /pipelines` — lists loaded pipeline definitions |
| `api_start_pipeline(port, name, body)` | `POST /pipelines/user_defined_pipelines/{name}` — starts an instance |
| `api_get_status(port, instance_id)` | `GET /pipelines/{id}/status` — gets instance status |
| `api_get_all_status(port)` | `GET /pipelines/status` — gets all instance statuses |
| `api_stop_pipeline(port, instance_id)` | `DELETE /pipelines/{id}` — stops an instance |

**`LogCapture`** class — background thread that tails container logs, saves to file, and extracts FPS from `gvafpscounter` output lines.

### `src/runner.py` — Top-Level Facade

The public API used by `pipeline-zoo.py`:

| Function | Description |
|----------|-------------|
| `list_pipelines()` | Returns all discovered `PipelineConfig` objects |
| `resolve_pipeline(pipeline_arg)` | Resolves `"use_case/mode"` string to metadata (platform, device, params file) |
| `render_dry_run(pipeline_arg, ...)` | Renders config + REST request body without executing |
| `run_pipeline(pipeline_arg, ...)` | Full end-to-end: ensure assets → generate config → start server → run instances → monitor → return `PipelineResult` |
| `cleanup()` | Removes `logs/`, `assets/`, `.env`, Docker volumes, images, and stopped containers |

## Included Pipelines

### `video-analytics-pipeline` — Object Detection + Classification

Three modes of increasing complexity, all using H.265 video input:

| Mode | Detection Model | Classifiers | Video | Description |
|------|----------------|-------------|-------|-------------|
| **light** | YOLOv11n (INT8) | ResNet-50 (INT8) | bears.h265 | Single classifier, fastest throughput |
| **medium** | YOLOv5m (INT8) | ResNet-50 + MobileNet-v2 (INT8) | apple.h265 | Dual classifiers, balanced |
| **heavy** | YOLOv11m (INT8) | ResNet-50 + MobileNet-v2 (INT8) | bears.h265 | Larger detection model, highest accuracy |

### `license-plate-recognition` — LPR with OCR

| Mode | Detection Model | Classifier | Video | Description |
|------|----------------|------------|-------|-------------|
| **default** | YOLOv8 LPR (FP32) | PP-OCRv4 (FP32) | license-plate-detection.mp4 | Detect plates → track → OCR classify |

Uses `decodebin3` for MP4 input (unlike the H.265 pipelines which use `h265parse ! vah265dec`).

### Device Configurations

Each pipeline mode has two device parameter files:

| Device | Description |
|--------|-------------|
| `gpu` | All inference on GPU with VA-API surface sharing |
| `gpu_npu` | Detection on GPU, classification offloaded to NPU |

## Pipeline Config Format

Each `pipeline.json` declares two things: **assets** and a **pipeline template**.

### 1. Assets — what models and video the pipeline needs

```json
{
  "assets": {
    "detection_model": "Ultralytics/yolov11n",
    "classification_model": "google/resnet-v1-50-tf",
    "input_video": "https://videos.pexels.com/video-files/18856748/18856748-uhd_3840_2160_60fps.mp4"
  }
}
```

Asset identifiers (e.g. `Ultralytics/yolov11n`) are looked up in the `_MODELS` routing table in `src/assets.py`, which maps them to cache directories and filenames. The tool resolves these to container-absolute paths automatically.

For video, the value can be a Pexels URL (downloaded and transcoded to H.265) or a local filename (used directly from `assets/video/`).

### 2. Pipeline template — GStreamer pipeline with `${var}` placeholders

```json
{
  "pipelines": [{
    "name": "edge-ai-light",
    "mode": "light",
    "pipeline": [
      "filesrc location=\"${video-path}\" ! h265parse ! vah265dec !",
      "gvadetect model=\"${det-model-path}\" device=${detect_device} ... !",
      "gvatrack tracking-type=short-term-imageless !",
      "gvaclassify model=\"${class-model-path}\" device=${classify_0_device} ... !",
      "gvafpscounter starting-frame=2000 !",
      "fakesink sync=false async=false"
    ]
  }]
}
```

Variables come from two sources:
- **Path variables** (e.g. `${video-path}`, `${det-model-path}`) — derived from the `_MODELS` routing table via `build_path_vars()`. Prefixed with `PIPE_ROOT` at render time.
- **Device parameters** (e.g. `${classify_0_device}`, `${classify_0_batch_size}`) — loaded from the selected `params_*.j2` file.

### Device parameter files (`params_*.j2`)

Jinja2-style `{% set var = "value" %}` assignments:

```jinja2
{# GPU-only device parameters #}
{% set detect_batch_size = "8" %}
{% set classify_0_device = "GPU" %}
{% set classify_0_pre_process_backend = "va-surface-sharing" %}
{% set classify_0_nireq = "2" %}
{% set classify_0_ie_config = "ie-config=NUM_STREAMS=2" %}
{% set classify_0_batch_size = "8" %}
```

```jinja2
{# GPU+NPU split device parameters #}
{% set detect_batch_size = "1" %}
{% set classify_0_device = "NPU" %}
{% set classify_0_pre_process_backend = "opencv" %}
{% set classify_0_nireq = "4" %}
{% set classify_0_ie_config = "" %}
{% set classify_0_batch_size = "1" %}
```

## Asset Management

### Model routing table (`_MODELS`)

All model metadata lives in a single `_MODELS` dict in `src/assets.py`. Each entry maps an asset identifier to:

| Field | Required | Description |
|-------|----------|-------------|
| `cache_dir` | Yes | Relative path under `assets/` (e.g. `models/yolo11n`) |
| `xml` | Yes | OpenVINO model filename (`.bin` derived automatically) |
| `downloader` | No | Command list to run inside the assets-download container |
| `urls` | No | List of `(url, local_path)` tuples for direct HTTP download |
| `model_proc` | No | Model-proc JSON — filename (in cache) or `(name, url)` tuple |
| `labels` | No | Path to labels file |
| `pre_setup` | No | Setup command to run before the downloader |

Models with neither `downloader` nor `urls` are assumed to be pre-cached (e.g. the LPR models).

### Auto-download

On first run, `ensure_assets()` checks whether all required model and video files exist in `assets/`. If any are missing, it automatically downloads them:

```
  Missing assets for light pipeline:
    [detection_model] Ultralytics/yolov11n (download + convert)
    [classification_model] google/resnet-v1-50-tf (download + convert)
    [input_video] bears.mp4 (download + transcode + loop)

  Downloading missing assets...
```

Download methods:
- **Script-based** (`downloader` field) — starts the `assets-download` container and runs the conversion script via `docker exec`. Used for Ultralytics, ResNet-50, MobileNet-v2.
- **URL-based** (`urls` field) — direct HTTP download to `assets/`. Used for YOLOv5m.
- **Video** — downloads MP4, transcodes to H.265 1080p 30fps via VA-API, creates 100× looped file.

### Supported models

| Identifier | Model | Format | Download Method |
|------------|-------|--------|-----------------|
| `Ultralytics/yolov11n` | YOLO v11 nano | INT8 | `yolo_downloader.py` + NNCF quantization |
| `Ultralytics/yolov11m` | YOLO v11 medium | INT8 | `yolo_downloader.py` + NNCF quantization |
| `dlstreamer/yolov5m` | YOLO v5 medium | INT8 | Direct HTTP (pre-converted) |
| `google/resnet-v1-50-tf` | ResNet-50 | INT8 | `resnet_downloader.py` + NNCF quantization |
| `pytorch/mobilenet-v2` | MobileNet v2 | INT8 | `mobilenet_downloader.py` + NNCF quantization |
| `public/yolov8_license_plate_detector` | YOLOv8 LPR | FP32 | Pre-cached |
| `public/ch_PP-OCRv4_rec_infer` | PP-OCRv4 | FP32 | Pre-cached |

### Supported videos

| Input | Filename in cache | Format | Content |
|-------|-------------------|--------|---------|
| Pexels URL `.../18856748/...` | `18856748.h265` | H.265 transcoded | Bears wildlife footage |
| Pexels URL `.../6891009/...` | `6891009.h265` | H.265 transcoded | Apple / fruit footage |
| `license-plate-detection.mp4` | `license-plate-detection.mp4` | MP4 (direct) | License plate cars |

## How It Works

When you run a pipeline, the tool performs these steps:

1. **Resolve** — locate `pipeline.json` and auto-detect `params_{device}.j2` for the current hardware.
2. **Ensure assets** — check `assets/` for required models and video; download if missing (skipped with `--dry-run`).
3. **Render** — substitute all `${var}` placeholders from path variables and device parameters.
4. **Adapt** — replace `fakesink` with `gvametaconvert ! gvametapublish ! appsink` for Pipeline Server.
5. **Generate config** — wrap the rendered pipeline in Pipeline Server config format.
6. **Generate .env** — detect GPU render group, resolve core pinning, write compose environment.
7. **Start server** — `docker compose --profile pipeline up -d`.
8. **Wait for ready** — poll `GET /pipelines` until the server responds (up to 90s).
9. **Start instances** — `POST /pipelines/user_defined_pipelines/{name}` for each instance.
10. **Monitor** — tail container logs, extract FPS from `gvafpscounter` every 5s.
11. **Cleanup** — stop all instances, `docker compose down` on exit (including Ctrl+C).

### Docker Compose Services

#### assets-download (profile: `download`)
- Image: `intel/dlstreamer:2026.1.0-20260505-weekly-ubuntu24`
- Runs as root (UID 0) — needed for model conversion and video transcoding
- Kept alive with `tail -f /dev/null`; conversion scripts run via `docker exec`
- Volumes: `./assets:/output` (write), `model-cache:/cache`, `../tools/model-conversion:/model-conversion:ro`
- Devices: `/dev/dri` (GPU for VA-API transcoding)
- Started on-demand when assets are missing; stopped after download

#### pipeline-server (profile: `pipeline`)
- Image: `intel/dlstreamer-pipeline-server:2026.1.0-20260505-weekly-ubuntu24`
- Runs as UID 1999 with `--read-only` filesystem and `no-new-privileges`
- Volume: `./assets:/home/pipeline-server/pipelines:ro` (read-only)
- Config: temp file mounted at `/home/pipeline-server/config.json:ro`
- Devices: `/dev/dri` (GPU), `/dev/accel` (NPU)
- Ports: 8080 (REST API), 8554 (RTSP output)
- Healthcheck: `curl` to `/pipelines` (5s interval, 15 retries)
- Environment: RTSP enabled, GST_DEBUG=1, NPU driver path configured

### Pipeline Server Config Format

```json
{
  "config": {
    "pipelines": [
      {
        "name": "video_analytics_pipeline_light_ARL_gpu",
        "source": "gstreamer",
        "queue_maxsize": 50,
        "pipeline": "<fully rendered GStreamer pipeline string>",
        "auto_start": false
      }
    ]
  }
}
```

## Pipeline Discovery

Pipelines are discovered automatically by scanning for `pipeline.json` files:

```
pipeline-zoo/{use_case}/{mode}/pipeline.json
```

Platform variants are detected from subdirectories containing `params_*.j2` files:

```
{use_case}/{mode}/{platform}/params_{device}.j2
```

Available devices are inferred from parameter file names (e.g. `params_gpu.j2` → device `gpu`).

## Adding a New Pipeline

1. Create a directory: `{use_case}/{mode}/` under `pipeline-zoo/`.
2. Add `pipeline.json` with `assets` and `pipelines` sections.
3. Create a platform subdirectory (e.g. `ARL/`) with `params_{device}.j2` files.
4. If new models are needed, add entries to `_MODELS` in `src/assets.py`.

The tool auto-discovers any directory with a `pipeline.json` — no other code changes needed.

**Example:** To add a `face-detection/default` pipeline:

```bash
mkdir -p face-detection/default/ARL
# Create pipeline.json with assets + pipeline template
# Create ARL/params_gpu.j2 and ARL/params_gpu_npu.j2
# Add model entry to _MODELS in src/assets.py if needed
```

## Dependencies

### Python packages (`requirements.txt`)

```
jinja2>=3.1
requests>=2.28
python-on-whales>=0.70
```

### System / runtime

- Docker Engine with Docker Compose v2
- Intel GPU with VA-API support (`/dev/dri`)
- Optional: Intel NPU (`/dev/accel`) for `gpu_npu` device mode
- `intel/dlstreamer-pipeline-server:2026.1.0-20260505-weekly-ubuntu24` Docker image (pulled automatically)
- `intel/dlstreamer:2026.1.0-20260505-weekly-ubuntu24` Docker image (for model conversion and video transcoding)
