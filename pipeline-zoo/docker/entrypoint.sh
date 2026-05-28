#!/bin/bash
# Model download container entrypoint — keeps the container alive for docker exec.
set -e

# Ensure files written by this container are readable by pipeline-server (UID 1999)
umask 0022

echo "=== Model-download container ==="
echo "Date: $(date -u)"
echo "Python: $(python3 --version)"
echo "OpenVINO: $(python3 -c 'import openvino; print(openvino.__version__)' 2>&1 || echo 'NOT FOUND')"
echo "Ultralytics: $(python3 -c 'import ultralytics; print(ultralytics.__version__)' 2>&1 || echo 'NOT FOUND')"
echo "Proxy: http=${http_proxy:-unset} https=${https_proxy:-unset}"
echo "Output dir: $(find /output/ -maxdepth 1 -printf '%m %u %g %p\n' 2>/dev/null | head -5 || echo '/output not mounted')"
echo "================================="

# Keep container running so pipeline-zoo.py can exec scripts into it
exec tail -f /dev/null
