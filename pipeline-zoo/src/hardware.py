"""Hardware detection and core resolution."""

import functools
import subprocess  # nosec B404 — invokes trusted helper_functions.sh
from pathlib import Path

from src.config import PROJECT_ROOT
from src.models import PipelineZooError, PlatformConfig, PipelineConfig


@functools.lru_cache(maxsize=1)
def detect_hardware() -> tuple[bool, bool]:
    """Detect available hardware accelerators.

    Returns (has_gpu, has_npu).
    """
    has_gpu = any(Path("/dev/dri").glob("render*")) if Path("/dev/dri").is_dir() else False
    has_npu = any(Path("/dev/accel").iterdir()) if Path("/dev/accel").is_dir() else False
    return has_gpu, has_npu


def detect_platform(pipeline: PipelineConfig) -> PlatformConfig:
    """Select the best matching platform for this machine.

    Currently picks the first available platform that has params files
    matching the detected device capabilities.
    """
    if not pipeline.platforms:
        raise PipelineZooError(
            f"No platform directories found for {pipeline.pipeline_id}")

    has_gpu, has_npu = detect_hardware()

    # Prefer a platform that supports gpu_npu if NPU is present
    if has_npu:
        for plat in pipeline.platforms.values():
            if "gpu_npu" in plat.devices:
                return plat

    # Fall back to first platform with gpu support
    for plat in pipeline.platforms.values():
        if "gpu" in plat.devices:
            return plat

    # Last resort: first platform
    return next(iter(pipeline.platforms.values()))


def detect_device(platform: PlatformConfig) -> str:
    """Select the best device for the given platform based on hardware.

    Prefers gpu_npu if NPU is available and the platform supports it.
    """
    _, has_npu = detect_hardware()
    if has_npu and "gpu_npu" in platform.devices:
        return "gpu_npu"
    if "gpu" in platform.devices:
        return "gpu"
    return platform.devices[0]


def resolve_cores(taskset):
    """Resolve taskset label (e.g. 'ecore') to a CPU core list."""
    helper = PROJECT_ROOT / "utils" / "helper_functions.sh"
    if not helper.is_file():
        return ""
    result = subprocess.run(  # nosec B603 — trusted script, resolved path
        ["/usr/bin/bash", "-c",
         f"source {helper} && parse_core_pinning {taskset}"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip()
