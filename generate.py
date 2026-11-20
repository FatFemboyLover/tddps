"""Generate partitioned telemetry for six different assets."""
import argparse
import csv
import random
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from equipment import EQUIPMENT

PART_STEPS = 10_000
EPOCH_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
TABLES = ("ground_truth", "observations", "anomaly_labels")
OBSERVER_COUNT = sum(spec.observers for spec in EQUIPMENT)


def observer_fields(spec, rng):
    extra = list(range(3, len(spec.fields)))
    count = 3 if len(extra) == 5 else 4
    while True:
        groups = [tuple(sorted(rng.sample(extra, count))) for _ in range(spec.observers)]
        if len(set(groups)) == spec.observers and set().union(*groups) == set(extra):
            return [(0, 1, 2, *group) for group in groups]


def writer(stack, path, header):
    stream = stack.enter_context(path.open("x", encoding="utf-8", newline=""))
    table = csv.writer(stream, lineterminator="\n")
    table.writerow(header)
    return table


MACHINE_COLUMNS = (
    "machine_id", "name", "category", "drive_type", "cooling",
    "criticality", "active_fields",
)


def write_catalogs(root, specs, masks):
    with ExitStack() as stack:
        assets = writer(stack, root / "machines.csv", ("machine_id", "kind"))
        observers = writer(stack, root / "observers.csv",
                           ("observer_id", "machine_id", "observer_type", "observed_fields"))
        observer = 0
        for machine, (spec, groups) in enumerate(zip(EQUIPMENT, masks), 1):
            assets.writerow((machine, spec.kind))
            for local_id, fields in enumerate(groups, 1):
                observer += 1
                observers.writerow((observer, machine, f"{spec.kind}_{local_id}",
                                    "|".join(spec.fields[i] for i in fields)))


def write_partition(root, part, start, count, specs, masks, rng):
    suffix = f"part-{part:05d}.csv"
    paths = []
    anomalous = observer_offset = 0
    for machine, (spec, groups) in enumerate(zip(EQUIPMENT, masks), 1):
        truth_path, obs_path, labels_path = [root / table / spec.kind / suffix for table in TABLES]
        paths.extend((truth_path, obs_path, labels_path))
        with ExitStack() as stack:
            truth = writer(stack, truth_path, ("machine_id", "timestamp_ms", *spec.fields))
            obs = writer(stack, obs_path, ("observer_id", "timestamp_ms", *spec.fields))
            labels = writer(stack, labels_path, ("observer_id", "timestamp_ms", "field", "delta"))
            for step in range(start, start + count):
                timestamp = EPOCH_MS + 100 * step
                state = spec.state(step, machine)
                truth.writerow((machine, timestamp, *(f"{value:.4f}" for value in state)))
                for local_id, fields in enumerate(groups, 1):
                    observer = observer_offset + local_id
                    readings = [""] * len(spec.fields)
                    for field in fields:
                        readings[field] = f"{state[field] + rng.gauss(0, spec.noise[field]):.4f}"
                    if rng.random() < 0.07:
                        field = rng.choice(fields)
                        before = float(readings[field])
                        shift = rng.choice((-1, 1)) * rng.uniform(8, 16) * spec.noise[field]
                        after = round(before + shift, 4)
                        readings[field] = f"{after:.4f}"
                        labels.writerow((observer, timestamp, spec.fields[field],
                                         f"{after - before:.4f}"))
                        anomalous += 1
                    obs.writerow((observer, timestamp, *readings))
        observer_offset += spec.observers
    return sum(path.stat().st_size for path in paths), anomalous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--machines", type=int, default=len(MACHINE_TYPES),
                        help="number of machines; types are cycled")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--steps", type=int)
    mode.add_argument("--target-bytes", type=int)
    args = parser.parse_args()
    limit = args.steps if args.steps is not None else args.target_bytes
    if limit <= 0:
        parser.error("the requested limit must be positive")
    if args.machines <= 0:
        parser.error("--machines must be positive")
    if args.output.exists():
        parser.error("output directory already exists")
    args.output.mkdir(parents=True)
    for table in TABLES:
        for spec in EQUIPMENT:
            (args.output / table / spec.kind).mkdir(parents=True)
    configuration_rng = random.Random(args.seed)
    masks = [observer_fields(spec, configuration_rng) for spec in EQUIPMENT]
    rng = random.Random(args.seed + 1)
    write_catalogs(args.output, specs, masks)
    size = sum(path.stat().st_size for path in args.output.glob("*.csv"))
    step = part = anomalous = 0
    n_observers = args.machines * 3
    while True:
        count = PART_STEPS if args.steps is None else min(PART_STEPS, args.steps - step)
        part_size, part_anomalies = write_partition(
            args.output, part, step, count, specs, masks, rng
        )
        size += part_size
        anomalous += part_anomalies
        step += count
        part += 1
        print(f"partitions={part} bytes={size:,} observations={step * OBSERVER_COUNT:,} "
              f"anomalies={anomalous:,} ({anomalous / (step * OBSERVER_COUNT):.2%})", flush=True)
        if (args.steps is not None and step == args.steps
                or args.target_bytes is not None and size >= args.target_bytes):
            break


if __name__ == "__main__":
    main()