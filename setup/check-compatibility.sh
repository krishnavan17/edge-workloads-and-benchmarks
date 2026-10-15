#!/bin/bash

# SPDX-FileCopyrightText: (C) 2024 - 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# Edge Workloads and Benchmarks System Compatibility Check
# Quick validation of system requirements before installation
# ==============================================================================

# Status prefixes (colored when stdout is a terminal)
if [ -t 1 ]; then
    _G="\033[0;32m"; _R="\033[0;31m"; _Y="\033[0;33m"; _B="\033[0;34m"; _N="\033[0m"
else
    _G=""; _R=""; _Y=""; _B=""; _N=""
fi
print_pass() { echo -e "${_G}[ Pass ]${_N} $1"; }
print_fail() { echo -e "${_R}[ Fail ]${_N} $1"; }
print_warn() { echo -e "${_Y}[ Warn ]${_N} $1"; }
print_info() { echo -e "${_B}[ Info ]${_N} $1"; }

WARNINGS=0
ERRORS=0

# ── OS ────────────────────────────────────────────────────────────────────────
KERNEL_VER=$(uname -r)
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" == "ubuntu" ]]; then
        if [[ "$VERSION_ID" == "22.04" || "$VERSION_ID" == "24.04" || "$VERSION_ID" == "26.04" ]]; then
            print_pass "OS:         Ubuntu $VERSION_ID, Kernel $KERNEL_VER"
        else
            print_warn "OS:         Ubuntu $VERSION_ID, Kernel $KERNEL_VER (recommended: 22.04, 24.04 or 26.04)"
            WARNINGS=$((WARNINGS + 1))
        fi
    else
        print_warn "OS:         $NAME $VERSION_ID, Kernel $KERNEL_VER (non-Ubuntu)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    print_fail "OS:         cannot detect"
    ERRORS=$((ERRORS + 1))
fi

# ── Docker ────────────────────────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1; then
    DOCKER_VERSION=$(docker --version 2>/dev/null | cut -d' ' -f3 | tr -d ',')
    if docker run --rm hello-world >/dev/null 2>&1; then
        print_pass "Docker:     $DOCKER_VERSION (functional)"
    else
        print_fail "Docker:     $DOCKER_VERSION (cannot run containers — try: sudo usermod -aG docker \$USER)"
        ERRORS=$((ERRORS + 1))
    fi
else
    print_fail "Docker:     not installed"
    ERRORS=$((ERRORS + 1))
fi

# ── GPU / OpenCL ──────────────────────────────────────────────────────────────
if command -v clinfo >/dev/null 2>&1; then
    GPU_VERSION=$(clinfo 2>/dev/null | grep -m1 "Driver Version" | awk '{print $3}' || echo "")
    if [ -n "$GPU_VERSION" ]; then
        COMPUTE_DEVICES=$(clinfo 2>/dev/null | grep -c "Device Type.*GPU" || echo "0")
        [ "$COMPUTE_DEVICES" -eq 0 ] && COMPUTE_DEVICES=$(find /dev/dri -name "render*" -type c 2>/dev/null | wc -l)
        print_pass "GPU:        Driver Version $GPU_VERSION ($COMPUTE_DEVICES compute device(s))"
    else
        print_warn "GPU:        clinfo present but no devices found"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    print_warn "GPU:        clinfo not installed (sudo apt install clinfo)"
    WARNINGS=$((WARNINGS + 1))
fi

# ── NPU ───────────────────────────────────────────────────────────────────────
if ls /dev/accel/accel* >/dev/null 2>&1; then
    NPU_DEVICES=$(find /dev/accel -name "accel*" -type c 2>/dev/null | wc -l)
    if dpkg -l | grep -q "intel-driver-compiler-npu"; then
        NPU_VERSION=$(dpkg -l | grep intel-driver-compiler-npu | awk '{print $3}' | cut -d. -f1-3)
        print_pass "NPU:        Driver Version $NPU_VERSION ($NPU_DEVICES compute device(s))"
    else
        print_warn "NPU:        $NPU_DEVICES device(s), driver not installed"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    print_info "NPU: not detected (optional)"
fi

# ── VA-API ────────────────────────────────────────────────────────────────────
if command -v vainfo >/dev/null 2>&1; then
    VAAPI_OUTPUT=$(vainfo 2>&1)
    if echo "$VAAPI_OUTPUT" | grep -q "VAProfileH264"; then
        VAAPI_VERSION=$(echo "$VAAPI_OUTPUT" | grep "libva info: VA-API version" | awk '{print $NF}')
        VAAPI_PROFILES=$(echo "$VAAPI_OUTPUT" | grep -c "VAProfile" || echo "0")
        print_pass "VA-API:     Driver Version $VAAPI_VERSION ($VAAPI_PROFILES profiles detected)"
    else
        print_warn "VA-API:     vainfo present but may not be functional"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    print_warn "VA-API:     vainfo not installed (sudo apt install vainfo)"
    WARNINGS=$((WARNINGS + 1))
fi

# ── System Resources ──────────────────────────────────────────────────────────
TOTAL_RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
AVAILABLE_SPACE=$(df -h . | tail -n1 | awk '{print $4}')
AVAILABLE_SPACE_NUM=$(echo "$AVAILABLE_SPACE" | grep -oP '^\d+' || echo "0")
AVAILABLE_SPACE_UNIT=$(echo "$AVAILABLE_SPACE" | grep -oP '[A-Z]+$' || echo "")

ram_ok=true; disk_ok=true
[ "$TOTAL_RAM_GB" -lt 8 ] 2>/dev/null && ram_ok=false
if [ "$AVAILABLE_SPACE_UNIT" = "G" ] && [ "$AVAILABLE_SPACE_NUM" -lt 11 ]; then disk_ok=false; fi

if $ram_ok && $disk_ok; then
    print_pass "Resources:  ${TOTAL_RAM_GB}GB RAM, ${AVAILABLE_SPACE} disk"
else
    if ! $ram_ok; then
        print_warn "RAM: ${TOTAL_RAM_GB}GB (8GB+ recommended)"
        WARNINGS=$((WARNINGS + 1))
    fi
    if ! $disk_ok; then
        print_warn "Disk: ${AVAILABLE_SPACE} (11GB+ recommended)"
        WARNINGS=$((WARNINGS + 1))
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo ""
    print_warn "Completed with $WARNINGS warning(s) — some features may be limited."
    exit 0
else
    echo ""
    print_fail "Failed with $ERRORS error(s) and $WARNINGS warning(s) — resolve before proceeding."
    exit 1
fi
