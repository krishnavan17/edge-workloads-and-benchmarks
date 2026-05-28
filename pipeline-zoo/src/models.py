"""Data model — shared types and exceptions."""

from dataclasses import dataclass, field
from pathlib import Path


class PipelineZooError(Exception):
    """Raised for any recoverable pipeline-zoo error."""


@dataclass
class PlatformConfig:
    """A platform (e.g. ARL) with its available device params files."""
    name: str
    devices: list[str]
    params_dir: Path


@dataclass
class PipelineConfig:
    """A pipeline identified by use_case/mode with platform variants."""
    use_case: str
    mode: str
    pipeline_dir: Path          # directory containing pipeline.json
    platforms: dict[str, PlatformConfig] = field(default_factory=dict)

    @property
    def pipeline_id(self) -> str:
        return f"{self.use_case}/{self.mode}"


@dataclass
class PipelineResult:
    """Result of a pipeline run — returned by runner.run_pipeline()."""
    pipeline_id: str
    pipeline_name: str
    device: str
    platform: str
    mode: str
    num_instances: int
    elapsed: int                        # seconds
    fps: float | None
    log_path: Path | None
    instance_ids: list[str] = field(default_factory=list)
    gstreamer_pipeline: str = ""
