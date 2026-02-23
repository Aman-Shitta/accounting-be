from django.db import connection


class QueryHelper:

    @staticmethod
    def _fetch_one(query, params):
        """Execute a query that returns a single row, return as dict."""
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row)) if row else {}

    @staticmethod
    def _fetch_all(query, params):
        """Execute a query that returns multiple rows, return as list of dicts."""
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _status_dict(rows, count_key="count"):
        """Convert a list of {status, count} rows into a flat {status: count} dict."""
        return {row["status"]: row[count_key] for row in rows}


class RawSQLMixin:

    def __init__(self):
        querier = QueryHelper()
        self._fetch_one = querier._fetch_one
        self._fetch_all = querier._fetch_all
        self._status_dict = querier._status_dict
        