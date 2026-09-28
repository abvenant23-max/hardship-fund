"""Entry point of the Hugging Face Space (Gradio SDK, which runs `python app.py`
and expects a web server on port 7860). It starts the platform itself: the
built web app plus the API under /api (backend/web.py). Gradio isn't used.
"""
import os
from pathlib import Path

import uvicorn

HERE = Path(__file__).resolve().parent
os.environ.setdefault("HARDSHIP_WEB_DIR", str(HERE / "web"))

if __name__ == "__main__":
    uvicorn.run("backend.web:app", host="0.0.0.0", port=int(os.environ.get("PORT", "7860")),
                proxy_headers=True, forwarded_allow_ips="*")
