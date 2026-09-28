"""Publish the app to its Hugging Face Space, which then installs and restarts it.

    HF_TOKEN=<write token> python deploy/push_space.py --space your-name/hardship-fund

The Space uses the free Gradio SDK as a plain Python runtime: it installs
requirements.txt and packages.txt, then runs app.py, which starts the
platform's FastAPI server (backend/web.py). Gradio Spaces can't build the
web app (no Node.js), so this script builds it here (`npm ci && npm run
build` in frontend/) and uploads the result as web/.

Uploaded: backend/, web/, requirements.txt, and space/app.py,
space/packages.txt and space/README.md at the Space's root. The Space is
public so a client can open it without an account; the app still requires
sign-in, and no data, secrets or models are uploaded: those come from the
Space's secrets, the database and the model repository. The GitHub workflow
.github/workflows/space.yml runs this on every push to main.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "*.log")


def build_web() -> Path:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm not found: install Node.js 20+ to build the web app, or pass --skip-build.")
    front = ROOT / "frontend"
    env = {**os.environ, "VITE_API_BASE": ""}   # same address as the API: /api
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=front, check=True, env=env)
    subprocess.run([npm, "run", "build"], cwd=front, check=True, env=env)
    return front / "dist"


def stage(target: Path, dist: Path) -> None:
    if not (dist / "index.html").is_file():
        sys.exit(f"No built web app in {dist}.")
    shutil.copytree(ROOT / "backend", target / "backend", ignore=SKIP)
    shutil.copytree(dist, target / "web")
    shutil.copy2(ROOT / "requirements.txt", target / "requirements.txt")
    for name in ("app.py", "packages.txt", "README.md"):
        shutil.copy2(ROOT / "space" / name, target / name)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default=os.environ.get("HF_SPACE"), help="owner/name of the Space (or HF_SPACE)")
    ap.add_argument("--message", default="Update from the project repository")
    ap.add_argument("--skip-build", action="store_true", help="use the existing frontend/dist")
    ap.add_argument("--dry-run", action="store_true", help="list what would be uploaded, upload nothing")
    ap.add_argument("--stage-only", metavar="DIR", help="write the Space's files to DIR and stop (for local testing)")
    args = ap.parse_args()
    if not (args.space or args.stage_only):
        sys.exit("Say which Space: --space your-name/hardship-fund (or set HF_SPACE).")

    dist = ROOT / "frontend" / "dist" if args.skip_build else build_web()
    if args.stage_only:
        target = Path(args.stage_only)
        shutil.rmtree(target, ignore_errors=True)
        stage(target, dist)
        print(f"Staged the Space in {target}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        stage(target, dist)
        files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
        if args.dry_run:
            print("\n".join(files))
            print(f"\n{len(files)} files would be uploaded to the Space {args.space}.")
            return

        from huggingface_hub import HfApi
        api = HfApi()   # reads HF_TOKEN
        api.create_repo(args.space, repo_type="space", space_sdk="gradio", private=False, exist_ok=True)
        api.upload_folder(repo_id=args.space, repo_type="space", folder_path=str(target),
                          commit_message=args.message,
                          # drop files removed here, and anything from an older layout
                          delete_patterns=["backend/**", "web/**", "frontend/**", "Dockerfile"])
        print(f"Uploaded {len(files)} files. The Space restarts now: https://huggingface.co/spaces/{args.space}")


if __name__ == "__main__":
    main()
