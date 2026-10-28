import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from handoff.config import Settings
from handoff.context import build_context
from handoff.owner_app import create_owner_app
from handoff.share_app import create_share_app

PASSWORD = "correct horse battery"


def make_env(tmp_path, name="data", gate=False, manager=None, share_client=None, **overrides):
    """`manager` is a function ctx -> ConnectionManager, used to inject fakes before the apps capture it."""
    s = Settings(data_dir=tmp_path / name, min_free_bytes=0, **overrides)
    s.data_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_context(s, gate_sharing=gate)
    if manager:
        ctx.manager = manager(ctx)
    owner = TestClient(create_owner_app(ctx), base_url="http://localhost")
    share = TestClient(create_share_app(ctx), base_url="http://localhost", **(share_client or {}))
    return SimpleNamespace(settings=s, ctx=ctx, owner=owner, share=share)


def sign_in(env):
    r = env.owner.post("/api/setup", json={"username": "owner", "password": PASSWORD})
    assert r.status_code == 200, r.text
    env.owner.headers["X-CSRF-Token"] = r.json()["csrf"]
    return env


@pytest.fixture
def env(tmp_path):
    return sign_in(make_env(tmp_path))


@pytest.fixture
def project(env):
    r = env.owner.post("/api/projects", json={"title": "Brand film"})
    assert r.status_code == 201
    return r.json()["id"]


def upload(env, pid, name, data):
    return env.owner.put(f"/api/projects/{pid}/files", params={"name": name}, content=data)


def make_link(env, pid, **body):
    r = env.owner.post(f"/api/projects/{pid}/links", json=body)
    assert r.status_code == 201, r.text
    return r.json()


PNG = b"\x89PNG\r\n\x1a\n" + os.urandom(2048)
