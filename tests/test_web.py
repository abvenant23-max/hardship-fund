"""backend/web.py: the web app and the API from one server (the Space)."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "assets" / "index-abc.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("keep out")
    monkeypatch.setenv("HARDSHIP_WEB_DIR", str(tmp_path))
    import backend.web
    return TestClient(importlib.reload(backend.web).app)   # no `with`: the API's startup needs a database


def test_files_and_app_routes(client):
    assert client.get("/assets/index-abc.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    for path in ("/", "/review", "/applications/42"):
        r = client.get(path)
        assert r.text == "<html>app</html>" and r.headers["cache-control"] == "no-cache"


def test_cannot_read_outside_the_app(client):
    assert "keep out" not in client.get("/../secret.txt").text
    assert "keep out" not in client.get("/%2e%2e/secret.txt").text


def test_api_is_under_api(client):
    assert client.get("/api/openapi.json").json()["info"]["title"] == "Household Hardship Platform API"
