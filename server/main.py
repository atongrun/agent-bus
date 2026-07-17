"""Agent Bus Server — FastAPI application entry point."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI

from server.bootstrap import router as bootstrap_router
from server.db import init_db
from server.events import router as events_router

# Load .env file if it exists
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize database. Shutdown: nothing yet."""
    init_db()
    yield


app = FastAPI(
    title="Agent Bus",
    description="Cross-machine durable event relay for AI agent collaboration",
    version="0.2.0",
    lifespan=lifespan,
)

# Include event routes
app.include_router(events_router)
# Include bootstrap token endpoint
app.include_router(bootstrap_router)


@app.get("/health")
async def health():
    """Health check endpoint — no auth required."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main():
    """Entry point for uvicorn."""
    import uvicorn

    host = os.environ.get("AGENT_BUS_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT_BUS_PORT", "8800"))
    uvicorn.run("server.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
