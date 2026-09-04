"""FastAPI app entry point for the executive reporting API.

Run with: uvicorn waterfall_guard.api.app:app
"""

from fastapi import FastAPI

from waterfall_guard.api.dashboard_router import router as dashboard_router

app = FastAPI(title="Waterfall Guard Executive Reporting API")
app.include_router(dashboard_router)
