#!/usr/bin/env python3
"""Generate a Pareto front comparison report from eval run summaries.

Produces a scatter plot (context_precision vs answer_relevancy, faithfulness
as bubble size and color gradient) plus a markdown summary table.  Points on
the Pareto front are connected with a dashed line.

Usage:

    python .claude/skills/eval-report/scripts/pareto_report.py \
      --runs "512/0=eval/rewrite_lift/runs/embed-nomic-faithful" \
             "512/64=eval/rewrite_lift/runs/nomic-512-64" \
             "1024/0=eval/rewrite_lift/runs/nomic-1024-0" \
      --sweep eval/va_cpg_chunking_sweep/sweep_results.json \
      --sweep-key-map "512_0=512/0" "512_64=512/64" "1024_0=1024/0" \
      --recommend "512/0" \
      --title "Chunk Config Comparison — VA CPG" \
      --output eval/reports/chunk-comparison.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np

# -- Palette (brand-neutral defaults, dark-mode safe) -----------------------

BG_COLOR = "#FAFAFA"
GRID_COLOR = "#E0E0E0"
TEXT_COLOR = "#333333"
PARETO_LINE_COLOR = "#2E7D32"
RECOMMEND_COLOR = "#D32F2F"
CMAP_NAME = "YlGn"


# -- Data loading ------------------------------------------------------------

def load_run(path: Path, condition: str = "raw") -> dict | None:
    summary_path = path / "summary.json"
    if not summary_path.exists():
        return None
    with open(summary_path) as f:
        data = json.load(f)
    cond = data.get(condition, {})
    config = data.get("config", {})
    return {
        "context_precision": cond.get("context_precision"),
        "answer_relevancy": cond.get("answer_relevancy"),
        "faithfulness": cond.get("faithfulness"),
        "query_count": config.get("query_count"),
        "eval_seed": config.get("eval_seed"),
    }


def load_sweep(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)["results"]


# -- Pareto front computation ------------------------------------------------

def pareto_front(points: list[tuple[float, float, str]]) -> list[str]:
    """Return labels of points on the Pareto front (maximize both axes)."""
    sorted_pts = sorted(points, key=lambda p: (-p[0], -p[1]))
    front_labels = []
    max_y = -float("inf")
    for _x, y, label in sorted_pts:
        if y > max_y:
            front_labels.append(label)
            max_y = y
    return front_labels


# -- Plot --------------------------------------------------------------------

def make_report(
    entries: dict[str, dict],
    output_path: Path,
    title: str,
    recommend_label: str | None,
    sweep_data: dict | None,
    sweep_key_map: dict[str, str] | None,
):
    has_ragas = [
        label for label, e in entries.items()
        if e.get("context_precision") is not None
    ]

    if not has_ragas:
        print("No runs with Ragas metrics found. Printing table only.\n")
        _print_table(entries, sweep_data, sweep_key_map, recommend_label)
        return

    # Merge sweep retrieval metrics into entries for the table.
    if sweep_data and sweep_key_map:
        for sweep_key, label in sweep_key_map.items():
            if label in entries and sweep_key in sweep_data:
                sd = sweep_data[sweep_key]
                entries[label]["hit_rate_at_5"] = sd.get("hit_rate_at_5")
                entries[label]["mrr_at_5"] = sd.get("mrr_at_5")
                entries[label]["mean_cosine_sim"] = sd.get("mean_cosine_sim")
                entries[label]["chunk_count"] = sd.get("chunk_count")

    # Extract Ragas data for plotting.
    plot_labels = []
    xs, ys, faiths = [], [], []
    for label in has_ragas:
        e = entries[label]
        plot_labels.append(label)
        xs.append(e["context_precision"])
        ys.append(e["answer_relevancy"])
        faiths.append(e["faithfulness"])

    xs = np.array(xs)
    ys = np.array(ys)
    faiths = np.array(faiths)

    # Bubble sizing: scale faithfulness to a visible range.
    faith_min, faith_max = faiths.min(), faiths.max()
    if faith_max - faith_min < 1e-6:
        sizes = np.full_like(faiths, 200.0)
    else:
        sizes = 80 + 400 * (faiths - faith_min) / (faith_max - faith_min)

    # Color mapping.
    cmap = plt.get_cmap(CMAP_NAME)
    if faith_max - faith_min < 1e-6:
        colors = [cmap(0.6)] * len(faiths)
    else:
        norm = mcolors.Normalize(vmin=faith_min - 0.02, vmax=faith_max + 0.02)
        colors = [cmap(norm(f)) for f in faiths]

    # Pareto front.
    front_labels = pareto_front(
        [(x, y, lbl) for x, y, lbl in zip(xs, ys, plot_labels, strict=True)]
    )
    front_points = [
        (entries[lbl]["context_precision"], entries[lbl]["answer_relevancy"])
        for lbl in front_labels
    ]
    front_points.sort(key=lambda p: p[0])

    # Query metadata from first run.
    first = entries[has_ragas[0]]
    query_count = first.get("query_count", "?")
    eval_seed = first.get("eval_seed", "?")

    # -- Figure: plot on top, table on bottom --------------------------------

    fig = plt.figure(figsize=(10, 9), facecolor=BG_COLOR)
    gs = fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.35)
    ax = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])

    ax.set_facecolor(BG_COLOR)
    ax.grid(True, alpha=0.4, color=GRID_COLOR, linestyle="-", linewidth=0.5)

    # Scatter.
    for i, label in enumerate(plot_labels):
        is_rec = label == recommend_label
        marker = "*" if is_rec else "o"
        edge = RECOMMEND_COLOR if is_rec else "#555555"
        zorder = 10 if is_rec else 5
        s = sizes[i] * (1.8 if is_rec else 1.0)
        ax.scatter(
            xs[i], ys[i], s=s, c=[colors[i]], marker=marker,
            edgecolors=edge, linewidths=1.5 if is_rec else 0.8,
            zorder=zorder, alpha=0.9,
        )
        if is_rec:
            ax.annotate(
                label, (xs[i], ys[i]),
                textcoords="offset points", xytext=(8, 10),
                fontsize=9, fontweight="bold", color=RECOMMEND_COLOR,
            )
            ax.annotate(
                "recommended", (xs[i], ys[i]),
                textcoords="offset points", xytext=(8, 22),
                fontsize=7.5, fontstyle="italic", color=RECOMMEND_COLOR,
            )
        else:
            ax.annotate(
                label, (xs[i], ys[i]),
                textcoords="offset points", xytext=(8, 6),
                fontsize=8.5, color=TEXT_COLOR,
            )

    # Pareto front line.
    if len(front_points) > 1:
        fx, fy = zip(*front_points, strict=True)
        ax.plot(
            fx, fy, linestyle="--", linewidth=1.5, color=PARETO_LINE_COLOR,
            alpha=0.5, zorder=2, label="Pareto front",
        )

    # Colorbar for faithfulness.
    sm = plt.cm.ScalarMappable(
        cmap=cmap,
        norm=mcolors.Normalize(
            vmin=faith_min - 0.02, vmax=faith_max + 0.02
        ),
    )
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.02, aspect=20)
    cbar.set_label("Faithfulness", fontsize=9, color=TEXT_COLOR)
    cbar.ax.tick_params(labelsize=8, colors=TEXT_COLOR)

    ax.set_xlabel("Context Precision", fontsize=10, color=TEXT_COLOR)
    ax.set_ylabel("Answer Relevancy", fontsize=10, color=TEXT_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)

    full_title = title
    if query_count != "?":
        full_title += f" ({query_count} queries, seed {eval_seed})"
    ax.set_title(full_title, fontsize=12, fontweight="bold", color=TEXT_COLOR, pad=12)

    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)

    # -- Table below the plot ------------------------------------------------

    ax_table.axis("off")

    col_headers = ["Config", "Ctx Prec", "Ans Rel", "Faithful"]
    has_retrieval = any(
        entries[lbl].get("hit_rate_at_5") is not None for lbl in plot_labels
    )
    if has_retrieval:
        col_headers += ["Hit@5", "MRR@5", "Cos Sim", "Chunks"]

    table_data = []
    for label in plot_labels:
        e = entries[label]
        row = [
            f"{'* ' if label == recommend_label else ''}{label}",
            f"{e['context_precision']:.3f}",
            f"{e['answer_relevancy']:.3f}",
            f"{e['faithfulness']:.3f}",
        ]
        if has_retrieval:
            row += [
                f"{e.get('hit_rate_at_5', '-'):.3f}" if e.get("hit_rate_at_5") is not None else "-",
                f"{e.get('mrr_at_5', '-'):.4f}" if e.get("mrr_at_5") is not None else "-",
                f"{e.get('mean_cosine_sim', '-'):.4f}" if e.get("mean_cosine_sim") is not None else "-",
                f"{e.get('chunk_count', '-'):,}" if e.get("chunk_count") is not None else "-",
            ]
        table_data.append(row)

    tbl = ax_table.table(
        cellText=table_data,
        colLabels=col_headers,
        loc="center",
        cellLoc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1.0, 1.4)

    for (row, _col), cell in tbl.get_celld().items():
        cell.set_edgecolor(GRID_COLOR)
        if row == 0:
            cell.set_facecolor("#E8E8E8")
            cell.set_text_props(fontweight="bold", color=TEXT_COLOR)
        else:
            cell.set_facecolor(BG_COLOR)
            cell.set_text_props(color=TEXT_COLOR)
            label_text = table_data[row - 1][0]
            if label_text.startswith("* "):
                cell.set_text_props(fontweight="bold", color=RECOMMEND_COLOR)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)

    print(f"Saved: {output_path}")
    print()
    _print_table(entries, sweep_data, sweep_key_map, recommend_label)

    # JSON summary.
    json_path = output_path.with_suffix(".json")
    json_out = {
        "title": full_title,
        "condition": "raw",
        "recommend": recommend_label,
        "pareto_front": front_labels,
        "configs": {},
    }
    for label, e in entries.items():
        json_out["configs"][label] = {
            k: v for k, v in e.items() if v is not None
        }
    with open(json_path, "w") as f:
        json.dump(json_out, f, indent=2)
    print(f"Saved: {json_path}")


def _print_table(
    entries: dict[str, dict],
    sweep_data: dict | None,
    sweep_key_map: dict[str, str] | None,
    recommend_label: str | None,
):
    """Print a markdown-formatted comparison table to stdout."""
    has_retrieval = any(e.get("hit_rate_at_5") is not None for e in entries.values())
    has_ragas = any(e.get("context_precision") is not None for e in entries.values())

    header = "| Config |"
    sep = "|--------|"
    if has_ragas:
        header += " Ctx Prec | Ans Rel | Faithful |"
        sep += "----------|---------|----------|"
    if has_retrieval:
        header += " Hit@5 | MRR@5  | Cos Sim | Chunks |"
        sep += "-------|--------|---------|--------|"

    print(header)
    print(sep)

    for label, e in entries.items():
        marker = " **" if label == recommend_label else ""
        end_marker = "**" if label == recommend_label else ""
        row = f"| {marker}{label}{end_marker} |"
        if has_ragas:
            cp = f"{e['context_precision']:.3f}" if e.get("context_precision") is not None else "-"
            ar = f"{e['answer_relevancy']:.3f}" if e.get("answer_relevancy") is not None else "-"
            fa = f"{e['faithfulness']:.3f}" if e.get("faithfulness") is not None else "-"
            row += f" {cp} | {ar} | {fa} |"
        if has_retrieval:
            hr = f"{e['hit_rate_at_5']:.3f}" if e.get("hit_rate_at_5") is not None else "-"
            mr = f"{e['mrr_at_5']:.4f}" if e.get("mrr_at_5") is not None else "-"
            cs = f"{e['mean_cosine_sim']:.4f}" if e.get("mean_cosine_sim") is not None else "-"
            cc = f"{e['chunk_count']:,}" if e.get("chunk_count") is not None else "-"
            row += f" {hr} | {mr} | {cs} | {cc} |"
        print(row)

    print()


# -- CLI ---------------------------------------------------------------------

def parse_kv_pairs(items: list[str]) -> dict[str, str]:
    """Parse 'key=value' pairs from CLI args."""
    result = {}
    for item in items:
        if "=" not in item:
            print(f"Error: expected key=value, got: {item}", file=sys.stderr)
            sys.exit(1)
        key, value = item.split("=", 1)
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Pareto front comparison report from eval runs."
    )
    parser.add_argument(
        "--runs", nargs="+", required=True,
        help="label=path pairs pointing to run directories with summary.json",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output PNG path (JSON summary written alongside)",
    )
    parser.add_argument("--title", default="Eval Comparison")
    parser.add_argument(
        "--recommend",
        help="Label of the recommended config (gets a star marker)",
    )
    parser.add_argument(
        "--condition", default="raw", choices=["raw", "rewrite"],
        help="Which condition to plot from summary.json (default: raw)",
    )
    parser.add_argument(
        "--sweep",
        help="Path to sweep_results.json for retrieval metrics",
    )
    parser.add_argument(
        "--sweep-key-map", nargs="*",
        help="sweep_key=run_label pairs mapping sweep config keys to --runs labels",
    )
    args = parser.parse_args()

    run_map = parse_kv_pairs(args.runs)
    entries: dict[str, dict] = {}

    for label, path_str in run_map.items():
        path = Path(path_str)
        data = load_run(path, args.condition)
        if data is None:
            print(f"Warning: no summary.json at {path}, skipping {label}", file=sys.stderr)
            entries[label] = {}
            continue
        entries[label] = data

    sweep_data = None
    sweep_key_map = None
    if args.sweep:
        sweep_data = load_sweep(Path(args.sweep))
        if args.sweep_key_map:
            sweep_key_map = parse_kv_pairs(args.sweep_key_map)

    make_report(
        entries=entries,
        output_path=Path(args.output),
        title=args.title,
        recommend_label=args.recommend,
        sweep_data=sweep_data,
        sweep_key_map=sweep_key_map,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
