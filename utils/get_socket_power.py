import argparse
import csv
import paramiko
import re
import time
from datetime import datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description="Measure active power from a PDU sensor over SSH."
    )
    parser.add_argument("--ip", required=True, help="PDU IP address")
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="SSH port (default: 22)",
    )
    parser.add_argument("--username", required=True, help="SSH username")
    parser.add_argument("--password", required=True, help="SSH password")
    parser.add_argument(
        "--outlet",
        type=int,
        default=7,
        help="Outlet number to measure (default: 7)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Total measurement duration in seconds (0 = collect until interrupted)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5,
        help="Interval between measurements in seconds (default: 5)",
    )
    parser.add_argument(
        "--output",
        default="power_log.csv",
        help="Output CSV file (default: power_log.csv)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh.connect(
        args.ip,
        port=args.port,
        username=args.username,
        password=args.password,
    )

    shell = ssh.invoke_shell()

    time.sleep(2)
    shell.recv(65535)

    start_time = time.time()

    print(
        f"Measuring power from {args.ip} outlet {args.outlet} every {args.interval}s"
        + (f" for {args.duration}s" if args.duration else " (until interrupted with Ctrl+C)")
    )
    print(f"Logging to {args.output}\n")

    command = f"show sensor outlet {args.outlet} activePower\n"

    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "power_w"])

        try:
            while True:
                shell.send(command)

                time.sleep(1)

                output = shell.recv(65535).decode()

                match = re.search(
                    r"Reading:\s*(\d+(?:\.\d+)?)\s*W",
                    output
                )

                timestamp = datetime.now()

                if match:
                    watts = float(match.group(1))

                    writer.writerow([
                        timestamp.isoformat(),
                        watts
                    ])

                    f.flush()

                    elapsed = time.time() - start_time
                    print(f"[{timestamp.strftime('%H:%M:%S')}] {watts} W  (elapsed {elapsed:.0f}s)")
                else:
                    print(f"[{timestamp.strftime('%H:%M:%S')}] no reading")

                if args.duration and (time.time() - start_time) >= args.duration:
                    break

                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped by user.")

    ssh.close()


if __name__ == "__main__":
    main()
