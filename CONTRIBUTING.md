# Contributing

Thanks for helping. Handoff is deliberately small: a FastAPI backend, SQLite for records, local disk for files, and plain HTML/JavaScript pages. Please keep it that way.

## Ground rules

- **Originals are never modified.** No transcoding, resizing, watermarking or metadata stripping of stored or downloaded files.
- **No required external service**: no paid domain, cloud storage, database server, queue or payment gateway.
- **Never execute uploaded code** on the host.
- Keep runtime dependencies minimal. Adding one needs a reason in the pull request.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

Add a test for every behaviour you change. Security-relevant routes (anything under `/s/`) need a test that a revoked, expired or view-only link cannot reach the data.

## Licensing (open decision)

The project has no license yet, so please **wait to open large pull requests** until one is chosen; code contributed without a license can't be used. Once decided, contributions will be accepted under that license with a sign-off (`git commit -s`).
