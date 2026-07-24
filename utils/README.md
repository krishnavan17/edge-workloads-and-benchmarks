# Utility Functions

Shared helper scripts used by benchmarks, Makefiles, and collateral tools throughout the repository.  
**Note:** These scripts are not intended to be used directly, but can function standalone. Please refer to the usage below.

## Obtain Cores
Lists cores by type (P-Core, E-Core, Low Power E-Core). Used for pinning CPU cores for scheduling workloads with taskset.
### Usage
```bash
./obtain_cores.sh
```
### Example output
```bash
pcore:0,1,2,3
ecore:4,5,6,7,8,9,10,11
lpecore:12,13,14,15
```

## Get Package Power
Samples platform package power consumption in Watts using RAPL sysfs.
### Usage
```bash
./get_package_power.sh [-s <sampling frequency (seconds)>] [-i <duration (seconds)>] [-d <delay (seconds)>]

# Example (measure for 60 seconds at a 1 second interval)
sudo ./get_package_power.sh -i 60
```
### Example output
```bash
[rapl] card1 (xe @ 0000:00:02.0): 1.72 W
```

## Get Socket Power (Wall Power)
Samples wall (socket) power in Watts from a PDU outlet over SSH. Benchmarks use
this as a secondary "Wall Power" metric alongside package power.

Configure the connection parameters in the *Wall (socket) power configuration*
section of [`helper_functions.sh`](helper_functions.sh) (or via the environment),
then enable it per workload with `make benchmarks WALL_POWER=True`. When
`WALL_POWER` is enabled but any required parameter
(`SOCKET_POWER_IP`, `SOCKET_POWER_USERNAME`, `SOCKET_POWER_PASSWORD`,
`SOCKET_POWER_PORT`, `SOCKET_POWER_OUTLET`) is empty, the workload refuses to
start. Requires the `paramiko` Python module (`pip install paramiko`).
### Usage
```bash
python3 ./get_socket_power.py --ip <pdu_ip> --username <user> --password <pass> \
    --outlet <n> --duration <seconds> --interval <seconds> --output <file.csv>
```
### Example output
```bash
[14:32:07] 212.0 W  (elapsed 5s)
```

## Check HF Token
Prompts for the user's HuggingFace token and saves as an environment variable for gated model access.
### Usage
```bash
./check_hf_token.sh
```
### Example output
```bash
hf_<rest_of_your_huggingface_token>
```

## Verify Collateral
Validates all required models and media files exist in the collateral directory.
### Usage
```bash
./verify_collateral.sh [--verbose] [--section vision|media|genai]
```
### Example Output
```bash
[ Pass ] Vision models: 13/13 files verified

[ Pass ] Media files: 8/8 files verified

[ Pass ] GenAI models: 12/12 models verified
```

## Show Status
Displays the current amount of completed benchmarks sorted by workload.
### Usage
```bash
./show_status.sh
```
### Example Output
```bash
================================================
  Benchmark Results Inventory
================================================
  edge-ai-pipelines: no results
  vision-benchmarks: no results
  media-benchmarks: no results
  genai-benchmarks: no results
================================================
  Total: 0 CSV result files
```