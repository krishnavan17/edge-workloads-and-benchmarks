"""Asset registry and asset management."""

import copy
import json
import re
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from src.config import (
    ASSETS_DIR, ENV_FILE, DEFAULT_IMAGE, REST_PORT, RTSP_PORT,
)
from src.models import PipelineZooError

_ALLOWED_URL_SCHEMES = ("https",)


# =========================================================================== #
#  Shared constants for downloader scripts running inside Docker              #
# =========================================================================== #

_VENV = "/model-conversion/venv/bin/python3"
_SCRIPTS = "/model-conversion/download-models"
_CACHE = "/cache/datasets"
_OUTPUT = "/output/models"
_LABELS = "/opt/intel/dlstreamer/samples/labels/imagenet_2012.txt"
_MODEL_PROC_URL = (
    "https://raw.githubusercontent.com/open-edge-platform/dlstreamer/"
    "refs/heads/main/samples/gstreamer/model_proc/public/"
    "classification-optimized.json"
)
_YOLOV5_BASE = (
    "https://raw.githubusercontent.com/dlstreamer/pipeline-zoo-models/"
    "refs/heads/main/storage/yolov5m-640_INT8"
)


# =========================================================================== #
#  Thin routing table — each entry describes how to obtain a model            #
#  Everything else (path_vars, check_files) is derived by helpers             #
# =========================================================================== #

_MODELS = {
    "Ultralytics/yolov11n": {
        "downloader":  [_VENV, f"{_SCRIPTS}/yolo_downloader.py",
                        "-m", "yolo11n", "-i", _CACHE, "-o", _OUTPUT],
        "pre_setup":   [_VENV, f"{_SCRIPTS}/initialize_ultralytics.py",
                        "-i", _CACHE],
        "cache_dir":   "models/yolo11n",
        "xml":         "yolo11n_int8.xml",
    },
    "Ultralytics/yolov11m": {
        "downloader":  [_VENV, f"{_SCRIPTS}/yolo_downloader.py",
                        "-m", "yolo11m", "-i", _CACHE, "-o", _OUTPUT],
        "pre_setup":   [_VENV, f"{_SCRIPTS}/initialize_ultralytics.py",
                        "-i", _CACHE],
        "cache_dir":   "models/yolo11m",
        "xml":         "yolo11m_int8.xml",
    },
    "dlstreamer/yolov5m": {
        "urls": [
            (f"{_YOLOV5_BASE}/FP16-INT8/yolov5m-640_INT8.xml",
             "models/yolo-v5m/yolov5m-640_INT8.xml"),
            (f"{_YOLOV5_BASE}/FP16-INT8/yolov5m-640_INT8.bin",
             "models/yolo-v5m/yolov5m-640_INT8.bin"),
            (f"{_YOLOV5_BASE}/yolo-v5.json",
             "models/yolo-v5m/yolo-v5.json"),
        ],
        "cache_dir":   "models/yolo-v5m",
        "xml":         "yolov5m-640_INT8.xml",
        "model_proc":  "yolo-v5.json",
    },
    "google/resnet-v1-50-tf": {
        "downloader":  [_VENV, f"{_SCRIPTS}/resnet_downloader.py",
                        "-o", f"{_OUTPUT}/resnet-50"],
        "cache_dir":   "models/resnet-50",
        "xml":         "resnet-50_int8.xml",
        "model_proc":  ("resnet-50.json", _MODEL_PROC_URL),
        "labels":      _LABELS,
    },
    "pytorch/mobilenet-v2": {
        "downloader":  [_VENV, f"{_SCRIPTS}/mobilenet_downloader.py",
                        "-o", f"{_OUTPUT}/mobilenet-v2"],
        "cache_dir":   "models/mobilenet-v2",
        "xml":         "mobilenetv2_int8.xml",
        "model_proc":  ("mobilenet-v2.json", _MODEL_PROC_URL),
        "labels":      _LABELS,
    },
    "public/yolov8_license_plate_detector": {
        "cache_dir":   "models/yolov8-lpr",
        "xml":         "yolov8_license_plate_detector.xml",
    },
    "public/ch_PP-OCRv4_rec_infer": {
        "cache_dir":   "models/ppocr-v4",
        "xml":         "ch_PP-OCRv4_rec_infer.xml",
    },
}


# =========================================================================== #
#  Helpers — derive path_vars, check_files, and video info from the table     #
# =========================================================================== #

def _xml_to_bin(xml):
    """Derive .bin filename from .xml filename."""
    return xml.rsplit(".", 1)[0] + ".bin"


def _check_files(entry):
    """Return list of cache-relative paths that must exist for a model."""
    cdir = entry["cache_dir"]
    files = [f"{cdir}/{entry['xml']}", f"{cdir}/{_xml_to_bin(entry['xml'])}"]
    proc = entry.get("model_proc")
    if isinstance(proc, tuple):  # (name, url) — downloaded separately
        files.append(f"{cdir}/{proc[0]}")
    elif isinstance(proc, str):  # filename already in cache (e.g. yolov5m)
        files.append(f"{cdir}/{proc}")
    return files


def get_model_path_vars(asset_id):
    """Return {suffix: relative_path} for a model asset.

    Keys: "model-path" (points to .xml), "model-dir" (parent directory).
    Paths are relative to PIPE_ROOT and contain no {mode} template.
    """
    entry = _MODELS[asset_id]
    cdir = entry["cache_dir"]
    return {
        "model-path": f"{cdir}/{entry['xml']}",
        "model-dir":  cdir,
    }


def get_model_labels(asset_id):
    """Return the labels path for a model, or None."""
    return _MODELS.get(asset_id, {}).get("labels")


def resolve_video(url_or_path):
    """Derive local video paths from a Pexels URL or local filename.

    For Pexels URLs: extracts video ID, expects H.265 transcoded output.
    For local filenames: uses the file directly from video/ cache.
    """
    m = re.search(r"/video-files/(\d+)/", url_or_path)
    if m:
        vid = m.group(1)
        return {
            "path_vars":  {"path": f"video/{vid}.h265"},
            "mp4_name":   f"{vid}.mp4",
            "h265_name":  f"{vid}.h265",
            "h265_loop":  f"{vid}_loop100.h265",
            "check_file": f"video/{vid}.h265",
        }
    if not url_or_path.startswith("http"):
        name = url_or_path
        return {
            "path_vars":  {"path": f"video/{name}"},
            "mp4_name":   name,
            "h265_name":  None,
            "h265_loop":  None,
            "check_file": f"video/{name}",
        }
    raise PipelineZooError(
        f"Cannot resolve video asset: {url_or_path}\n"
        f"  Expected a Pexels URL or a local filename.")


# Maps pipeline.json asset keys to variable-name prefixes used in templates.
ASSET_KEY_PREFIX = {
    "detection_model":        "det",
    "classification_model":   "class",
    "classification_model_0": "class1",
    "classification_model_1": "class2",
    "input_video":            "video",
}

# Maps CLI flag dest names to the pipeline.json asset key(s) they override.
_CLI_TO_ASSET_KEYS = {
    "detection_model":        ["detection_model"],
    "classification_model_0": ["classification_model_0", "classification_model"],
    "classification_model_1": ["classification_model_1"],
    "input_video":            ["input_video"],
}


def apply_asset_overrides(args, pipeline_data):
    """Apply CLI asset override flags to pipeline data.

    Returns pipeline_data (possibly deep-copied with overridden asset IDs).
    """
    overrides = {}
    for dest, asset_keys in _CLI_TO_ASSET_KEYS.items():
        value = getattr(args, dest, None)
        if value is not None:
            overrides[dest] = value

    if not overrides:
        return pipeline_data

    pipeline_data = copy.deepcopy(pipeline_data)
    assets = pipeline_data.get("assets", {})

    for dest, value in overrides.items():
        replaced = False
        for key in _CLI_TO_ASSET_KEYS[dest]:
            if key in assets:
                print(f"  Override: {key} = {value}  (was {assets[key]})")
                assets[key] = value
                replaced = True
                break
        if not replaced:
            raise PipelineZooError(
                f"Cannot override '{dest}': no matching asset key in "
                f"pipeline.json (tried: {_CLI_TO_ASSET_KEYS[dest]})")

    return pipeline_data


def _validate_url(url):
    """Reject URLs with unexpected schemes (only https allowed)."""
    scheme = urlparse(url).scheme
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise PipelineZooError(
            f"Unsupported URL scheme '{scheme}' in: {url}\n"
            f"  Allowed: {', '.join(_ALLOWED_URL_SCHEMES)}")


def _download_url(url, dest):
    """Download a file from *url* to *dest* with a simple progress message."""
    _validate_url(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"    Downloading {dest.name}...")
    try:
        resp = urllib.request.urlopen(url, timeout=300)  # nosec B310 — scheme validated by _validate_url()
        with open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except (urllib.error.URLError, OSError) as exc:
        raise PipelineZooError(f"Download failed for {url}: {exc}") from exc


def _download_model(asset_id):
    """Download/convert a model asset into the cache directory.

    For URL-based models (yolov5m): download directly from GitHub.
    For script-based models: run conversion script via docker exec.
    No install/copy step — path_vars point directly at the cache.
    """
    from src.docker import docker_exec

    entry = _MODELS[asset_id]
    cache_dir = entry["cache_dir"]

    # Check if already cached
    check = _check_files(entry)
    if all((ASSETS_DIR / f).is_file() for f in check):
        print(f"    Using cached model files for {asset_id}")
        return

    if "urls" in entry:
        # Direct download (e.g. yolov5m pre-converted from GitHub)
        for url, dest_rel in entry["urls"]:
            dest_path = ASSETS_DIR / dest_rel
            if not dest_path.is_file():
                _download_url(url, dest_path)
    elif "downloader" in entry:
        # Run downloader script via docker exec
        if "pre_setup" in entry:
            pre_cmd = entry["pre_setup"]
            print(f"    Running {Path(pre_cmd[1]).name}...")
            docker_exec("pipeline-zoo-assets", pre_cmd)

        cmd = entry["downloader"]
        print(f"    Running {Path(cmd[1]).name}...")
        docker_exec("pipeline-zoo-assets", cmd)
    else:
        raise PipelineZooError(
            f"Model '{asset_id}' has no downloader or URLs and is not cached.\n"
            f"  Expected files in: {ASSETS_DIR / cache_dir}")

    # Download model-proc JSON if specified as (name, url) tuple
    proc = entry.get("model_proc")
    if isinstance(proc, tuple):
        proc_name, proc_url = proc
        dst = ASSETS_DIR / cache_dir / proc_name
        if not dst.is_file():
            _download_url(proc_url, dst)


def ensure_assets(pipeline_dir, mode, data=None, asset_port=None):
    """Check pipeline assets exist; auto-download if missing.

    Script-based models run inside the assets-download container via docker exec.
    URL-based models (yolov5m) are downloaded directly.
    Videos are transcoded by the video-download service (one-shot).

    Returns immediately if all assets are present.
    Raises PipelineZooError if download fails.
    """
    from src.docker import (
        validate_compose, compose_up, compose_stop, exec_video_download,
        generate_env_file, wait_for_container,
    )

    if data is None:
        pj_path = pipeline_dir / "pipeline.json"
        data = json.loads(pj_path.read_text())
    assets = data.get("assets", {})

    missing_models = []
    missing_videos = []

    for key, asset_id in assets.items():
        if key == "input_video":
            vreg = resolve_video(asset_id)
            check = ASSETS_DIR / vreg["check_file"]
            if not check.is_file():
                missing_videos.append((key, asset_id))
        else:
            if asset_id not in _MODELS:
                available = ", ".join(sorted(_MODELS))
                raise PipelineZooError(
                    f"Unknown model asset '{asset_id}' for key '{key}'.\n"
                    f"  Available models: {available}")
            for f in _check_files(_MODELS[asset_id]):
                if not (ASSETS_DIR / f).is_file():
                    missing_models.append((key, asset_id))
                    break

    if not missing_models and not missing_videos:
        return  # All assets present

    print(f"\n  Missing assets for {mode} pipeline:")
    for key, asset_id in missing_models:
        entry = _MODELS[asset_id]
        cached = all((ASSETS_DIR / f).is_file() for f in _check_files(entry))
        tag = " (cached)" if cached else " (download + convert)"
        print(f"    [{key}] {asset_id}{tag}")
    for key, url in missing_videos:
        vreg = resolve_video(url)
        print(f"    [{key}] {vreg['mp4_name']} (download + transcode + loop)")

    print("\n  Downloading missing assets...")
    print()

    # Ensure assets directory exists and is writable by the container
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.chmod(0o777)  # noqa: S103

    # Ensure .env file exists
    if not ENV_FILE.is_file():
        generate_env_file("/dev/null", DEFAULT_IMAGE, REST_PORT, RTSP_PORT)

    # ── Start assets-download container if anything is missing ───────────────
    needs_container = any(
        "downloader" in _MODELS[a]
        for _k, a in missing_models
    ) or bool(missing_videos)

    if needs_container:
        print("  Starting assets-download container...")
        validate_compose()
        compose_up("download")
        wait_for_container("assets-download", profile="download")
        print("  Container ready.\n")

    # ── Phase 1: Model downloads ────────────────────────────────────────────
    for key, asset_id in missing_models:
        print(f"  Downloading {asset_id}...")
        _download_model(asset_id)
        print()

    # ── Phase 2: Video download + transcode ─────────────────────────────────
    if missing_videos:
        print("  Starting video download + transcode...")
        video_args = []
        for _key, url in missing_videos:
            vreg = resolve_video(url)
            video_args.extend([
                "--url", url,
                "--output-path", vreg["check_file"],
                "--loop-count", "100",
            ])
        exec_video_download(video_args)
        print()

    # ── Stop assets-download container ──────────────────────────────────────
    if needs_container:
        print("  Stopping assets-download container...")
        compose_stop("assets-download")

    # ── Verify ──────────────────────────────────────────────────────────────
    still_missing = []
    for key, asset_id in missing_models:
        for f in _check_files(_MODELS[asset_id]):
            if not (ASSETS_DIR / f).is_file():
                still_missing.append(f)
    for key, url in missing_videos:
        vreg = resolve_video(url)
        if not (ASSETS_DIR / vreg["check_file"]).is_file():
            still_missing.append(vreg["check_file"])

    if still_missing:
        msg = "Some assets still missing after download:\n"
        for f in still_missing:
            msg += f"  {f}\n"
        raise PipelineZooError(msg)

    print("  All assets ready.\n")
