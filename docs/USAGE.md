# Usage Guide

## Running Benchmarks

Each workload directory has its own Makefile with a `benchmarks` target. Navigate to the workload directory and run `make benchmarks`:

```bash
# Example: Edge AI Pipelines
cd workloads/edge-ai-pipelines
make benchmarks
```

Run `make help` inside any workload directory for workload-specific options. Common options include:

| Option | Description | Default |
|--------|-------------|--------|
| `DRY_RUN` | List all benchmark configurations without running | `False` |
| `RESUME` | Skip tests that already have results | `False` |
| `DURATION` | Duration for each benchmark test (seconds) | `60`–`120` |
| `POWER` | Enable power/efficiency metrics (requires sudo) | `True` |
| `WALL_POWER` | Enable PDU wall power measurement (configure in `utils/helper_functions.sh`) | `False` |
| `CORES` | CPU core pinning: `pcore`, `ecore`, or range (e.g., `0-11`) | all cores |

## Examples

```bash
# Setup and download collateral
make prereqs
make collateral INCLUDE_GENAI=True

# Run benchmarks from a workload directory
cd workloads/edge-ai-pipelines && make benchmarks DURATION=120 CORES=ecore
cd workloads/vision-benchmarks && make benchmarks DRY_RUN=True  # Preview coverage matrix

# View results
make status                                       # Check results inventory
make report                                       # Generate HTML dashboard
make serve                                        # Start local dashboard server
```

## Full Makefile Variable List

#### make prereqs
- `INCLUDE_GPU` — Install GPU drivers during setup (default: `True`)
- `INCLUDE_NPU` — Install NPU drivers during setup (default: `True`, may require reboot)

#### make collateral
- `INCLUDE_VISION` — Download vision models during collateral setup (default: `True`)
- `INCLUDE_MEDIA` — Download media files during collateral setup (default: `True`)
- `INCLUDE_GENAI` — Download GenAI models during collateral setup (default: `False`)

#### make report
- `REPORT_NAME` — Custom filename for bundled HTML report (default: `report`)

#### make serve
- `PORT` — HTTP server port for dashboard (default: `8000`)
- `HOSTIP` — HTTP server IP binding for dashboard (default: `127.0.0.1`)

#### make clean-results
- `WORKLOAD` — Scope `clean-results` to specific workloads: `vision`, `media`, `genai`, `pipeline` (comma-separated)