---
name: eval-report
description: >
  Generate a standardized eval comparison report from retrieval-hub eval runs.
  Produces a Pareto front scatter plot (context_precision vs answer_relevancy,
  faithfulness as bubble size + color gradient) and an accessible summary table
  with raw numbers. Use when comparing chunk configs, embedding models, reranking
  strategies, or any set of eval runs that produced summary.json files.
---

# Eval Report

Generate a standardized comparison report from two or more eval runs.

## When to use

After running `eval_answer_quality.py` on multiple configurations and you need
to compare results visually and decide on a winner. Typical triggers:

- "compare these eval runs"
- "generate the Pareto plot"
- "eval report"
- After completing a sweep (chunk configs, embedding models, reranking strategies)

## Inputs

The user provides either:

1. **Run directories** — paths to `eval/rewrite_lift/runs/<run-name>/` directories,
   each containing a `summary.json`.
2. **A sweep results file** — e.g., `eval/va_cpg_chunking_sweep/sweep_results.json`
   for retrieval-only metrics, paired with run directories for Ragas metrics.

Each run must have a human-readable label (e.g., "512/0", "Nomic raw").

## Output

The script at `.claude/skills/eval-report/scripts/pareto_report.py` produces:

1. **Pareto front PNG** — scatter plot:
   - X-axis: context_precision
   - Y-axis: answer_relevancy
   - Bubble size: faithfulness (larger = higher)
   - Color gradient: faithfulness (darker = higher)
   - Labels on each point
   - Pareto front line connecting non-dominated points
   - Recommended config called out with a star marker
   - Title includes query count and seed for reproducibility

2. **Markdown table** — printed to stdout and appended below the plot as a
   text-based summary. Includes all metrics for every config. This ensures
   the data is accessible to people who cannot see the graph.

3. **JSON summary** — machine-readable comparison output.

## How to run

```bash
# From project root, with venv active:
python .claude/skills/eval-report/scripts/pareto_report.py \
  --runs run1_label=eval/rewrite_lift/runs/embed-nomic-faithful \
         run2_label=eval/rewrite_lift/runs/nomic-512-64 \
  --output eval/reports/chunk-comparison.png \
  --title "Chunk Config Comparison — VA CPG"
```

Or invoke from the agent with `/eval-report`.

## Extending

To add sweep retrieval metrics (hit_rate, MRR, cosine_sim) from a sweep_results
file, pass `--sweep eval/va_cpg_chunking_sweep/sweep_results.json` with a
`--sweep-key-map` that maps sweep config keys to run labels.

## Design decisions

- Faithfulness is the third axis (bubble size + gradient) because it's the
  highest-weight metric for clinical content but doesn't trade off cleanly
  against the other two.
- Raw numbers appear below the plot, not just in a separate file, so the
  report is self-contained and accessible.
- The Pareto front is computed on context_precision and answer_relevancy only
  (the two axes). Faithfulness is shown but does not affect the front.
