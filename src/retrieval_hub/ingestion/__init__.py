"""Ingestion pipeline for the retrieval-hub core library.

The ``ingestion`` subpackage contains the seven-stage pipeline described in
``docs/ingestion.md``: fetch, parse, normalize, chunk, embed, write, register.

Step 4 exercises the pipeline as a hand-run script, not a production runner;
each stage is implemented as a plain Python function that can be composed by
a script or a test. Production runners (Jobs / Tekton / KubeFlow) come in a
later step and will reuse the same stage functions.
"""

from __future__ import annotations

__all__: list[str] = []
