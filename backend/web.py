"""The web app and the API from one process and one address, for hosts that
run one process (the Hugging Face Space, started by space/app.py):

    /api/...     the API (backend.api.main), docs at /api/docs
    /assets/...  the built web app's files
    anything else  the web app (index.html), which does its own routing

    HARDSHIP_WEB_DIR=frontend/dist uvicorn backend.web:app --port 7860

Docker Compose doesn't use this: nginx serves the app and proxies /api there.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.main import app as api

WEB_DIR = Path(os.environ.get("HARDSHIP_WEB_DIR", Path(__file__).resolve().parents[1] / "frontend" / "dist")).resolve()

# A mounted app's startup doesn't run by itself, so borrow the API's.
app = FastAPI(lifespan=api.router.lifespan_context, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api)
if (WEB_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web(path: str):
    file = (WEB_DIR / path).resolve()
    if path and file.is_file() and file.is_relative_to(WEB_DIR):
        return FileResponse(file)
    index = WEB_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(404, f"The web app isn't built: no {index}")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
