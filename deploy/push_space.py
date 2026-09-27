"""Publish the app to its Hugging Face Space, which then builds and restarts it.

    HF_TOKEN=<write token> python deploy/push_space.py --space your-name/hardship-fund

Copies only what the Space needs (backend/, frontend/ without node_modules or
builds, requirements.txt) plus space/Dockerfile and space/README.md to the
Space's root. The Space is public so a client can open it without an
account; the app itself still requires sign-in, and no data, secrets or
models are uploaded: those come from the Space's secrets, the database and
the model repository. The GitHub workflow .github/workflows/space.yml runs
this on every push to main.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", "dist", ".env*", "*.log",
                              "*.tsbuildinfo", ".vite", "coverage")


def stage(target: Path) -> None:
    shutil.copytree(ROOT / "backend", target / "backend", ignore=SKIP)
    shutil.copytree(ROOT / "frontend", target / "frontend", ignore=SKIP)
    shutil.copy2(ROOT / "requirements.txt", target / "requirements.txt")
    shutil.copy2(ROOT / "space" / "Dockerfile", target / "Dockerfile")
    shutil.copy2(ROOT / "space" / "README.md", target / "README.md")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space", default=os.environ.get("HF_SPACE"), help="owner/name of the Space (or HF_SPACE)")
    ap.add_argument("--message", default="Update from the project repository")
    ap.add_argument("--dry-run", action="store_true", help="list what would be uploaded, upload nothing")
    args = ap.parse_args()
    if not args.space:
        sys.exit("Say which Space: --space your-name/hardship-fund (or set HF_SPACE).")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        stage(target)
        files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
        if args.dry_run:
            print("\n".join(files))
            print(f"\n{len(files)} files would be uploaded to the Space {args.space}.")
            return

        from huggingface_hub import HfApi
        api = HfApi()   # reads HF_TOKEN
        api.create_repo(args.space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
        api.upload_folder(repo_id=args.space, repo_type="space", folder_path=str(target),
                          commit_message=args.message,
                          delete_patterns=["backend/**", "frontend/**"])   # drop files removed here
        print(f"Uploaded {len(files)} files. The Space rebuilds now: https://huggingface.co/spaces/{args.space}")


if __name__ == "__main__":
    main()
