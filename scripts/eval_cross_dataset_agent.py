"""Cross-dataset reasoning eval: test agent source selection and synthesis.

Runs eval questions through an Anthropic API conversation loop with
RetrievalHub MCP tools. Records tool call sequences, source selection
accuracy, and final answers.

Usage:
    python scripts/eval_cross_dataset_agent.py
    python scripts/eval_cross_dataset_agent.py --prompt-file path/to/prompt.md
    python scripts/eval_cross_dataset_agent.py --question-id xds001
    python scripts/eval_cross_dataset_agent.py --mcp-url http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger("eval_cross_dataset_agent")

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "eval" / "cross_dataset_reasoning"
QUESTIONS_PATH = EVAL_DIR / "eval_questions.json"

DEFAULT_PROMPT_FILE = str(REPO_ROOT.parent / "retrieval-hub-agent" / "identity.md")
DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOOL_RESULT_LOG = 500

# Claude 5 family models reject the temperature parameter.
_NO_TEMPERATURE_PREFIXES = ("claude-sonnet-5", "claude-opus-5")


def _supports_temperature(model: str) -> bool:
    return not model.startswith(_NO_TEMPERATURE_PREFIXES)

# Tool definitions matching the MCP server's signatures.
TOOLS = [
    {
        "name": "list_sources",
        "description": (
            "List all queryable data sources in the RetrievalHub catalog. "
            "Returns sources in the CURATED or PUBLISHED lifecycle states. "
            "Each entry includes the slug (use with retrieve), display name, "
            "source family, lifecycle status, and document count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "describe_source",
        "description": (
            "Get detailed metadata for a specific data source. "
            "Returns catalog metadata including sample prompts, document/chunk "
            "counts, and ownership information. Use the slug from list_sources."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Source slug from list_sources",
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "retrieve",
        "description": (
            "Search a data source and return relevant passages with provenance "
            "metadata. Each hit includes a cosine similarity score. The response "
            "includes usage_rules (citation requirements, scope disclaimers, "
            "handling constraints) and data_freshness metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query",
                },
                "source": {
                    "type": "string",
                    "description": "Source slug (from list_sources)",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["query", "source"],
        },
    },
    {
        "name": "refine",
        "description": (
            "Expand context around a previously retrieved chunk. Use when a "
            "retrieve hit looks like part of a larger process or section and "
            "you need more context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source slug"},
                "doc_title": {
                    "type": "string",
                    "description": "Document title from retrieve hit",
                },
                "chunk_index": {
                    "type": "integer",
                    "description": "Chunk index from retrieve hit",
                },
                "query": {
                    "type": "string",
                    "description": "What additional context you need",
                },
                "chunk_id": {
                    "type": "string",
                    "description": (
                        "Stable UUID from prior result "
                        "(auto-resolves doc_title/chunk_index)"
                    ),
                },
                "window": {
                    "type": "integer",
                    "description": "Chunks before and after to include",
                },
                "max_context_tokens": {
                    "type": "integer",
                    "description": "Maximum tokens to return",
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Refinement strategy: section, adjacent, "
                        "cross_reference, entity_arc"
                    ),
                },
            },
            "required": ["source", "doc_title", "chunk_index", "query"],
        },
    },
]


def load_system_prompt(path: str) -> tuple[str, str]:
    """Read a system prompt from a markdown or YAML file.

    YAML files: extracts the ``template`` field and ``version``.
    Everything else: returns the raw content with version "unknown".

    Returns ``(prompt_text, version_string)``.
    """
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith((".yaml", ".yml")):
        data = yaml.safe_load(text)
        version = str(data.get("version", "unknown"))
        return data["template"], f"v{version}"
    return text, "unknown"


async def proxy_tool_call(
    session: ClientSession, tool_name: str, arguments: dict
) -> str:
    """Call an MCP tool and return the result as a JSON string.

    Errors are returned as a descriptive string rather than raised so
    the conversation loop can surface them to the model.
    """
    try:
        result = await session.call_tool(tool_name, arguments)
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("MCP tool %s failed: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


async def run_question(
    client: anthropic.AsyncAnthropic,
    mcp_session: ClientSession,
    system_prompt: str,
    question: dict,
    model: str,
    max_iterations: int = 15,
) -> dict:
    """Run one eval question through the full conversation loop.

    Returns a dict with tool call trace, source selection data, the
    model's final answer, and token counts.
    """
    messages: list[dict] = [{"role": "user", "content": question["question"]}]
    tool_calls: list[dict] = []
    sources_queried: set[str] = set()
    sources_described: set[str] = set()
    used_list_sources = False
    total_input_tokens = 0
    total_output_tokens = 0
    final_answer = ""

    for iteration in range(1, max_iterations + 1):
        create_kwargs: dict = dict(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
        if _supports_temperature(model):
            create_kwargs["temperature"] = 0.0
        response = await client.messages.create(**create_kwargs)

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Process every content block in the response.
        tool_use_blocks = []
        for block in response.content:
            if block.type == "text":
                final_answer = block.text
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        if not tool_use_blocks:
            # No tool calls -- the model is done.
            break

        # Append the full assistant message (may contain text + tool_use).
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool call and build tool_result messages.
        tool_results: list[dict] = []
        for block in tool_use_blocks:
            name = block.name
            args = block.input

            # Track source selection.
            if name == "list_sources":
                used_list_sources = True
            elif name == "describe_source" and "slug" in args:
                sources_described.add(args["slug"])
            elif name == "retrieve" and "source" in args:
                sources_queried.add(args["source"])

            result_text = await proxy_tool_call(mcp_session, name, args)

            tool_calls.append(
                {
                    "tool_name": name,
                    "arguments": args,
                    "result_summary": result_text[:MAX_TOOL_RESULT_LOG],
                }
            )

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }
            )

        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            break
    else:
        logger.warning(
            "Question %s hit max iterations (%d)",
            question["id"],
            max_iterations,
        )

    return {
        "question_id": question["id"],
        "question": question["question"],
        "category": question.get("category", ""),
        "expected_sources": question.get("expected_sources", []),
        "tool_calls": tool_calls,
        "sources_queried": sorted(sources_queried),
        "sources_described": sorted(sources_described),
        "used_list_sources": used_list_sources,
        "final_answer": final_answer,
        "iterations": min(iteration, max_iterations),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
    }


def compute_metrics(
    results: list[dict], questions: list[dict]
) -> list[dict]:
    """Compute source selection metrics for each question.

    Returns a list mirroring *results* with added metric fields.
    """
    expected_map = {q["id"]: set(q.get("expected_sources", [])) for q in questions}

    for r in results:
        expected = expected_map.get(r["question_id"], set())
        queried = set(r["sources_queried"])

        if not queried and not expected:
            precision = 1.0
            recall = 1.0
        elif not queried:
            precision = 1.0  # vacuously true
            recall = 0.0
        elif not expected:
            precision = 0.0
            recall = 1.0  # nothing to miss
        else:
            precision = len(queried & expected) / len(queried)
            recall = len(queried & expected) / len(expected)

        r["source_precision"] = precision
        r["source_recall"] = recall
        r["source_exact_match"] = queried == expected

    return results


def build_summary(results: list[dict]) -> dict:
    """Aggregate metrics by category and overall."""
    categories: dict[str, list[dict]] = {}
    for r in results:
        cat = r.get("category", "unknown")
        categories.setdefault(cat, []).append(r)

    def _agg(items: list[dict]) -> dict:
        n = len(items)
        if n == 0:
            return {"count": 0}
        return {
            "count": n,
            "source_precision_mean": sum(i["source_precision"] for i in items) / n,
            "source_recall_mean": sum(i["source_recall"] for i in items) / n,
            "exact_match_rate": sum(i["source_exact_match"] for i in items) / n,
        }

    by_category = {cat: _agg(items) for cat, items in sorted(categories.items())}

    total_input = sum(r["input_tokens"] for r in results)
    total_output = sum(r["output_tokens"] for r in results)
    n = len(results)
    avg_iter = sum(r["iterations"] for r in results) / n if n else 0

    overall = _agg(results)
    overall.update(
        {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "avg_iterations": round(avg_iter, 2),
        }
    )

    return {
        "total_questions": n,
        "by_category": by_category,
        "overall": overall,
    }


def print_summary(summary: dict, wall_time: float) -> None:
    """Print a human-readable summary table to stdout."""
    print()
    print("=" * 72)
    print("Cross-Dataset Reasoning Eval Results")
    print("=" * 72)

    for cat, data in summary["by_category"].items():
        if data["count"] == 0:
            continue
        print(f"\n  {cat} (n={data['count']}):")
        print(f"    {'Metric':<25} {'Value':>8}")
        print(f"    {'-' * 25} {'-' * 8}")
        print(f"    {'source_precision_mean':<25} {data['source_precision_mean']:>8.3f}")
        print(f"    {'source_recall_mean':<25} {data['source_recall_mean']:>8.3f}")
        print(f"    {'exact_match_rate':<25} {data['exact_match_rate']:>8.3f}")

    overall = summary["overall"]
    print(f"\n  Overall (n={overall['count']}):")
    print(f"    source_precision_mean:  {overall['source_precision_mean']:.3f}")
    print(f"    source_recall_mean:     {overall['source_recall_mean']:.3f}")
    print(f"    exact_match_rate:       {overall['exact_match_rate']:.3f}")
    print(f"    avg_iterations:         {overall['avg_iterations']:.1f}")
    print(
        f"    tokens (in/out):        "
        f"{overall['total_input_tokens']:,} / {overall['total_output_tokens']:,}"
    )
    print(f"\n  Wall time: {wall_time:.1f}s")
    print("=" * 72)


async def async_main(args: argparse.Namespace) -> int:
    # Load system prompt.
    prompt_path = args.prompt_file
    try:
        system_prompt, prompt_version = load_system_prompt(prompt_path)
    except FileNotFoundError:
        logger.error("System prompt file not found: %s", prompt_path)
        return 1

    logger.info("Loaded system prompt from %s (%d chars, %s)", prompt_path, len(system_prompt), prompt_version)

    # Load eval questions.
    try:
        questions_data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
        questions = questions_data["questions"]
    except (FileNotFoundError, KeyError) as exc:
        logger.error("Failed to load eval questions from %s: %s", QUESTIONS_PATH, exc)
        return 1

    # Filter to a single question if requested.
    if args.question_id:
        questions = [q for q in questions if q["id"] == args.question_id]
        if not questions:
            logger.error("No question found with id=%s", args.question_id)
            return 1

    logger.info("Loaded %d eval question(s)", len(questions))

    # Determine run ID and output directory.
    run_id = args.run_id or datetime.now(tz=timezone.utc).strftime(f"%Y%m%d-%H%M%S-{prompt_version}")
    output_dir = EVAL_DIR / "runs" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Connect to MCP server.
    logger.info("Connecting to MCP server at %s", args.mcp_url)

    async with streamable_http_client(args.mcp_url) as (
        read_stream,
        write_stream,
    ):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()
            tools = await mcp_session.list_tools()
            tool_names = [t.name for t in tools.tools]
            logger.info("MCP connected. Available tools: %s", tool_names)

            # Verify expected tools are present.
            expected_tools = {"list_sources", "describe_source", "retrieve", "refine"}
            missing = expected_tools - set(tool_names)
            if missing:
                logger.error("MCP server is missing required tools: %s", missing)
                return 1

            # Probe catalog size for the config record.
            catalog_probe = await mcp_session.call_tool("list_sources", {})
            catalog_size = 0
            for block in catalog_probe.content:
                if hasattr(block, "text"):
                    try:
                        catalog_size = len(json.loads(block.text))
                    except (json.JSONDecodeError, TypeError):
                        pass
            logger.info("Catalog contains %d sources", catalog_size)

            # Anthropic client.
            client = anthropic.AsyncAnthropic()

            # Verify the model is available before running the full eval.
            logger.info("Probing model availability: %s", args.model)
            try:
                probe_kwargs: dict = dict(
                    model=args.model,
                    max_tokens=16,
                    messages=[{"role": "user", "content": "Say ok."}],
                )
                if _supports_temperature(args.model):
                    probe_kwargs["temperature"] = 0.0
                probe_resp = await client.messages.create(**probe_kwargs)
                logger.info(
                    "Model probe succeeded (%d input, %d output tokens)",
                    probe_resp.usage.input_tokens,
                    probe_resp.usage.output_tokens,
                )
            except anthropic.NotFoundError:
                logger.error(
                    "Model %s returned 404 — it may be deprecated. "
                    "Use a current alias (e.g. claude-sonnet-5).",
                    args.model,
                )
                return 1
            except anthropic.APIError as exc:
                logger.error("Model probe failed: %s", exc)
                return 1

            # Write config before running questions.
            uses_temperature = _supports_temperature(args.model)
            config = {
                "prompt_file": str(prompt_path),
                "prompt_version": prompt_version,
                "model": args.model,
                "temperature": 0.0 if uses_temperature else None,
                "mcp_url": args.mcp_url,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "catalog_size": catalog_size,
                "question_count": len(questions),
            }
            (output_dir / "config.json").write_text(
                json.dumps(config, indent=2) + "\n", encoding="utf-8"
            )

            # Run each question.
            wall_start = time.monotonic()
            results: list[dict] = []

            for i, question in enumerate(questions, 1):
                logger.info(
                    "Running question %d/%d: %s", i, len(questions), question["id"]
                )

                try:
                    result = await run_question(
                        client,
                        mcp_session,
                        system_prompt,
                        question,
                        args.model,
                    )
                    results.append(result)

                    logger.info(
                        "  sources_queried=%s  iterations=%d  tokens=%d/%d",
                        result["sources_queried"],
                        result["iterations"],
                        result["input_tokens"],
                        result["output_tokens"],
                    )
                except Exception:
                    logger.exception("Failed on question %s", question["id"])
                    results.append(
                        {
                            "question_id": question["id"],
                            "question": question["question"],
                            "category": question.get("category", ""),
                            "expected_sources": question.get("expected_sources", []),
                            "tool_calls": [],
                            "sources_queried": [],
                            "sources_described": [],
                            "used_list_sources": False,
                            "final_answer": "",
                            "iterations": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "error": True,
                        }
                    )

                # Brief pause between questions to avoid rate limiting.
                if i < len(questions):
                    await asyncio.sleep(1)

            wall_time = time.monotonic() - wall_start

    # Compute metrics.
    results = compute_metrics(results, questions)

    # Write results.
    (output_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Wrote results to %s", output_dir / "results.json")

    # Build and write summary.
    summary = build_summary(results)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Wrote summary to %s", output_dir / "summary.json")

    print_summary(summary, wall_time)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--prompt-file",
        default=DEFAULT_PROMPT_FILE,
        help="Path to system prompt (markdown or YAML). Default: %(default)s",
    )
    parser.add_argument(
        "--mcp-url",
        default=DEFAULT_MCP_URL,
        help="MCP server URL. Default: %(default)s",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Anthropic model. Default: %(default)s",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run identifier (default: YYYYMMDD-HHMMSS-v0)",
    )
    parser.add_argument(
        "--question-id",
        default=None,
        help="Run a single question by ID",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
