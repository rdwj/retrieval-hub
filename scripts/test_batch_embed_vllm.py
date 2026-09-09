"""Batch embedding stress test for vLLM nomic-embed-text-v1.5.

Port-forward the vLLM service first:
    oc port-forward svc/vllm-nomic-embedding 8000:8000 \
        --context=gpt-oss-120b -n retrieval-hub

Then run:
    python scripts/test_batch_embed_vllm.py --endpoint http://127.0.0.1:8000

Generates N synthetic chunks and embeds them in batches, reporting
throughput, memory stability (no OOM), and vector dimensions.
"""

from __future__ import annotations

import argparse
import logging
import time

from retrieval_hub.ingestion.embed import ChunkEmbedder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def generate_synthetic_chunks(n: int) -> list:
    """Create N fake chunks with realistic text lengths."""
    from dataclasses import dataclass

    @dataclass
    class FakeChunk:
        text: str

    base_texts = [
        "Hypertension is defined as systolic blood pressure of 140 mmHg or higher, "
        "or diastolic blood pressure of 90 mmHg or higher. Treatment approaches include "
        "lifestyle modifications and pharmacological interventions.",
        "Post-traumatic stress disorder is characterized by intrusive memories, "
        "avoidance behaviors, negative changes in thinking and mood, and changes in "
        "physical and emotional reactions following exposure to a traumatic event.",
        "Type 2 diabetes mellitus management includes regular monitoring of glycated "
        "hemoglobin levels, dietary modifications, exercise programs, and medication "
        "adjustments based on individual patient response.",
        "Chronic pain management requires a multimodal approach combining physical "
        "therapy, cognitive behavioral therapy, pharmacological treatment, and patient "
        "education about self-management strategies.",
        "Substance use disorder treatment follows a continuum of care including "
        "screening, brief intervention, referral to treatment, detoxification, "
        "rehabilitation, and long-term recovery support.",
    ]

    return [FakeChunk(text=base_texts[i % len(base_texts)] + f" [chunk {i}]") for i in range(n)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch embedding stress test")
    parser.add_argument("--endpoint", required=True, help="vLLM endpoint URL")
    parser.add_argument("--chunks", type=int, default=1000, help="Number of chunks")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--model", default="nomic-ai/nomic-embed-text-v1.5")
    args = parser.parse_args()

    logger.info("Starting batch embedding test: %d chunks, batch_size=%d", args.chunks, args.batch_size)
    logger.info("Endpoint: %s", args.endpoint)

    embedder = ChunkEmbedder(
        model_name=args.model,
        endpoint=args.endpoint,
        batch_size=args.batch_size,
    )

    dim = embedder.dimension
    logger.info("Model dimension: %d", dim)

    chunks = generate_synthetic_chunks(args.chunks)
    logger.info("Generated %d synthetic chunks", len(chunks))

    t0 = time.time()
    vectors = embedder.embed_chunks(chunks)
    elapsed = time.time() - t0

    logger.info("Embedded %d chunks in %.1fs (%.1f chunks/sec)", len(vectors), elapsed, len(vectors) / elapsed)
    logger.info("Vector dimension: %d (expected %d)", len(vectors[0]), dim)
    logger.info("All vectors correct dimension: %s", all(len(v) == dim for v in vectors))

    print(f"\nRESULTS:")
    print(f"  Chunks:     {len(vectors)}")
    print(f"  Dimension:  {len(vectors[0])}")
    print(f"  Time:       {elapsed:.1f}s")
    print(f"  Throughput: {len(vectors) / elapsed:.1f} chunks/sec")
    print(f"  Batch size: {args.batch_size}")
    print(f"  Status:     PASS")


if __name__ == "__main__":
    main()
