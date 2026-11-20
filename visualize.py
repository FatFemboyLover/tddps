"""Визуализация датасета телеметрии с категориальными признаками.

Примеры:
    python visualize.py data-100k --output plots-100k --partitions 2 --stride 5 \
        --field current_a --field power_kw --predictions predictions-100k.csv
"""
import argparse
import csv
import statistics
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIELDS = (
    "speed_rpm", "load_pct", "motor_temp_c", "current_a", "voltage_v",
    "power_kw", "case_temp_c", "vibration_x_mm_s", "vibration_y_mm_s",
    "vibration_z_mm_s",
)
COMMON = FIELDS[:3]
SIGMA = dict(zip(FIELDS, (3, 0.25, 0.12, 0.04, 0.25, 0.025, 0.10, 0.012, 0.012, 0.012)))
UNITS = {
    "speed_rpm": "об/мин", "load_pct": "%", "motor_temp_c": "°C",
    "current_a": "А", "voltage_v": "В", "power_kw": "кВт",
    "case_temp_c": "°C", "vibration_x_mm_s": "мм/с",
    "vibration_y_mm_s": "мм/с", "vibration_z_mm_s": "мм/с",
}
DEFAULT_FIELDS = ("speed_rpm", "load_pct", "motor_temp_c", "current_a")
THRESHOLD = 5.0
THIN = 4000


# --------------------------------------------------------------- чтение CSV
def read_rows(path):
    with path.open(encoding="utf-8", newline="") as file:
        yield from csv.DictReader(file)


def load_catalogs(dataset):
    machines = {}
    for r in read_rows(dataset / "machines.csv"):
        mid = int(r["machine_id"])
        machines[mid] = {
            "name": r["name"],
            "category": r["category"],
            "drive_type": r["drive_type"],
            "cooling": r["cooling"],
            "criticality": r["criticality"],
            "active_fields": r["active_fields"].split("|"),
        }
    observers = {}
    for r in read_rows(dataset / "observers.csv"):
        oid = int(r["observer_id"])
        observers[oid] = (int(r["machine_id"]), r["observed_fields"].split("|"))
    return machines, observers


def partition_paths(dataset):
    return sorted((dataset / "observations").glob("part-*.csv"),
                  key=lambda p: int(p.stem.split("-")[1]))


def thin(xs, ys, limit=THIN):
    if len(xs) <= limit:
        return xs, ys
    step = len(xs) // limit + 1
    return xs[::step], ys[::step]


# ------------------------------------------------------------- сбор данных
def collect(dataset, observers, wanted_machines, parts, stride):
    truth = defaultdict(lambda: defaultdict(list))
    obs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    labels = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for part in parts:
        kept_ts = set()
        idx = -1
        for ts_text, rows in groupby(read_rows(dataset / "ground_truth" / part.name),
                                     key=lambda r: r["timestamp_ms"]):
            idx += 1
            if idx % stride:
                continue
            ts = int(ts_text)
            for row in rows:
                m = int(row["machine_id"])
                if m not in wanted_machines:
                    continue
                kept_ts.add(ts)
                for f in FIELDS:
                    truth[m][f].append((ts, float(row[f])))
                if row.get("status"):
                    truth[m]["status"].append((ts, row["status"]))
        idx = -1
        for ts_text, rows in groupby(read_rows(dataset / "observations" / part.name),
                                     key=lambda r: r["timestamp_ms"]):
            idx += 1
            if idx % stride:
                continue
            ts = int(ts_text)
            if ts not in kept_ts:
                continue
            for row in rows:
                oid = int(row["observer_id"])
                m = observers[oid][0]
                if m not in wanted_machines:
                    continue
                for f in FIELDS:
                    v = row[f]
                    if v:
                        obs[m][f][oid].append((ts, float(v)))
        label_path = dataset / "anomaly_labels" / part.name
        if label_path.is_file():
            for row in read_rows(label_path):
                ts = int(row["timestamp_ms"])
                if ts not in kept_ts:
                    continue
                oid = int(row["observer_id"])
                m = observers[oid][0]
                if m not in wanted_machines:
                    continue
                labels[m][row["field"]][oid].append((ts, float(row["delta"])))
    return truth, obs, labels


def count_labels(dataset, parts):
    counts = Counter()
    for part in parts:
        lp = dataset / "anomaly_labels" / part.name
        if not lp.is_file():
            continue
        for r in read_rows(lp):
            counts[(int(r["observer_id"]), r["field"])] += 1
    return counts


def load_predictions(path):
    return [(int(r["observer_id"]), int(r["timestamp_ms"]), r["field"],
             float(r["score"]), r["method"]) for r in read_rows(path)]


def load_labels(dataset, parts):
    out = set()
    for part in parts:
        lp = dataset / "anomaly_labels" / part.name
        if not lp.is_file():
            continue
        for r in read_rows(lp):
            out.add((int(r["observer_id"]), int(r["timestamp_ms"]), r["field"]))
    return out


# --------------------------------------------------------------- графики
def _status_spans(status_ts):
    """Разбить [(ts, status)] на интервалы одного статуса."""
    if not status_ts:
        return []
    spans, start, cur = [], status_ts[0][0], status_ts[0][1]
    for ts, s in status_ts[1:]:
        if s != cur:
            spans.append((start, ts, cur))
            start, cur = ts, s
    spans.append((start, status_ts[-1][0], cur))
    return spans


def plot_field(machine, info, field, truth_m, obs_m, labels_m, observers, path):
    pts_truth = truth_m.get(field, [])
    if not pts_truth:
        return
    t = [p[0] for p in pts_truth]
    v = [p[1] for p in pts_truth]
    truth_map = dict(pts_truth)
    sigma = SIGMA[field]

    fig, (ax_raw, ax_res) = plt.subplots(
        2, 1, figsize=(15, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 2]},
    )
    # затенение по status
    status_ts = truth_m.get("status", [])
    if status_ts:
        labels_order = sorted({s for _, s in status_ts})
        pos = {s: i for i, s in enumerate(labels_order)}
        cmap_s = plt.cm.tab10
        for lo, hi, s in _status_spans(status_ts):
            color = cmap_s(pos[s] % 10)
            ax_raw.axvspan(lo, hi, color=color, alpha=0.07)
            ax_res.axvspan(lo, hi, color=color, alpha=0.07)

    ax_raw.plot(t, v, color="black", lw=1.0, label="эталон")
    cmap = plt.cm.tab10
    for i, oid in enumerate(sorted(obs_m.get(field, {}))):
        pts = obs_m[field][oid]
        if not pts:
            continue
        color = cmap(i % 10)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        sx, sy = thin(xs, ys)
        n_obs = len(observers[oid][1])
        ax_raw.scatter(sx, sy, s=8, color=color, alpha=0.8,
                       label=f"obs {oid} ({n_obs} полей)")

        rx = [p[0] for p in pts if p[0] in truth_map]
        ry = [p[1] - truth_map[p[0]] for p in pts if p[0] in truth_map]
        rx, ry = thin(rx, ry)
        ax_res.plot(rx, ry, color=color, lw=0.7, alpha=0.9)

        obs_map = dict(pts)
        at, ar = [], []
        for ts, _ in labels_m.get(oid, []):
            if ts in truth_map and ts in obs_map:
                at.append(ts)
                ar.append(obs_map[ts] - truth_map[ts])
        if at:
            ax_res.scatter(at, ar, s=70, marker="x", color="red",
                           linewidths=2, zorder=6,
                           label="разметка" if i == 0 else None)

    ax_res.axhline(THRESHOLD * sigma, color="red", ls="--", lw=0.8, alpha=0.6)
    ax_res.axhline(-THRESHOLD * sigma, color="red", ls="--", lw=0.8, alpha=0.6)
    ax_raw.set_ylabel(f"{field}, {UNITS.get(field, '')}")
    ax_res.set_ylabel("остаток (набл. − эталон)")
    ax_res.set_xlabel("timestamp_ms")
    ax_raw.set_title(
        f"{info['name']}  [{info['category']} · {info['drive_type']} · "
        f"{info['cooling']} · {info['criticality']}]: {field}"
    )
    ax_raw.legend(loc="upper right", fontsize=7, ncol=3)
    ax_res.legend(loc="upper right", fontsize=7)
    ax_raw.grid(alpha=0.3)
    ax_res.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_status_timeline(machine, info, truth_m, path):
    status_ts = truth_m.get("status", [])
    if not status_ts:
        return
    labels = sorted({s for _, s in status_ts})
    pos = {s: i for i, s in enumerate(labels)}
    t = [p[0] for p in status_ts]
    v = [pos[s] for _, s in status_ts]
    fig, ax = plt.subplots(figsize=(15, 2.5))
    ax.fill_between(t, v, step="post", alpha=0.6, color="steelblue")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("timestamp_ms")
    ax.set_title(f"{info['name']} — status ({info['category']}, {info['criticality']})")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_status_distribution(truth, machines, path):
    labels_all = set()
    for t in truth.values():
        for _, s in t.get("status", []):
            labels_all.add(s)
    if not labels_all:
        return
    labels = sorted(labels_all)
    rows = sorted(truth)
    matrix = []
    for m in rows:
        counts = Counter(s for _, s in truth[m].get("status", []))
        total = sum(counts.values()) or 1
        matrix.append([counts.get(s, 0) / total for s in labels])
    matrix = np.array(matrix)
    fig, ax = plt.subplots(figsize=(12, 4))
    left = np.zeros(len(rows))
    cmap = plt.cm.tab10
    for j, s in enumerate(labels):
        ax.barh([machines[m]["name"] for m in rows], matrix[:, j],
                left=left, color=cmap(j % 10), label=s)
        left += matrix[:, j]
    ax.set_xlabel("доля времени")
    ax.set_title("Распределение status по машинам")
    ax.legend(loc="lower right", fontsize=8, ncol=2)
    ax.invert_yaxis()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_active_fields(machines, path):
    rows = sorted(machines)
    fields = list(FIELDS)
    matrix = np.zeros((len(rows), len(fields)))
    for i, m in enumerate(rows):
        active = set(machines[m]["active_fields"]) | set(COMMON)
        for j, f in enumerate(fields):
            matrix[i, j] = 1 if f in active else 0
    fig, ax = plt.subplots(figsize=(12, 3.5))
    im = ax.imshow(matrix, aspect="auto", cmap="Greens", vmin=0, vmax=1)
    ax.set_xticks(range(len(fields)))
    ax.set_xticklabels(fields, rotation=25, ha="right", fontsize=8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([machines[m]["name"] for m in rows], fontsize=8)
    for i in range(len(rows)):
        for j in range(len(fields)):
            if matrix[i, j]:
                ax.text(j, i, "✓", ha="center", va="center",
                        fontsize=9, color="darkgreen")
    ax.set_title("Активные поля по типам (✓ — снимает хотя бы один наблюдатель)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_category_card(machines, path):
    rows = sorted(machines)
    headers = ["id", "name", "category", "drive_type", "cooling", "criticality", "active_fields"]
    data = [headers]
    for m in rows:
        info = machines[m]
        data.append([str(m), info["name"], info["category"], info["drive_type"],
                     info["cooling"], info["criticality"],
                     str(len(info["active_fields"]))])
    fig, ax = plt.subplots(figsize=(12, 0.5 * len(rows) + 1.2))
    ax.axis("off")
    table = ax.table(cellText=data[1:], colLabels=headers,
                     loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)
    ax.set_title("Категориальные признаки машин")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_anomaly_heatmap(counts, observers, path):
    oids = sorted(observers)
    fields = list(FIELDS)
    matrix = np.zeros((len(fields), len(oids)))
    for (oid, f), c in counts.items():
        if oid in oids and f in fields:
            matrix[fields.index(f), oids.index(oid)] = c
    if matrix.max() == 0:
        return
    fig, ax = plt.subplots(figsize=(14, 6))
    im = ax.imshow(matrix, aspect="auto", cmap="OrRd")
    ax.set_xticks(range(len(oids)))
    ax.set_xticklabels([str(o) for o in oids], fontsize=8)
    ax.set_yticks(range(len(fields)))
    ax.set_yticklabels(fields, fontsize=8)
    ax.set_xlabel("observer_id")
    ax.set_title("Внесённые искажения: поле × наблюдатель")
    vmax = matrix.max()
    for i in range(len(fields)):
        for j in range(len(oids)):
            val = int(matrix[i, j])
            if val:
                ax.text(j, i, str(val), ha="center", va="center", fontsize=7,
                        color="white" if val > vmax / 2 else "black")
    fig.colorbar(im, ax=ax, label="шт.")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_anomalies_by_status(labels, truth, machines, path):
    by_status = defaultdict(Counter)
    for m, per_field in labels.items():
        status_map = dict(truth[m].get("status", []))
        for per_obs in per_field.values():
            for entries in per_obs.values():
                for ts, _ in entries:
                    by_status[m][status_map.get(ts, "?")] += 1
    if not by_status:
        return
    statuses = sorted({s for c in by_status.values() for s in c})
    rows = sorted(by_status)
    matrix = np.array([[by_status[m].get(s, 0) for s in statuses] for m in rows],
                      dtype=float)
    fig, ax = plt.subplots(figsize=(12, 4))
    im = ax.imshow(matrix, aspect="auto", cmap="OrRd")
    ax.set_xticks(range(len(statuses)))
    ax.set_xticklabels(statuses, fontsize=8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([machines[m]["name"] for m in rows], fontsize=8)
    vmax = matrix.max() if matrix.size else 1
    for i in range(len(rows)):
        for j in range(len(statuses)):
            if matrix[i, j]:
                ax.text(j, i, int(matrix[i, j]), ha="center", va="center",
                        fontsize=8,
                        color="white" if matrix[i, j] > vmax / 2 else "black")
    ax.set_title("Искажения по status")
    fig.colorbar(im, ax=ax, label="шт.")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_scores_hist(preds, path):
    if not preds:
        return
    by_field = defaultdict(list)
    for _, _, f, s, _ in preds:
        by_field[f].append(s)
    fields = sorted(by_field)
    cols = 2
    rows = (len(fields) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(14, 3 * rows), squeeze=False)
    for i, f in enumerate(fields):
        ax = axes[i // cols][i % cols]
        ax.hist(by_field[f], bins=50, log=True, color="steelblue")
        ax.axvline(THRESHOLD, color="red", ls="--", lw=0.8)
        ax.set_title(f, fontsize=9)
        ax.set_xlabel("score")
        ax.grid(alpha=0.3)
    for j in range(len(fields), rows * cols):
        axes[j // cols][j % cols].set_visible(False)
    fig.suptitle("Оценки детектора (лог-шкала по Y)")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def plot_precision_recall(preds, labels, path):
    stats = defaultdict(lambda: [0, 0, 0])
    pred_set = set()
    for oid, ts, f, _s, _m in preds:
        key = (oid, ts, f)
        pred_set.add(key)
        stats[f][0 if key in labels else 1] += 1
    for key in labels:
        if key not in pred_set:
            stats[key[2]][2] += 1
    if not stats:
        return
    fields = sorted(stats)
    tp = [stats[f][0] for f in fields]
    fp = [stats[f][1] for f in fields]
    fn = [stats[f][2] for f in fields]
    x = np.arange(len(fields))
    w = 0.28
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(x - w, tp, w, label="TP", color="seagreen")
    ax.bar(x, fp, w, label="FP", color="indianred")
    ax.bar(x + w, fn, w, label="FN (не поймано)", color="orange")
    ax.set_xticks(x)
    ax.set_xticklabels(fields, rotation=20, ha="right")
    ax.set_title("Детектор vs. разметка по полям")
    ax.legend()
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# --------------------------------------------------------------- анализ
def build_analysis(truth, labels, machines):
    lines = ["# Анализ датасета", ""]
    for m in sorted(truth):
        info = machines[m]
        t = truth[m]
        lines.append(f"## {info['name']} — {info['category']}")
        lines.append(f"- drive_type={info['drive_type']}, cooling={info['cooling']}, "
                     f"criticality={info['criticality']}")
        lines.append(f"- active_fields: {', '.join(info['active_fields'])}")
        status_counts = Counter(s for _, s in t.get("status", []))
        total = sum(status_counts.values()) or 1
        if status_counts:
            lines.append("- status:")
            for s, c in status_counts.most_common():
                lines.append(f"    - {s}: {c} ({c / total:.1%})")
        lines.append("- сигналы:")
        for f in ("speed_rpm", "load_pct", "motor_temp_c", "current_a", "power_kw"):
            vals = [v for _, v in t.get(f, [])]
            if vals:
                lines.append(
                    f"    - {f}: mean={statistics.mean(vals):.3f}, "
                    f"sd={statistics.pstdev(vals):.3f}"
                )
        # искажения по статусу
        if m in labels:
            status_map = dict(t.get("status", []))
            ab = Counter()
            for per_obs in labels[m].values():
                for entries in per_obs.values():
                    for ts, _ in entries:
                        ab[status_map.get(ts, "?")] += 1
            if ab:
                lines.append("- искажения по status: " +
                             ", ".join(f"{s}={c}" for s, c in ab.most_common()))
        lines.append("")
    return "\n".join(lines)


def write_index(output, plots, groups):
    html = ["<!doctype html><meta charset='utf-8'>",
            "<title>Telemetry plots</title>",
            "<style>body{font-family:sans-serif;max-width:1400px;margin:20px auto}"
            "img{max-width:100%;border:1px solid #ccc;margin-bottom:14px}"
            "h2{margin-top:30px}table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:4px 8px}</style>",
            "<h1>Телеметрия — визуализация</h1>"]
    for title, items in groups:
        if not items:
            continue
        html.append(f"<h2>{title}</h2>")
        for p in items:
            html.append(f"<div><b>{p.name}</b><br><img src='{p.name}'></div>")
    (output / "index.html").write_text("\n".join(html), encoding="utf-8")


# ------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partitions", type=int, default=1)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--machine", type=int, action="append")
    parser.add_argument("--field", action="append")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--no-overview", action="store_true")
    args = parser.parse_args()

    if args.partitions <= 0 or args.stride <= 0:
        parser.error("--partitions и --stride должны быть положительными")
    if not (args.dataset / "observations").is_dir():
        parser.error("в каталоге нет observations/")

    machines, observers = load_catalogs(args.dataset)
    parts = partition_paths(args.dataset)
    if not parts:
        parser.error("не найдены партиции")
    parts = parts[:args.partitions]
    wanted = set(args.machine) if args.machine else set(machines)
    bad = wanted - set(machines)
    if bad:
        parser.error(f"неизвестные machine_id: {sorted(bad)}")
    fields = tuple(args.field) if args.field else DEFAULT_FIELDS
    bad = set(fields) - set(FIELDS)
    if bad:
        parser.error(f"неизвестные поля: {sorted(bad)}")

    args.output.mkdir(parents=True, exist_ok=True)
    groups = []  # [(title, [paths])]

    print(f"читаю {len(parts)} партиций, stride={args.stride}")
    truth, obs, labels = collect(args.dataset, observers, wanted, parts, args.stride)

    # 1. категориальные признаки
    cat_group = []
    p = args.output / "category_card.png"
    plot_category_card(machines, p); cat_group.append(p)
    p = args.output / "active_fields_matrix.png"
    plot_active_fields(machines, p); cat_group.append(p)
    groups.append(("Категориальные признаки", cat_group))

    # 2. статусы
    st_group = []
    for m in sorted(wanted):
        p = args.output / f"status_timeline_m{m:02d}.png"
        plot_status_timeline(m, machines[m], truth[m], p)
        st_group.append(p)
    p = args.output / "status_distribution.png"
    plot_status_distribution(truth, machines, p)
    st_group.append(p)
    groups.append(("Статусы", st_group))

    # 3. подробные графики по полям
    for m in sorted(wanted):
        for f in fields:
            if not truth[m].get(f):
                continue
            path = args.output / f"machine{m:02d}_{f}.png"
            plot_field(m, machines[m], f, truth[m], obs[m], labels[m], observers, path)
            groups.append((f"{machines[m]['name']} — {f}", [path]))

    # 4. обзорные графики
    if not args.no_overview:
        for m in sorted(wanted):
            path = args.output / f"machine{m:02d}_overview.png"
            info = machines[m]
            fields_m = [f for f in FIELDS if truth[m].get(f)]
            if not fields_m:
                continue
            cols = 2
            rows = (len(fields_m) + cols - 1) // cols
            fig, axes = plt.subplots(rows, cols, figsize=(14, 3 * rows),
                                     squeeze=False, sharex=True)
            for i, f in enumerate(fields_m):
                ax = axes[i // cols][i % cols]
                ax.plot([p[0] for p in truth[m][f]],
                        [p[1] for p in truth[m][f]], lw=0.9)
                ax.set_title(f, fontsize=9)
                ax.set_ylabel(UNITS.get(f, ""), fontsize=8)
                ax.grid(alpha=0.3)
            for j in range(len(fields_m), rows * cols):
                axes[j // cols][j % cols].set_visible(False)
            fig.suptitle(f"{info['name']} [{info['category']} · {info['criticality']}] — эталон")
            fig.tight_layout()
            fig.savefig(path, dpi=110)
            plt.close(fig)
            groups.append((f"{info['name']} — обзор", [path]))

    # 5. разметка
    lab_group = []
    counts = count_labels(args.dataset, parts)
    if counts:
        p = args.output / "anomalies_heatmap.png"
        plot_anomaly_heatmap(counts, observers, p); lab_group.append(p)
        p = args.output / "anomalies_by_status.png"
        plot_anomalies_by_status(labels, truth, machines, p); lab_group.append(p)
    groups.append(("Разметка", lab_group))

    # 6. детектор
    if args.predictions:
        det_group = []
        preds = load_predictions(args.predictions)
        p = args.output / "detector_scores.png"
        plot_scores_hist(preds, p); det_group.append(p)
        label_set = load_labels(args.dataset, parts)
        if label_set:
            p = args.output / "detector_pr.png"
            plot_precision_recall(preds, label_set, p); det_group.append(p)
        groups.append(("Детектор", det_group))

    write_index(args.output, [], groups)

    # 7. анализ
    analysis = build_analysis(truth, labels, machines)
    (args.output / "analysis.txt").write_text(analysis, encoding="utf-8")

    total = sum(len(items) for _, items in groups)
    print(f"готово: {total} PNG + analysis.txt в {args.output}")


if __name__ == "__main__":
    main()