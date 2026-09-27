"""The optional model repository (backend/ml/store.py), with the Hugging Face
calls replaced by local copies."""
import shutil
import sys
import types

import pytest

from backend.ml import store


def make_version(root, name="lgbm-test"):
    d = root / name
    d.mkdir(parents=True)
    (d / "metadata.json").write_text("{}")
    (d / "mid.txt").write_text("model")
    return d


def test_without_a_repository_nothing_is_uploaded(tmp_path, monkeypatch):
    monkeypatch.delenv("HARDSHIP_MODEL_REPO", raising=False)
    d = make_version(tmp_path)
    assert store.publish(d) is None
    assert store.fetch(d) == d


def test_missing_folder_without_a_repository_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.delenv("HARDSHIP_MODEL_REPO", raising=False)
    with pytest.raises(FileNotFoundError, match="HARDSHIP_MODEL_REPO"):
        store.fetch(tmp_path / "lgbm-gone")


@pytest.fixture
def fake_hub(tmp_path, monkeypatch):
    """A stand-in for huggingface_hub that keeps the 'repository' in a folder."""
    remote = tmp_path / "remote"
    calls = []

    class HfApi:
        def create_repo(self, repo, **kw):
            calls.append(("create", repo, kw.get("private")))

        def upload_folder(self, repo_id, folder_path, path_in_repo, **kw):
            shutil.copytree(folder_path, remote / path_in_repo)
            calls.append(("upload", repo_id, path_in_repo))

    def snapshot_download(repo_id, allow_patterns, local_dir, **kw):
        name = allow_patterns[0].split("/")[0]
        if (remote / name).exists():
            shutil.copytree(remote / name, f"{local_dir}/{name}")
        calls.append(("download", repo_id, name))

    monkeypatch.setitem(sys.modules, "huggingface_hub",
                        types.SimpleNamespace(HfApi=HfApi, snapshot_download=snapshot_download))
    monkeypatch.setenv("HARDSHIP_MODEL_REPO", "someone/hardship-models")
    return remote, calls


def test_publish_then_fetch_on_a_fresh_disk(tmp_path, fake_hub):
    remote, calls = fake_hub
    d = make_version(tmp_path / "laptop")
    assert store.publish(d) == "someone/hardship-models"
    assert ("create", "someone/hardship-models", True) in calls   # private by default

    server = tmp_path / "server" / "models"
    server.mkdir(parents=True)
    got = store.fetch(server / "lgbm-test")
    assert (got / "mid.txt").read_text() == "model"
    store.fetch(server / "lgbm-test")                               # second time: already on disk
    assert sum(c[0] == "download" for c in calls) == 1


def test_fetch_of_an_unknown_version(tmp_path, fake_hub):
    with pytest.raises(FileNotFoundError, match="not in the model repository"):
        store.fetch(tmp_path / "lgbm-never-uploaded")


def test_database_urls_name_the_installed_driver():
    from backend.ml.db import sqlalchemy_url
    assert sqlalchemy_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg2://u:p@h:5432/d"
    assert sqlalchemy_url("postgres://u:p@h/d") == "postgresql+psycopg2://u:p@h/d"   # older scheme some hosts use
    assert sqlalchemy_url("postgresql+psycopg2://u@h/d") == "postgresql+psycopg2://u@h/d"
