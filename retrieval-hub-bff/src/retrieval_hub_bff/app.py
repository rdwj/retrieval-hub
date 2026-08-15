"""FastAPI application for the RetrievalHub BFF."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from retrieval_hub_bff.routes import router

app = FastAPI(title="RetrievalHub BFF")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
