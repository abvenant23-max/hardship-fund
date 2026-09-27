"""Optional remote copy of the model artifacts on the Hugging Face Hub.

Hosts like Render wipe a service's disk on every deploy and restart, so
models/<version>/ can't live only on disk there. When HARDSHIP_MODEL_REPO
is set (e.g. "your-name/hardship-models", best kept private), every saved
version is also uploaded to that repository under <version>/, and a
version missing on disk is downloaded from it the first time it is needed.
Uploading and reading a private repository need a token in HF_TOKEN.

Unset, nothing changes: artifacts stay on the local disk only.
"""
from __future__ import annotations

import os
from pathlib import Path


def repo_id() -> str | None:
    return os.environ.get("HARDSHIP_MODEL_REPO") or None


def publish(directory: Path) -> str | None:
    """Upload one version's folder. Returns the repository, or None when no
    repository is configured."""
    repo = repo_id()
    if repo is None:
        return None
    from huggingface_hub import HfApi   # only needed when a repository is configured

    api = HfApi()
    api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
    api.upload_folder(repo_id=repo, repo_type="model", folder_path=str(directory),
                      path_in_repo=directory.name, commit_message=f"Add model {directory.name}")
    return repo


def fetch(directory: Path) -> Path:
    """Make sure a version's folder is on disk, downloading it if needed."""
    if (directory / "metadata.json").exists():
        return directory
    repo = repo_id()
    if repo is None:
        raise FileNotFoundError(
            f"Model files for '{directory.name}' are not in {directory.parent} and no model repository "
            f"is configured (HARDSHIP_MODEL_REPO). Retrain, or restore the folder.")
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=repo, repo_type="model", allow_patterns=[f"{directory.name}/*"],
                      local_dir=str(directory.parent))
    if not (directory / "metadata.json").exists():
        raise FileNotFoundError(f"Model '{directory.name}' is not in the model repository {repo}.")
    return directory
