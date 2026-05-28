#!/usr/bin/env python3
# =============================================================================
# Pipeline Zoo — run optimized DL Streamer pipelines via Pipeline Server
#
# Usage:
#   zoo --list
#   zoo video-analytics-pipeline/light
#   zoo video-analytics-pipeline/light --dry-run
#   zoo video-analytics-pipeline/medium --device gpu_npu --num-instances 2 --duration 60
# =============================================================================

import argparse
import atexit
import json
import signal
import sys

# Ensure the zoo package can be imported regardless of cwd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from src.config import (
    COMPOSE_FILE, ENV_FILE, DEFAULT_IMAGE,
    REST_PORT,
)
from src.models import PipelineZooError
from src.hardware import detect_hardware
from src.docker import is_service_running
from src.api import api_list_pipelines
from src.runner import (
    list_pipelines, resolve_pipeline, render_dry_run, run_pipeline,
    cleanup, _stop_all_instances,
)
from src.docker import compose_down


# =========================================================================== #
#  Command: list                                                              #
# =========================================================================== #

def cmd_list(args):
    """List available pipelines and optionally pick one to run."""
    pipelines = list_pipelines()
    if not pipelines:
        raise PipelineZooError("No pipeline configs found.")

    has_gpu, has_npu = detect_hardware()
    hw_info = []
    if has_gpu:
        hw_info.append("GPU")
    if has_npu:
        hw_info.append("NPU")
    print(f"\n  Detected hardware: {', '.join(hw_info) or 'none'}")

    if ENV_FILE.is_file() and is_service_running("pipeline-server"):
        try:
            loaded = api_list_pipelines(args.port)
            if loaded:
                print("  Server is running with loaded pipelines:")
                for p in loaded:
                    print(f"    - {p['name']}/{p['version']}")
        except (OSError, KeyError):
            pass

    print()
    print(f"  {'#':>4s}  {'PIPELINE':<30s} {'MODE':<10s} {'PLATFORMS':<20s}")
    print(f"  {'-' * 4}  {'-' * 30} {'-' * 10} {'-' * 20}")
    for i, p in enumerate(pipelines, 1):
        platforms_str = ", ".join(
            f"{name}[{','.join(plat.devices)}]"
            for name, plat in p.platforms.items()
        )
        print(f"  {i:4d}  {p.use_case:<30s} {p.mode:<10s} {platforms_str:<20s}")
    print()

    try:
        raw = input(f"  Select pipeline [1-{len(pipelines)}] "
                    f"(0 or Enter to exit): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not raw or raw == "0":
        return

    try:
        choice = int(raw)
    except ValueError:
        raise PipelineZooError(f"Invalid input: {raw}")

    if not (1 <= choice <= len(pipelines)):
        raise PipelineZooError(f"Invalid selection: {choice}")

    selected = pipelines[choice - 1]
    print(f"\n  Selected: {selected.pipeline_id}")

    args.pipeline = selected.pipeline_id
    cmd_run(args)


# =========================================================================== #
#  Command: run                                                               #
# =========================================================================== #

def _gather_asset_overrides(args):
    """Collect non-None asset overrides from CLI args into a dict."""
    keys = ("detection_model", "classification_model_0",
            "classification_model_1", "input_video")
    overrides = {}
    for k in keys:
        v = getattr(args, k, None)
        if v is not None:
            overrides[k] = v
    return overrides or None


def cmd_run(args):
    """Launch a pipeline inside DL Streamer Pipeline Server."""
    num_instances = args.num_instances or 2
    asset_overrides = _gather_asset_overrides(args)

    if args.dry_run:
        result = render_dry_run(
            args.pipeline,
            params_file=args.params_file,
            num_instances=num_instances,
            duration=args.duration,
            image=args.image,
            port=args.port,
            asset_overrides=asset_overrides,
        )
        _print_dry_run(result, num_instances, args)

        if args.save_config:
            save_path = (f"config_{result['pipeline_name']}.json"
                         if args.save_config == "auto" else args.save_config)
            with open(save_path, "w") as f:
                json.dump(result["config"], f, indent=2)
            print(f"  Config saved to: {save_path}")
        return

    # Register cleanup (signal handling stays in CLI)
    _cleanup_done = False

    def _cleanup(*_a):
        nonlocal _cleanup_done
        if _cleanup_done:
            return
        _cleanup_done = True
        print("\n  Shutting down...")
        _stop_all_instances(args.port)
        compose_down()

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    result = run_pipeline(
        args.pipeline,
        params_file=args.params_file,
        num_instances=num_instances,
        duration=args.duration,
        image=args.image,
        port=args.port,
        asset_overrides=asset_overrides,
    )

    # Print summary
    print(f"\n\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"  Pipeline:    {result.pipeline_id}")
    print(f"  Device:      {result.device}")
    print(f"  Instances:   {result.num_instances}")
    print(f"  Duration:    {result.elapsed}s")
    if result.fps is not None:
        print(f"  Total FPS:   {result.fps:.2f}")
    else:
        print(f"  Total FPS:   N/A (check container logs)")
    print(f"  Logs:        {result.log_path}")
    print(f"{'=' * 60}\n")

    if args.save_config:
        info = resolve_pipeline(args.pipeline, args.params_file)
        pipeline_name = result.pipeline_name
        save_path = (f"config_{pipeline_name}.json"
                     if args.save_config == "auto" else args.save_config)
        # Re-render to get config dict for saving
        dr = render_dry_run(
            args.pipeline, params_file=args.params_file,
            asset_overrides=asset_overrides,
        )
        with open(save_path, "w") as f:
            json.dump(dr["config"], f, indent=2)
        print(f"  Config saved to: {save_path}")


def _print_dry_run(result, num_instances, args):
    """Display dry-run output."""
    config = result["config"]
    pipeline_name = result["pipeline_name"]
    request_body = result["request_body"]

    print("  Generated config.json:")
    print(json.dumps(config, indent=4))

    print(f"\n  Compose file: {COMPOSE_FILE}")
    print(f"  Services:")
    print(f"    assets-download  (profile: download)")
    print(f"    pipeline-server  (profile: pipeline, port {args.port})")
    print(f"  Command:")
    print(f"    docker compose -f {COMPOSE_FILE} --profile pipeline up -d")

    print(f"\n  REST request (x{num_instances} instances):")
    print(f"    POST http://localhost:{args.port}/pipelines/"
          f"user_defined_pipelines/{pipeline_name}")
    print(json.dumps(request_body, indent=4))
    print()


# =========================================================================== #
#  Command: cleanup                                                           #
# =========================================================================== #

def cmd_cleanup(args):
    """Remove all runtime-generated artifacts."""
    cleanup()


# =========================================================================== #
#  Main — Argument Parser                                                     #
# =========================================================================== #

def main():
    parser = argparse.ArgumentParser(
        prog="pipeline-zoo",
        description="Pipeline Zoo -- run optimized DL Streamer pipelines "
                    "via Pipeline Server",
    )
    parser.add_argument(
        "pipeline", nargs="?", default=None,
        help="Pipeline path: use_case/mode "
             "(e.g. video-analytics-pipeline/light)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available pipelines and pick one to run",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Remove all runtime artifacts (logs, assets, .env, Docker volumes and images)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show config and commands without executing",
    )
    parser.add_argument(
        "--params-file", dest="params_file", default=None,
        metavar="PATH",
        help="Path to a params .j2 file (e.g. ARL/params_gpu_npu.j2). "
             "Auto-detected if omitted.",
    )
    parser.add_argument(
        "--num-instances", type=int, default=None,
        help="Number of pipeline instances to run (default: 2)",
    )
    parser.add_argument(
        "--duration", type=int, default=120,
        help="Test duration in seconds (default: 120)",
    )
    parser.add_argument(
        "--port", type=int, default=REST_PORT,
        help=f"REST API port (default: {REST_PORT})",
    )
    parser.add_argument(
        "--image", default=DEFAULT_IMAGE,
        help=f"Pipeline server Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--save-config", nargs="?", const="auto", default=None,
        metavar="PATH",
        help="Save generated config.json (default: config_{name}.json)",
    )

    # Asset override flags
    parser.add_argument(
        "--detection-model", dest="detection_model", default=None,
        metavar="ID",
        help="Override detection model asset (e.g. Ultralytics/yolov11n)",
    )
    parser.add_argument(
        "--classification-model-0", dest="classification_model_0",
        default=None, metavar="ID",
        help="Override first classification model asset",
    )
    parser.add_argument(
        "--classification-model-1", dest="classification_model_1",
        default=None, metavar="ID",
        help="Override second classification model asset",
    )
    parser.add_argument(
        "--input-video", dest="input_video", default=None,
        metavar="URL",
        help="Override input video asset (must be a Pexels video URL)",
    )

    args = parser.parse_args()

    try:
        if args.cleanup:
            cmd_cleanup(args)
        elif args.list:
            cmd_list(args)
        elif args.pipeline:
            cmd_run(args)
        else:
            parser.print_help()
    except PipelineZooError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
