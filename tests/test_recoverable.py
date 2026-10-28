import os

from handoff.__main__ import backup
from handoff.context import build_context
from handoff.keys import KeyStore

from .conftest import make_env, make_link, sign_in, upload


def test_link_secret_is_stored_encrypted_and_can_be_copied_again(env, project):
    link = make_link(env, project)
    token = link["token"]
    row = env.ctx.db.one("SELECT token_hash, token_enc FROM share_links WHERE id = ?", (link["id"],))
    assert row["token_enc"] and token not in row["token_enc"]  # ciphertext, not the secret
    again = env.owner.get(f"/api/links/{link['id']}/url")
    assert again.status_code == 200
    assert again.json()["url"] == link["url"] == f"{env.settings.share_base()}/s/{token}"
    assert env.share.get(f"/s/{token}").status_code == 200  # visitors are still looked up by hash


def test_project_listing_reports_which_links_can_be_copied(env, project):
    make_link(env, project)
    links = env.owner.get(f"/api/projects/{project}").json()["links"]
    assert links[0]["recoverable"] is True


def test_changed_or_missing_key_means_link_cannot_be_shown_but_still_works(env, project):
    link = make_link(env, project)
    env.ctx.keys = KeyStore(env.settings.data_dir / "other-keys")  # as after a restore onto a fresh install
    r = env.owner.get(f"/api/links/{link['id']}/url")
    assert r.status_code == 409 and "Create a new link" in r.json()["detail"]
    assert env.share.get(f"/s/{link['token']}").status_code == 200  # the link already sent keeps working
    assert env.owner.get(f"/api/projects/{project}").json()["links"][0]["recoverable"] is False


def test_links_created_before_this_feature_cannot_be_shown(env, project):
    link = make_link(env, project)
    env.ctx.db.execute("UPDATE share_links SET token_enc = NULL WHERE id = ?", (link["id"],))
    assert env.owner.get(f"/api/links/{link['id']}/url").status_code == 409


def test_revoked_link_cannot_be_copied(env, project):
    link = make_link(env, project)
    env.owner.delete(f"/api/links/{link['id']}")
    assert env.owner.get(f"/api/links/{link['id']}/url").status_code == 409


def test_backup_never_contains_keys_or_plaintext_link_secrets(env, project, tmp_path):
    link = make_link(env, project)
    upload(env, project, "a.bin", os.urandom(3000))
    dest = tmp_path / "bk"
    assert backup(env.settings, dest) == 0
    names = {p.name for p in dest.rglob("*") if p.is_file()}
    assert "link.key" not in names and "secret.key" not in names
    snapshot = (dest / "db" / "handoff.sqlite3").read_bytes()
    assert link["token"].encode() not in snapshot
    assert env.settings.key_dir.exists() and (env.settings.key_dir / "link.key").exists()
    assert not any(p.is_relative_to(env.settings.key_dir) for p in dest.rglob("*"))


def test_keys_live_outside_the_files_and_database_folders(env):
    assert not env.settings.key_dir.is_relative_to(env.settings.files_dir)
    assert not env.settings.key_dir.is_relative_to(env.settings.db_path.parent)


def test_key_dir_can_live_outside_the_data_folder(tmp_path):
    from handoff.config import Settings

    s = Settings(data_dir=tmp_path / "data", min_free_bytes=0, key_dir_override=tmp_path / "elsewhere")
    s.data_dir.mkdir()
    ctx = build_context(s)
    ctx.keys.encrypt_token("x")
    assert (tmp_path / "elsewhere" / "link.key").exists()
    assert not (s.data_dir / "keys").exists() or not any((s.data_dir / "keys").glob("link.key"))


def test_legacy_signing_secret_is_moved_out_of_the_database_folder(tmp_path):
    from handoff.config import Settings

    s = Settings(data_dir=tmp_path / "data", min_free_bytes=0)
    (s.data_dir / "db").mkdir(parents=True)
    s.legacy_secret_path.write_bytes(b"x" * 32)
    build_context(s)
    assert not s.legacy_secret_path.exists()
    assert s.secret_path.read_bytes() == b"x" * 32
