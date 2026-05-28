#!/usr/bin/env python3
# =============================================================================
# Video Download — Pipeline Zoo
#
# Standalone script for downloading, transcoding, and looping video assets.
# Runs inside a dlstreamer-pipeline-server container which provides
# GStreamer and VA-API hardware acceleration for H.265 transcoding.
#
# Usage (inside container):
#   python3 video_download.py \
#       --url "https://videos.pexels.com/..." \
#       --output-path "light/video/bears.h265" \
#       --loop-count 100
#
# Can process multiple videos via repeated flag groups:
#   python3 video_download.py \
#       --url URL1 --output-path PATH1 --loop-count 100 \
#       --url URL2 --output-path PATH2 --loop-count 100
# =============================================================================

import argparse
import shutil
import subprocess  # nosec B404 — only invokes hardcoded gst-launch-1.0
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

OUTPUT_DIR = Path("/output")
CACHE_DIR = Path("/cache")

_ALLOWED_URL_SCHEMES = ("https",)


def _validate_url(url):
    """Reject URLs with unexpected schemes (only https allowed)."""
    scheme = urlparse(url).scheme
    if scheme not in _ALLOWED_URL_SCHEMES:
        raise ValueError(
            f"Unsupported URL scheme '{scheme}' in: {url}\n"
            f"  Allowed: {', '.join(_ALLOWED_URL_SCHEMES)}")


def download_file(url, dest):
    """Download a file from URL with progress."""
    _validate_url(url)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {dest.name}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=300)  # nosec B310 — scheme validated by _validate_url()
    with open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def transcode_to_h265(mp4_path, h265_path):
    """Transcode MP4 to H.265 via GStreamer VA-API."""
    print(f"  Transcoding {mp4_path.name} -> {h265_path.name} (VA-API)...")
    mp4_resolved = str(Path(mp4_path).resolve())
    h265_resolved = str(Path(h265_path).resolve())
    gst_cmd = [
        "gst-launch-1.0",
        "filesrc", f"location={mp4_resolved}", "!",
        "decodebin3", "!",
        "videorate", "!", "video/x-raw,framerate=30/1", "!",
        "vapostproc", "!",
        "capsfilter",
        "caps=video/x-raw(memory:VAMemory),pixel-aspect-ratio=1/1,"
        "width=1920,height=1080,framerate=30/1", "!",
        "vah265enc", "bitrate=2000", "b-frames=0", "key-int-max=60", "!",
        "h265parse", "!",
        "filesink", f"location={h265_resolved}",
    ]
    result = subprocess.run(  # nosec B603 — hardcoded gst-launch-1.0, paths resolved
        gst_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Transcode failed:\n{result.stderr}")


def create_looped(h265_path, dst, loop_count):
    """Create looped H.265 file by concatenating raw bitstream."""
    print(f"  Creating {loop_count}x loop -> {dst.name}...")
    dst.parent.mkdir(parents=True, exist_ok=True)
    chunk = h265_path.read_bytes()
    with open(dst, "wb") as out:
        for _ in range(loop_count):
            out.write(chunk)


def process_video(url, output_path, loop_count):
    """Download MP4, transcode to H.265 (VA-API), loop, install."""
    video_cache = CACHE_DIR / "video"
    video_cache.mkdir(parents=True, exist_ok=True)

    url_basename = Path(url.split("?")[0]).stem
    mp4_path = video_cache / f"{url_basename}.mp4"
    h265_path = video_cache / f"{url_basename}.h265"

    # Step 1: Download MP4
    if not mp4_path.is_file():
        download_file(url, mp4_path)
    else:
        print(f"  Using cached {mp4_path.name}")

    # Step 2: Transcode to H.265 via VA-API
    if not h265_path.is_file():
        transcode_to_h265(mp4_path, h265_path)
    else:
        print(f"  Using cached {h265_path.name}")

    # Step 3: Create looped file at output path
    dst = OUTPUT_DIR / output_path
    if not dst.is_file():
        create_looped(h265_path, dst, loop_count)
    else:
        print(f"  Output already exists: {output_path}")

    print(f"  Video ready: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Download, transcode, and loop video assets")
    parser.add_argument("--url", action="append", required=True,
                        help="Video URL to download (repeatable)")
    parser.add_argument("--output-path", action="append", required=True,
                        help="Output path relative to /output/ (repeatable)")
    parser.add_argument("--loop-count", action="append", type=int,
                        help="Loop count per video (default: 100)")
    args = parser.parse_args()

    if len(args.url) != len(args.output_path):
        print("Error: --url and --output-path must have the same count",
              file=sys.stderr)
        sys.exit(1)

    loop_counts = args.loop_count or []
    while len(loop_counts) < len(args.url):
        loop_counts.append(100)

    failed = []
    for url, output_path, loop_count in zip(
            args.url, args.output_path, loop_counts):
        try:
            print(f"\nProcessing: {output_path}")
            process_video(url, output_path, loop_count)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            failed.append(output_path)

    if failed:
        print(f"\n{len(failed)} video(s) failed:", file=sys.stderr)
        for f in failed:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    print(f"\nAll {len(args.url)} video(s) ready.")


if __name__ == "__main__":
    main()
