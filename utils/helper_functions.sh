#!/bin/bash

# SPDX-FileCopyrightText: (C) 2024 - 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# Parses core pinning input and returns a valid core list or NO_PIN
parse_core_pinning() {
    local input="$1"
    local script_dir
    script_dir="$(dirname "${BASH_SOURCE[0]}")"
    local obtain_cores_script="${script_dir}/obtain_cores.sh"
    
    if [[ "${input}" == "none" || "${input}" == "nopin" ]]; then
        echo "NO_PIN"
        return 0
    fi
    
    if [[ "${input}" =~ ^[0-9,\-]+$ ]]; then
        echo "${input}"
        return 0
    fi

    local core_type=""
    case "${input,,}" in
        pcore|p-core|pcores|p-cores)
            core_type="pcore"
            ;;
        ecore|e-core|ecores|e-cores)
            core_type="ecore"
            ;;
        lpecore|lpe-core|lpecores|lpe-cores)
            core_type="lpecore"
            ;;
        *)
            echo "[ Warning ] Unknown core pinning format: '${input}'. Using NO_PIN." >&2
            echo "NO_PIN"
            return 0
            ;;
    esac
    
    if [[ ! -x "${obtain_cores_script}" ]]; then
        echo "[ Warning ] ${obtain_cores_script} not found or not executable. Using NO_PIN." >&2
        echo "NO_PIN"
        return 0
    fi
    
    local core_output
    core_output=$("${obtain_cores_script}" 2>/dev/null)
    
    if [[ $? -ne 0 || -z "${core_output}" ]]; then
        echo "[ Warning ] Failed to detect core types. Using NO_PIN." >&2
        echo "NO_PIN"
        return 0
    fi
    
    local core_list=""
    while IFS= read -r line; do
        if [[ "${line}" =~ ^${core_type}:(.+)$ ]]; then
            core_list="${BASH_REMATCH[1]}"
            break
        fi
    done <<< "${core_output}"
    
    if [[ -z "${core_list}" ]]; then
        echo "[ Warning ] Core type '${core_type}' not available on this system. Using NO_PIN." >&2
        echo "NO_PIN"
        return 0
    fi
    
    echo "${core_list}"
    return 0
}

# Fix file ownership when running under sudo so non-root user can access results.
fix_sudo_permissions() {
    local target_dir="$1"
    if [[ -n "${SUDO_USER:-}" && -d "${target_dir}" ]]; then
        chown -R "${SUDO_USER}:${SUDO_GID:-$(id -g "${SUDO_USER}")}" "${target_dir}"
    fi
}

# Power Monitoring
POWER_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Wall (socket) power configuration
# ---------------------------------------------------------------------------
# Wall power is measured from a PDU outlet over SSH using get_socket_power.py.
# To enable it, set WALL_POWER=True and populate the connection parameters
# below (or export them in the environment). When WALL_POWER is enabled but any
# required parameter is empty, the workload refuses to start.
#
# NOTE: Benchmarks often run under sudo (POWER=True), and sudo strips exported
# shell variables. To make settings survive sudo, put them in a local env file
# named "wall_power.env" next to this script (it is sourced below and ignored by
# git). Example wall_power.env:
#     WALL_POWER=True
#     SOCKET_POWER_IP=10.106.147.131
#     SOCKET_POWER_USERNAME=support
#     SOCKET_POWER_PASSWORD='User1234'
#     SOCKET_POWER_OUTLET=1
if [[ -f "${POWER_SCRIPT_DIR}/wall_power.env" ]]; then
    # shellcheck disable=SC1090,SC1091
    source "${POWER_SCRIPT_DIR}/wall_power.env"
fi

WALL_POWER="${WALL_POWER:-False}"
SOCKET_POWER_IP="${SOCKET_POWER_IP:-}"
SOCKET_POWER_PORT="${SOCKET_POWER_PORT:-22}"
SOCKET_POWER_USERNAME="${SOCKET_POWER_USERNAME:-}"
SOCKET_POWER_PASSWORD="${SOCKET_POWER_PASSWORD:-}"
SOCKET_POWER_OUTLET="${SOCKET_POWER_OUTLET:-7}"

# Interpreter used to run get_socket_power.py. Resolved once when this file is
# sourced (before any workload venv is activated) so wall power always uses the
# system python3 where paramiko is installed. Override via WALL_POWER_PYTHON.
WALL_POWER_PYTHON="${WALL_POWER_PYTHON:-$(command -v python3 2>/dev/null || echo python3)}"

# Returns success when wall power measurement is enabled.
wall_power_enabled() {
    case "${WALL_POWER,,}" in
        true|yes|1|on) return 0 ;;
        *) return 1 ;;
    esac
}

# Validate wall power configuration before a workload starts. When WALL_POWER is
# enabled, all required PDU connection parameters must be provided; otherwise the
# workload must not start.
wall_power_validate() {
    wall_power_enabled || return 0

    local missing=()
    [[ -z "${SOCKET_POWER_IP}" ]] && missing+=("SOCKET_POWER_IP")
    [[ -z "${SOCKET_POWER_USERNAME}" ]] && missing+=("SOCKET_POWER_USERNAME")
    [[ -z "${SOCKET_POWER_PASSWORD}" ]] && missing+=("SOCKET_POWER_PASSWORD")
    [[ -z "${SOCKET_POWER_PORT}" ]] && missing+=("SOCKET_POWER_PORT")
    [[ -z "${SOCKET_POWER_OUTLET}" ]] && missing+=("SOCKET_POWER_OUTLET")

    if (( ${#missing[@]} > 0 )); then
        echo "[ Error ] WALL_POWER is enabled but required parameter(s) are empty: ${missing[*]}" >&2
        echo "[ Error ] Set them in utils/helper_functions.sh (or the environment) and retry." >&2
        exit 1
    fi

    if [[ ! -f "${POWER_SCRIPT_DIR}/get_socket_power.py" ]]; then
        echo "[ Error ] Wall power script not found: ${POWER_SCRIPT_DIR}/get_socket_power.py" >&2
        exit 1
    fi

    if ! command -v "${WALL_POWER_PYTHON}" >/dev/null 2>&1; then
        echo "[ Error ] python3 ('${WALL_POWER_PYTHON}') is required for wall power measurement but was not found." >&2
        exit 1
    fi

    if ! "${WALL_POWER_PYTHON}" -c "import paramiko" >/dev/null 2>&1; then
        echo "[ Error ] Python module 'paramiko' is required for wall power measurement." >&2
        echo "[ Error ] Install it with: sudo apt-get install -y python3-paramiko  (or: ${WALL_POWER_PYTHON} -m pip install paramiko)" >&2
        exit 1
    fi
}

power_init() {
    local results_dir="$1"
    local filename="$2"
    local duration="$3"

    PowerPID=""
    PowerLogFile="${results_dir}/${filename}_power.log"
    PowerDelay=$(bc <<< "scale=0; ${duration} / 4")
    PowerDuration=$(bc <<< "scale=0; ${duration} / 2")
    AvgPower="NA"

    # Wall (socket) power state
    SocketPowerPID=""
    SocketPowerLogFile="${results_dir}/${filename}_wall_power.csv"
    AvgWallPower="NA"

    # Fail fast (before the workload starts) if wall power is misconfigured.
    wall_power_validate
}

power_start() {
    local duration="$1"

    if [[ -x "${POWER_SCRIPT_DIR}/get_package_power.sh" ]]; then
        timeout --preserve-status "${duration}" "${POWER_SCRIPT_DIR}/get_package_power.sh" \
            -s 1 -i "${PowerDuration}" -d "${PowerDelay}" > "${PowerLogFile}" 2>&1 &
        PowerPID=$!
        sleep 0.5
        if kill -0 "${PowerPID}" 2>/dev/null; then
            echo "[ Info ] Power monitoring started (PID: ${PowerPID})"
        else
            wait "${PowerPID}" 2>/dev/null || true
            PowerPID=""
        fi
    fi

    if wall_power_enabled; then
        # Align the wall power window with the package power window: start after
        # PowerDelay and sample for PowerDuration (the middle of the run).
        (
            sleep "${PowerDelay}"
            "${WALL_POWER_PYTHON}" "${POWER_SCRIPT_DIR}/get_socket_power.py" \
                --ip "${SOCKET_POWER_IP}" \
                --port "${SOCKET_POWER_PORT}" \
                --username "${SOCKET_POWER_USERNAME}" \
                --password "${SOCKET_POWER_PASSWORD}" \
                --outlet "${SOCKET_POWER_OUTLET}" \
                --duration "${PowerDuration}" \
                --interval 1 \
                --output "${SocketPowerLogFile}"
        ) > "${SocketPowerLogFile%.csv}.log" 2>&1 &
        SocketPowerPID=$!
        sleep 0.5
        if kill -0 "${SocketPowerPID}" 2>/dev/null; then
            echo "[ Info ] Wall power monitoring started (PID: ${SocketPowerPID})"
        else
            wait "${SocketPowerPID}" 2>/dev/null || true
            SocketPowerPID=""
        fi
    fi
}

power_stop() {
    if [[ -n "${PowerPID:-}" ]]; then
        kill "${PowerPID}" 2>/dev/null || true
        wait "${PowerPID}" 2>/dev/null || true
        PowerPID=""
    fi
    if [[ -n "${SocketPowerPID:-}" ]]; then
        kill "${SocketPowerPID}" 2>/dev/null || true
        pkill -P "${SocketPowerPID}" 2>/dev/null || true
        wait "${SocketPowerPID}" 2>/dev/null || true
        SocketPowerPID=""
    fi
}

power_collect() {
    AvgPower="NA"
    if [[ -f "${PowerLogFile}" ]] && grep -q "W$" "${PowerLogFile}" 2>/dev/null; then
        AvgPower=$(grep -oP '\d+\.\d+(?= W)' "${PowerLogFile}" | \
            awk '{sum+=$1; count++} END {if(count>0) printf "%.2f", sum/count; else print "NA"}')
    fi

    AvgWallPower="NA"
    if [[ -f "${SocketPowerLogFile:-}" ]]; then
        AvgWallPower=$(awk -F',' \
            'NR>1 && $2 ~ /^[0-9]+(\.[0-9]+)?$/ {sum+=$2; count++} END {if(count>0) printf "%.2f", sum/count; else print "NA"}' \
            "${SocketPowerLogFile}")
        [[ -n "${AvgWallPower}" ]] || AvgWallPower="NA"
    fi
}
