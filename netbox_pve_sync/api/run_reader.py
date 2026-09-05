"""Read-only PostgreSQL adapter for synchronization history."""

import psycopg

from ..run_history import RunRepository


class PostgresRunReader:
    """Expose only list/detail through a transaction-read-only connection."""

    def __init__(self, settings, connector=psycopg.connect):
        self._settings = settings
        self._connector = connector

    def _repository(self):
        if not self._settings.registry_dsn:
            raise RuntimeError('history unavailable')

        def connect():
            connection = self._connector(
                self._settings.registry_dsn, connect_timeout=3,
                options='-c statement_timeout=2000 -c default_transaction_read_only=on',
            )
            connection.read_only = True
            return connection
        return RunRepository(connect, self._settings.registry_schema)

    def list_runs(self, **filters):
        """Read bounded newest-first history."""
        return self._repository().list_runs(**filters)

    def get_run(self, run_id):
        """Read one public UUID."""
        return self._repository().get_run(run_id)
