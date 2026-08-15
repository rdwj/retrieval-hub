# AutoRAG Chunking Evaluation

Evaluates chunking strategies for the VA CPG corpus using [AutoRAG](https://github.com/Marker-Inc-Korea/AutoRAG) (v0.3.x).

## Setup

```bash
pip install "AutoRAG>=0.3.24,<1.0"
```

## Steps

1. **Prepare data** -- converts markdown corpus and QA JSON into AutoRAG parquet format:

   ```bash
   python eval/autorag/prepare_data.py
   ```

   Outputs `eval/autorag/data/{parsed,corpus,qa}.parquet`.

2. **Run chunking sweep** -- tests Token and Sentence chunking at 256/512/1024 sizes with 0/64 overlap:

   ```bash
   python eval/autorag/run_eval.py
   ```

3. **Review results** in `eval/autorag/results/chunk/summary.csv`.

## Data format

- **parsed.parquet**: full documents with `texts`, `doc_id`, `metadata` columns (input to Chunker)
- **corpus.parquet**: same data with `contents` column (for direct Evaluator use)
- **qa.parquet**: 50 clinical questions with `retrieval_gt` doc_ids and `generation_gt` answer texts

## Configuration files

- `chunk_config.yaml` -- chunking methods, sizes, and overlaps to sweep
- `eval_config.yaml` -- retrieval and reranking evaluation (for phase 2)
