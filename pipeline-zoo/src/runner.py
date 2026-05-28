"""Pipeline Zoo runner — programmatic API for pipeline orchestration.

External usage:
    from src.runner import run_pipeline, list_pipelines, render_dry_run

    result = run_pipeline("video-analytics-pipeline/light",
                          params_file="ARL/params_gpu_npu.j2", duration=120)
    print(result.fps, result.log_path)
"""

import json
import os
import shutil
import tempfile
import time

from pathlib import Path

from src.config import (
    ENV_FILE, DEFAULT_IMAGE, REST_PORT, RTSP_PORT,
    ASSETS_DIR, LOGS_DIR,
)
from src.models import PipelineZooError, PipelineResult
from src.hardware import detect_hardware, detect_platform, detect_device
from src.rendering import (
    discover_pipelines, generate_config_json, build_path_vars,
)
from src.docker import (
    validate_compose, ensure_image, compose_up, compose_down,
    compose_stop, is_service_running, generate_env_file,
)
from src.api import (
    wait_for_ready, api_list_pipelines, api_start_pipeline,
    api_get_all_status, api_stop_pipeline, LogCapture,
)
from src.assets import ensure_assets, apply_asset_overrides


# =========================================================================== #
#  Public API                                                                 #
# =========================================================================== #

def list_pipelines():
    """Return all discovered pipeline configs.

    Returns:
        list[PipelineConfig]
    """
    return discover_pipelines()


def resolve_pipeline(pipeline_arg, params_file=None):
    """Resolve a pipeline argument to its metadata.

    Args:
        pipeline_arg: "use_case/mode" (e.g. "video-analytics-pipeline/light")
        params_file: Optional path to a params .j2 file.
                     Auto-detected if None.

    Returns:
        dict with keys: pipeline_id, use_case, platform, mode, device,
        pipeline_dir, params_file, has_gpu, has_npu
    """
    pipeline_arg = pipeline_arg.strip("/")
    parts = pipeline_arg.split("/")
    if len(parts) != 2:
        raise PipelineZooError(
            f"Expected use_case/mode, got: {pipeline_arg}")

    use_case, mode = parts

    pipelines = discover_pipelines()
    pipeline = None
    for p in pipelines:
        if p.use_case == use_case and p.mode == mode:
            pipeline = p
            break

    if pipeline is None:
        available = [p.pipeline_id for p in pipelines]
        raise PipelineZooError(
            f"Pipeline not found: {pipeline_arg}\n"
            f"Available: {', '.join(available) or 'none'}")

    platform = detect_platform(pipeline)

    if params_file:
        params_file = Path(params_file)
        if params_file.is_absolute():
            resolved = params_file
        elif params_file.exists():
            resolved = params_file.resolve()
        else:
            resolved = pipeline.pipeline_dir / params_file
        if not resolved.is_file():
            raise PipelineZooError(f"Params file not found: {resolved}")
        params_file = resolved
        device = params_file.stem.removeprefix("params_")
    else:
        device = detect_device(platform)
        params_file = platform.params_dir / f"params_{device}.j2"

    has_gpu, has_npu = detect_hardware()

    return {
        "pipeline_id": pipeline.pipeline_id,
        "use_case": use_case,
        "platform": platform.name,
        "mode": mode,
        "device": device,
        "pipeline_dir": pipeline.pipeline_dir,
        "params_file": params_file,
        "has_gpu": has_gpu,
        "has_npu": has_npu,
    }


def render_dry_run(pipeline_arg, params_file=None, num_instances=2,
                   duration=120, image=DEFAULT_IMAGE, port=REST_PORT,
                   asset_overrides=None):
    """Render pipeline config without executing.

    Returns:
        dict with keys: config, request_body, pipeline_name, info
    """
    info = resolve_pipeline(pipeline_arg, params_file)
    pipeline_dir = info["pipeline_dir"]
    params_file = info["params_file"]
    mode = info["mode"]
    use_case = info["use_case"]
    device = info["device"]
    pipeline_name = (
        f"{use_case}_{mode}_{info['platform']}_{device}".replace("-", "_"))

    pj_path = pipeline_dir / "pipeline.json"
    pipeline_data = json.loads(pj_path.read_text())

    if asset_overrides:
        pipeline_data = _apply_overrides(pipeline_data, asset_overrides)

    config = generate_config_json(pipeline_dir, params_file, pipeline_name,
                                  data=pipeline_data)
    request_body = _build_request_body(pipeline_data, pipeline_name)

    return {
        "config": config,
        "request_body": request_body,
        "pipeline_name": pipeline_name,
        "info": info,
    }


def run_pipeline(pipeline_arg, params_file=None, num_instances=2, duration=120,
                 image=DEFAULT_IMAGE, port=REST_PORT,
                 asset_overrides=None, log=print):
    """Run a pipeline end-to-end and return the result.

    Args:
        pipeline_arg: "use_case/mode" (e.g. "video-analytics-pipeline/light")
        params_file: Path to a params .j2 file; auto-detected if None.
        num_instances: Number of pipeline instances (default 2).
        duration: Monitoring duration in seconds (default 120).
        image: Pipeline server Docker image.
        port: REST API port.
        asset_overrides: Dict mapping asset keys to override values, or None.
        log: Callable for progress messages (default: print). Pass None to
             suppress output.

    Returns:
        PipelineResult
    """
    if log is None:
        log = lambda *a, **kw: None  # noqa: E731

    # -- Resolve pipeline --
    info = resolve_pipeline(pipeline_arg, params_file)
    pipeline_dir = info["pipeline_dir"]
    params_file = info["params_file"]
    mode = info["mode"]
    use_case = info["use_case"]
    device = info["device"]
    platform = info["platform"]
    pid = info["pipeline_id"]
    pipeline_name = (
        f"{use_case}_{mode}_{platform}_{device}".replace("-", "_"))

    hw_info = []
    if info["has_gpu"]:
        hw_info.append("GPU")
    if info["has_npu"]:
        hw_info.append("NPU")
    log(f"\n  Hardware:  {', '.join(hw_info) or 'none detected'}")
    log(f"  Platform:  {platform}")
    log(f"  Params:    {params_file}")

    # -- Load pipeline data --
    pj_path = pipeline_dir / "pipeline.json"
    pipeline_data = json.loads(pj_path.read_text())

    if asset_overrides:
        pipeline_data = _apply_overrides(pipeline_data, asset_overrides)

    # -- Ensure assets --
    ensure_assets(pipeline_dir, mode, data=pipeline_data)

    # -- Generate config --
    log(f"\n{'=' * 60}")
    log(f"  Pipeline Zoo -- {pid} --params-file {params_file.name}")
    log(f"  Instances: {num_instances}  Duration: {duration}s")
    log(f"{'=' * 60}")

    config = generate_config_json(pipeline_dir, params_file, pipeline_name,
                                  data=pipeline_data)
    gst_pipeline = config["config"]["pipelines"][0]["pipeline"]
    log(f"\n  GStreamer pipeline:")
    log(f"  {gst_pipeline}\n")

    # -- Write config to temp file --
    with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="zoo-config-",
            delete=False) as tmp:
        config_path = tmp.name
        json.dump(config, tmp, indent=2)
    # Container UID 1999 reads this via bind mount — must be world-readable.
    # File contains only a GStreamer pipeline string, no secrets.
    os.chmod(
    config_path, 0o644
    )  # nosec: B103 - temp config must be world-readable for container UID 1999; no secrets stored

    try:

        # -- Stop any existing pipeline server --
        if ENV_FILE.is_file() and is_service_running("pipeline-server"):
            log("\n  Stopping existing pipeline server...")
            compose_stop("pipeline-server")
            import time as _t
            _t.sleep(2)

        # -- Generate .env and start via compose --
        generate_env_file(config_path, image, port, RTSP_PORT)
        validate_compose()
        ensure_image(image)

        log(f"\n  Starting pipeline server via compose...")
        compose_up("pipeline")

        # -- Wait for server ready --
        log(f"  Waiting for pipeline server (port {port})...")
        if not wait_for_ready(port, timeout=90):
            raise PipelineZooError(
                "Pipeline server did not become ready.")
        log("  Pipeline server is ready.")

        loaded = api_list_pipelines(port)
        for p in loaded:
            log(f"    Loaded: {p['name']}/{p['version']}")

        # -- Build request + start instances --
        request_body = _build_request_body(pipeline_data, pipeline_name)

        instance_ids = []
        log(f"\n  Starting {num_instances} pipeline instance(s)...")
        for i in range(num_instances):
            req = json.loads(json.dumps(request_body))
            if num_instances > 1:
                req["destination"]["frame"]["path"] = f"{pipeline_name}_{i}"
                req["destination"]["metadata"]["path"] = (
                    f"/tmp/{pipeline_name}_{i}_results.jsonl") #nosec: B108 - temp file created on docker image, no sectrets stored.
            try:
                instance_id = api_start_pipeline(port, pipeline_name, req)
                instance_ids.append(instance_id)
                rtsp_path = req["destination"]["frame"]["path"]
                log(f"    Instance {i}: {instance_id[:12]}...  "
                    f"RTSP: rtsp://localhost:{RTSP_PORT}/{rtsp_path}")
            except Exception as e:
                log(f"    Instance {i}: FAILED -- {e}")

        if not instance_ids:
            raise PipelineZooError("No pipeline instances started.")

        # -- Monitor --
        log(f"\n  Monitoring for {duration}s (Ctrl+C to stop)...")
        log(f"  {'TIME':>6s}  {'STATE':<14s} {'FPS':>8s}")
        log(f"  {'-' * 6}  {'-' * 14} {'-' * 8}")

        log_capture = LogCapture("pipeline-server",
                                 pipeline_name=pipeline_name)
        log_capture.start()

        start_time = time.time()
        last_fps = None
        try:
            while time.time() - start_time < duration:
                elapsed = int(time.time() - start_time)
                states = _collect_states(port, instance_ids)
                fps = log_capture.fps
                if fps is not None:
                    last_fps = fps

                running = sum(1 for s in states.values() if s == "RUNNING")
                state_str = f"{running}/{len(instance_ids)} running"
                fps_str = f"{fps:.1f}" if fps is not None else "..."

                log(f"  {elapsed:5d}s  {state_str:<14s} {fps_str:>8s}",
                    end="\r")

                if all(s in ("COMPLETED", "ERROR", "ABORTED")
                       for s in states.values()):
                    log(f"\n  All pipelines finished at {elapsed}s.")
                    break

                time.sleep(5)

        except KeyboardInterrupt:
            pass
        finally:
            log_capture.stop()

        # -- Collect result --
        elapsed = int(time.time() - start_time)
        fps = log_capture.fps
        if fps is not None:
            last_fps = fps

        return PipelineResult(
            pipeline_id=pid,
            pipeline_name=pipeline_name,
            device=device,
            platform=platform,
            mode=mode,
            num_instances=num_instances,
            elapsed=elapsed,
            fps=last_fps,
            log_path=log_capture.log_path,
            instance_ids=instance_ids,
            gstreamer_pipeline=gst_pipeline,
        )

    finally:
        # Cleanup
        _stop_all_instances(port)
        compose_down()
        try:
            os.unlink(config_path)
        except OSError:
            pass


def cleanup(log=print):
    """Remove all runtime-generated artifacts.

    Removes: logs/, assets/, .env, Docker volumes 'model-cache' and
    'video-cache', and stopped pipeline-zoo containers.

    Args:
        log: Callable for progress messages. Pass None to suppress.

    Returns:
        dict with keys: removed (list of paths), bytes_freed (int).
    """
    if log is None:
        log = lambda *a, **kw: None  # noqa: E731

    removed = []
    bytes_freed = 0

    def _rm_dir(path, label):
        nonlocal bytes_freed
        if not path.is_dir():
            return
        size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        shutil.rmtree(path)
        bytes_freed += size
        removed.append(str(path))
        log(f"  Removed {label}: {_fmt_size(size)}")

    def _rm_file(path, label):
        nonlocal bytes_freed
        if not path.is_file():
            return
        size = path.stat().st_size
        path.unlink()
        bytes_freed += size
        removed.append(str(path))
        log(f"  Removed {label}")

    log("\n  Cleanup:")

    _rm_dir(LOGS_DIR, f"logs/ ({_count_files(LOGS_DIR)} files)")
    _rm_file(ENV_FILE, ".env")
    _rm_dir(ASSETS_DIR, f"assets/ ({_count_files(ASSETS_DIR)} files)")

    # Remove __pycache__ directories
    from src.config import ZOO_DIR
    for pycache in sorted(ZOO_DIR.rglob("__pycache__")):
        if pycache.is_dir():
            _rm_dir(pycache, f"{pycache.relative_to(ZOO_DIR)}/")

    from src.docker import remove_volume, remove_zoo_containers, remove_image
    from src.config import DEFAULT_IMAGE, DLSTREAMER_IMAGE
    remove_zoo_containers(log=log)
    for vol in ("pipeline-zoo_model-cache", "pipeline-zoo_video-cache",
                "pipeline-zoo_asset-cache"):
        remove_volume(vol, log=log)
    remove_image(DEFAULT_IMAGE, log=log)
    remove_image(DLSTREAMER_IMAGE, log=log)

    if not removed:
        log("  Nothing to clean.")

    log(f"\n  Total freed: {_fmt_size(bytes_freed)}")

    return {
        "removed": removed,
        "bytes_freed": bytes_freed,
    }


def _count_files(path):
    """Count files in a directory (non-recursive is fine for display)."""
    if not path.is_dir():
        return 0
    return sum(1 for f in path.rglob("*") if f.is_file())


def _fmt_size(nbytes):
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# =========================================================================== #
#  Internal helpers                                                           #
# =========================================================================== #

def _apply_overrides(pipeline_data, overrides):
    """Apply asset overrides from a plain dict.

    Args:
        overrides: dict mapping CLI-style keys
                   (detection_model, classification_model_0, etc.)
                   to asset IDs.
    """
    import copy
    from src.assets import _CLI_TO_ASSET_KEYS

    pipeline_data = copy.deepcopy(pipeline_data)
    assets = pipeline_data.get("assets", {})

    for dest, value in overrides.items():
        keys = _CLI_TO_ASSET_KEYS.get(dest)
        if not keys:
            continue
        replaced = False
        for key in keys:
            if key in assets:
                assets[key] = value
                replaced = True
                break
        if not replaced:
            raise PipelineZooError(
                f"Cannot override '{dest}': no matching asset key in "
                f"pipeline.json (tried: {keys})")

    return pipeline_data


def _build_request_body(pipeline_data, pipeline_name):
    """Build the REST API request body for a pipeline run."""
    mode = pipeline_data["pipelines"][0].get("mode", "unknown")
    assets = pipeline_data.get("assets", {})
    pv = build_path_vars(assets, mode)
    video_path = pv.get("video-path", "<video-path>")
    return {
        "source": {
            "uri": f"file://{video_path}",
            "type": "uri",
        },
        "destination": {
            "metadata": {
                "type": "file",
                "path": f"/tmp/{pipeline_name}_results.jsonl", #nosec: B108 - temp file created on docker image, no sectrets stored.
                "format": "json-lines",
            },
            "frame": {
                "type": "rtsp",
                "path": pipeline_name,
            },
        },
    }


def _collect_states(port, instance_ids):
    """Collect pipeline states with a single bulk API call."""
    states = {iid: "UNKNOWN" for iid in instance_ids}
    try:
        all_status = api_get_all_status(port)
        if isinstance(all_status, list):
            by_id = {s["id"]: s for s in all_status if "id" in s}
            for iid in instance_ids:
                info = by_id.get(iid)
                if info and "state" in info:
                    states[iid] = info["state"]
    except (OSError, KeyError):
        pass
    return states


def _stop_all_instances(port):
    """Stop all running pipeline instances."""
    try:
        statuses = api_get_all_status(port)
        for status in statuses:
            status_id = status.get("id")
            state = status.get("state", "")
            if status_id and state not in ("COMPLETED", "ERROR", "ABORTED"):
                api_stop_pipeline(port, status_id)
    except OSError:
        pass
