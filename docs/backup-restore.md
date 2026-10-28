# Backup and restore

Everything Handoff stores is in one folder, `data`. The desktop app keeps it in `%LOCALAPPDATA%\Handoff\data` (Windows); server mode uses `./data` (or `DATA_DIR`).

```
data/
  db/handoff.sqlite3     project records, link hashes, file records (never file contents)
  files/<project>/<file> the original files, exactly as uploaded
  incoming/              uploads in progress (safe to ignore)
  backups/               automatic database snapshots taken before upgrades
```

## Keys are never backed up

Handoff keeps the encryption key that lets it show a link's full text again (and its cookie-signing secret) in a separate `keys` folder. **Backups deliberately exclude it**, so a copied backup can't unlock stored link secrets. In the desktop app, `keys` sits next to `data`, not inside it. In server mode, `keys` is inside `data` by default; set `KEY_DIR` to move it, and don't copy it into backups.

The cost: after you restore onto a new install, links you already sent **keep working**, but Handoff can't show their text again, so "Copy link" says to create a new link.

## Why this is simple

Original files are **write-once**: once stored they never change. So copying `files/` with any tool is safe while the app runs. The database is different: copy it only with the command below, not by copying the file, because SQLite keeps recent changes in a side file while running.

## Back up

**Everything into a folder on another drive** (works while the app is running):

```bash
python -m handoff backup /path/to/backup-drive/handoff
```

Run it again later: files already copied are skipped, so it is fast.

**Database only**, if you copy `data/files/` yourself with a file manager (avoids storing every file twice):

```bash
python -m handoff backup /path/to/backup-drive/handoff --db-only
```

Each backup includes `MANIFEST.sha256`. To check a backup later, run `sha256sum -c MANIFEST.sha256` inside the backup folder.

## Restore

1. Quit Handoff.
2. Make sure `data` is empty or a copy you can discard.
3. Restore: `python -m handoff restore /path/to/backup-drive/handoff` (add `--force` to replace an existing database).
4. Start Handoff.
5. Check integrity: `python -m handoff verify`.

Share links keep working after a restore, because only their hashes are stored. If your public address changed, send clients the new address; the secret part of each link is unchanged but the links you copied earlier still contain the old address.

## Upgrades

Replace the app with the new version. Before changing the database layout it saves a snapshot in `data/backups/`. Going back to an older version is not supported; restore a backup instead.

## If a file goes missing

At startup the app compares the database with the disk. A record whose file is gone is marked missing and hidden from clients. Run `python -m handoff verify` to see which, and `verify --fix` after you put the file back.
