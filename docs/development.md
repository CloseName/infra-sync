# Development

Use Python 3.12 (current image) or 3.13 (current CI). Keep the production CLI
entrypoint and existing tests intact. From repository root:

```sh
python -m pip install -e .
python -m pip install -r requirements-dev.txt
pytest -q
pylint --fail-under=9.0 --max-line-length=120 netbox_sync
git diff --check
```

New application contracts use only the standard library. Alembic/SQLAlchemy are
development/operator tools installed by requirements-dev.txt, not added to the
sync image's dependencies. Migration revisions ship in the repository; invoke
them from that checkout, not from a separately installed legacy PyPI package.
Package discovery explicitly includes only `netbox_sync*`, preventing deploy
and migration directories from becoming accidental Python distributions.

Normal tests use fakes, never a production source or NetBox. Live ESXi and
PostgreSQL tests remain opt-in. See [WEB-1 development and deployment](web.md)
for the optional API/frontend, and [architecture](architecture.md) and
[migrations](migrations.md) for runtime and database boundaries.
