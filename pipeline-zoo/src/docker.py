"""Docker Compose lifecycle (python-on-whales)."""

import sys
import time
from pathlib import Path

from src.config import (
    COMPOSE_FILE, ENV_FILE, ZOO_DIR, PROJECT_ROOT,
)
from src.models import PipelineZooError
from src.hardware import resolve_cores

try:
    from python_on_whales import DockerClient
    from python_on_whales.exceptions import DockerException
except ImportError:
    DockerClient = None
    DockerException = Exception


def _docker(profile=None):
    """Create a DockerClient configured for our compose project."""
    if DockerClient is None:
        raise PipelineZooError(
            "'python-on-whales' package not found.\n"
            "  Install: pip install python-on-whales>=0.70\n"
            "  If using sudo: sudo -E env PATH=$PATH ./pipeline-zoo.py ...")
    profiles = [profile] if isinstance(profile, str) else (profile or [])
    return DockerClient(
        compose_files=[str(COMPOSE_FILE)],
        compose_profiles=profiles,
        compose_env_files=[str(ENV_FILE)] if ENV_FILE.is_file() else [],
    )


def validate_compose():
    """Validate compose file + .env before launching."""
    try:
        _docker(["download", "pipeline"]).compose.config()
    except DockerException as exc:
        raise PipelineZooError(f"Invalid compose config:\n{exc}") from exc


def ensure_image(image):
    """Pull image only if not present locally."""
    docker = _docker()
    if docker.image.exists(image):
        print(f"  Image {image} already cached.")
    else:
        print(f"  Pulling {image}...")
        try:
            docker.image.pull(image)
        except DockerException as exc:
            raise PipelineZooError(
                f"Failed to pull image {image}:\n{exc}") from exc


def wait_for_healthy(service, timeout=90):
    """Wait for a container's healthcheck to report 'healthy'.

    Falls back to checking if the container is running when no
    healthcheck is configured.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            containers = _docker().compose.ps(services=[service])
            if not containers:
                time.sleep(2)
                continue
            c = containers[0]
            health = getattr(c.state, "health", None)
            if health is not None and health.status == "healthy":
                return True
            if health is None and c.state.status == "running":
                return True
            if c.state.status in ("exited", "dead"):
                logs = compose_logs(service, tail=30)
                print(f"Error: {service} exited unexpectedly.",
                      file=sys.stderr)
                if logs:
                    print("Container logs:", file=sys.stderr)
                    print(logs, file=sys.stderr)
                return False
        except DockerException:
            pass
        time.sleep(2)
    return False


def wait_for_container(service, timeout=60, profile=None):
    """Wait until a compose service container is running.

    Unlike wait_for_healthy(), this does not require a healthcheck —
    it simply waits for the container status to be 'running'.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            containers = _docker(profile).compose.ps(services=[service])
            if containers and containers[0].state.status == "running":
                return True
            if containers and containers[0].state.status in ("exited", "dead"):
                logs = compose_logs(service, tail=30)
                print(f"Error: {service} exited unexpectedly.",
                      file=sys.stderr)
                if logs:
                    print("Container logs:", file=sys.stderr)
                    print(logs, file=sys.stderr)
                return False
        except DockerException:
            pass
        time.sleep(2)
    return False


def generate_env_file(config_path, image, rest_port, rtsp_port):
    """Generate .env file for docker compose."""
    render_gid = None
    dri = Path("/dev/dri")
    if dri.is_dir():
        for dev in sorted(dri.glob("render*")):
            try:
                render_gid = dev.stat().st_gid
                break
            except OSError:
                pass

    if render_gid is None:
        raise PipelineZooError("No /dev/dri/render* device found.")

    cores = resolve_cores("ecore")
    if cores:
        print(f"  Resolved e-cores: {cores}")

    env_lines = [
        f"CONFIG_PATH={config_path}",
        f"PIPELINE_SERVER_IMAGE={image}",
        f"REST_PORT={rest_port}",
        f"RTSP_PORT={rtsp_port}",
        f"RENDER_GROUP={render_gid}",
        f"CORE_PINNING={cores}" if cores else "CORE_PINNING=",
    ]

    ENV_FILE.write_text("\n".join(env_lines) + "\n")


def compose_up(profile, build=False):
    """Start a compose service profile."""
    try:
        _docker(profile).compose.up(detach=True, build=build)
    except DockerException as exc:
        raise PipelineZooError(
            f"docker compose up --profile {profile} failed:\n{exc}") from exc


def compose_down():
    """Stop and remove all compose services."""
    try:
        _docker(["download", "pipeline"]).compose.down(
            remove_orphans=True)
    except DockerException:
        pass


def compose_stop(service):
    """Stop a specific compose service."""
    try:
        _docker().compose.stop(services=[service])
    except DockerException:
        pass


def compose_logs(service, tail=50):
    """Get logs from a compose service."""
    try:
        return _docker().compose.logs(services=[service], tail=str(tail))
    except DockerException:
        return ""


def compose_logs_stream(service):
    """Stream logs from a compose service as an iterator of lines.

    Yields decoded log lines (str) one at a time.
    """
    for _source, chunk in _docker().compose.logs(
        services=[service], follow=True, stream=True, tail=1000
    ):
        yield chunk.decode(errors="replace")


def is_service_running(service):
    """Check if a compose service container is running."""
    try:
        containers = _docker().compose.ps(services=[service])
        return any(c.state.status == "running" for c in containers)
    except DockerException:
        return False


def docker_exec(container, cmd):
    """Run a command inside a running container.

    Raises PipelineZooError if the command fails.
    """
    if DockerClient is None:
        raise PipelineZooError("python-on-whales not available")
    docker = DockerClient()
    try:
        output = docker.container.execute(container, cmd)
        if output:
            for line in output.splitlines():
                print(f"    [exec] {line}")
    except DockerException as exc:
        raise PipelineZooError(
            f"docker exec in {container} failed:\n{exc}") from exc


def exec_video_download(args):
    """Run video_download.py inside the assets-download container.

    The container must already be running (started via compose_up).
    The script is bind-mounted at /opt/scripts/video_download.py.
    """
    cmd = ["python3", "/opt/scripts/video_download.py"] + list(args)
    docker_exec("pipeline-zoo-assets", cmd)


# =========================================================================== #
#  Cleanup helpers                                                            #
# =========================================================================== #

_ZOO_CONTAINERS = (
    "pipeline-zoo-assets", "pipeline-zoo-server",
)


def remove_zoo_containers(log=print):
    """Remove stopped pipeline-zoo containers.

    Returns True if any containers were removed.
    """
    if DockerClient is None:
        return False
    docker = DockerClient()
    removed = False
    for name in _ZOO_CONTAINERS:
        try:
            c = docker.container.inspect(name)
            if c.state.status != "running":
                docker.container.remove(name, force=True)
                log(f"  Removed container: {name}")
                removed = True
        except DockerException:
            pass
    return removed


def remove_volume(name, log=print):
    """Remove a Docker volume by name.

    Returns True if the volume was removed.
    """
    if DockerClient is None:
        return False
    docker = DockerClient()
    try:
        docker.volume.remove(name)
        log(f"  Removed volume: {name}")
        return True
    except DockerException:
        return False


def remove_image(image, log=print):
    """Remove a Docker image by name.

    Returns True if the image was removed.
    """
    if DockerClient is None:
        return False
    docker = DockerClient()
    try:
        if docker.image.exists(image):
            docker.image.remove(image, force=True)
            log(f"  Removed image: {image}")
            return True
    except DockerException:
        pass
    return False
