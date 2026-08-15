"""Entry point: ``python -m retrieval_hub_bff``."""

import os

import uvicorn

from retrieval_hub_bff.app import app

if __name__ == "__main__":
    host = os.environ.get("BFF_HOST", "0.0.0.0")
    port = int(os.environ.get("BFF_PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
