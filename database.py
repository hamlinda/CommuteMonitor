from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS travel_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at TEXT NOT NULL,
    route_key TEXT,
    route_name TEXT,
    origin_label TEXT NOT NULL,
    destination_label TEXT NOT NULL,
    origin_address TEXT NOT NULL,
    destination_address TEXT NOT NULL,
    origin_lat REAL,
    origin_lon REAL,
    destination_lat REAL,
    destination_lon REAL,
    duration_seconds REAL,
    duration_minutes REAL,
    distance_meters REAL,
    distance_km REAL,
    distance_miles REAL,
    route_summary TEXT,
    route_geometry_json TEXT,
    status TEXT NOT NULL DEFAULT 'success',
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_travel_samples_collected_at
    ON travel_samples (collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_travel_samples_status
    ON travel_samples (status);
"""


@dataclass(frozen=True)
class TravelSample:
    collected_at: str
    route_key: str
    route_name: str
    origin_label: str
    destination_label: str
    origin_address: str
    destination_address: str
    origin_lat: float | None
    origin_lon: float | None
    destination_lat: float | None
    destination_lon: float | None
    duration_seconds: float | None
    duration_minutes: float | None
    distance_meters: float | None
    distance_km: float | None
    distance_miles: float | None
    route_summary: str | None
    route_geometry_json: str | None
    status: str
    error_message: str | None = None


def _table_columns(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("PRAGMA table_info(travel_samples)").fetchall()
    return {str(row[1]) for row in rows}


def _add_column_if_missing(
    connection: sqlite3.Connection,
    columns: set[str],
    column_name: str,
    column_definition: str,
) -> None:
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE travel_samples ADD COLUMN {column_definition}"
        )


def migrate_schema(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection)
    _add_column_if_missing(connection, columns, "route_key", "route_key TEXT")
    _add_column_if_missing(
        connection,
        columns,
        "route_name",
        "route_name TEXT",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_travel_samples_route_key_collected_at "
        "ON travel_samples (route_key, collected_at DESC)"
    )
    connection.execute(
        "PRAGMA user_version = 1"
    )


def backfill_route_metadata(
    db_path: str | Path,
    route_key: str,
    route_name: str,
) -> int:
    connection = open_connection(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE travel_samples
            SET route_key = ?, route_name = ?
            WHERE (route_key IS NULL OR route_key = '')
              AND (route_name IS NULL OR route_name = '')
            """,
            (route_key, route_name),
        )
        connection.commit()
        return int(cursor.rowcount)
    finally:
        connection.close()


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: str | Path) -> None:
    connection = open_connection(db_path)
    try:
        connection.executescript(SCHEMA_SQL)
        migrate_schema(connection)
        connection.commit()
    finally:
        connection.close()


def insert_sample(db_path: str | Path, sample: TravelSample) -> int:
    connection = open_connection(db_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO travel_samples (
                collected_at,
                route_key,
                route_name,
                origin_label,
                destination_label,
                origin_address,
                destination_address,
                origin_lat,
                origin_lon,
                destination_lat,
                destination_lon,
                duration_seconds,
                duration_minutes,
                distance_meters,
                distance_km,
                distance_miles,
                route_summary,
                route_geometry_json,
                status,
                error_message
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                sample.collected_at,
                sample.route_key,
                sample.route_name,
                sample.origin_label,
                sample.destination_label,
                sample.origin_address,
                sample.destination_address,
                sample.origin_lat,
                sample.origin_lon,
                sample.destination_lat,
                sample.destination_lon,
                sample.duration_seconds,
                sample.duration_minutes,
                sample.distance_meters,
                sample.distance_km,
                sample.distance_miles,
                sample.route_summary,
                sample.route_geometry_json,
                sample.status,
                sample.error_message,
            ),
        )
        connection.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("SQLite did not return a row id")
        return int(row_id)
    finally:
        connection.close()


def prune_old_records(db_path: str | Path, retention_days: int) -> int:
    connection = open_connection(db_path)
    try:
        cursor = connection.execute(
            (
                "DELETE FROM travel_samples "
                "WHERE collected_at < datetime('now', ?)"
            ),
            (f'-{int(retention_days)} days',),
        )
        connection.commit()
        return int(cursor.rowcount)
    finally:
        connection.close()


def delete_samples_for_route(db_path: str | Path, route_key: str) -> int:
    """Delete all samples for a given route key."""
    connection = open_connection(db_path)
    try:
        cursor = connection.execute(
            "DELETE FROM travel_samples WHERE route_key = ?",
            (route_key,),
        )
        connection.commit()
        return int(cursor.rowcount)
    finally:
        connection.close()


def fetch_samples(
    db_path: str | Path,
    retention_days: int = 7,
    only_successful: bool = True,
    route_key: str | None = None,
) -> list[dict[str, Any]]:
    where_clauses = ["collected_at >= datetime('now', ?)"]
    parameters: list[Any] = [f'-{int(retention_days)} days']
    if only_successful:
        where_clauses.append("status = 'success'")
    if route_key is not None:
        where_clauses.append("route_key = ?")
        parameters.append(route_key)
    query = f"""
        SELECT *
        FROM travel_samples
        WHERE {' AND '.join(where_clauses)}
        ORDER BY id DESC
    """
    connection = open_connection(db_path)
    try:
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def fetch_latest_sample(
    db_path: str | Path,
    route_key: str | None = None,
) -> dict[str, Any] | None:
    connection = open_connection(db_path)
    try:
        if route_key is None:
            row = connection.execute(
                """
                SELECT *
                FROM travel_samples
                WHERE status = 'success'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT *
                FROM travel_samples
                WHERE status = 'success'
                  AND route_key = ?
                                ORDER BY id DESC
                LIMIT 1
                """,
                (route_key,),
            ).fetchone()
    finally:
        connection.close()
    return dict(row) if row else None


def fetch_route_latest_samples(
    db_path: str | Path,
    retention_days: int = 7,
) -> list[dict[str, Any]]:
    connection = open_connection(db_path)
    try:
        rows = connection.execute(
            """
            SELECT ts.*
            FROM travel_samples AS ts
            INNER JOIN (
                SELECT
                    COALESCE(route_key, '') AS route_key_group,
                                        MAX(id) AS latest_id
                FROM travel_samples
                WHERE collected_at >= datetime('now', ?)
                  AND status = 'success'
                GROUP BY COALESCE(route_key, '')
            ) AS latest
                        ON COALESCE(ts.route_key, '') = latest.route_key_group
                        AND ts.id = latest.latest_id
            WHERE ts.collected_at >= datetime('now', ?)
              AND ts.status = 'success'
                        ORDER BY ts.id DESC
            """,
            (f'-{int(retention_days)} days', f'-{int(retention_days)} days'),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def fetch_fastest_commute_for_timeframe(
    db_path: str | Path,
    retention_days: int = 7,
    route_key: str | None = None,
    weekdays: list[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any] | None:
    where_clauses = [
        "collected_at >= datetime('now', ?)",
        "status = 'success'",
    ]
    parameters: list[Any] = [f'-{int(retention_days)} days']

    if route_key is not None:
        where_clauses.append("route_key = ?")
        parameters.append(route_key)

    if weekdays:
        weekday_values = []
        for weekday in weekdays:
            weekday_name = str(weekday).strip().title()
            mapping = {
                "Monday": "1",
                "Tuesday": "2",
                "Wednesday": "3",
                "Thursday": "4",
                "Friday": "5",
                "Saturday": "6",
                "Sunday": "0",
            }
            if weekday_name in mapping:
                weekday_values.append(mapping[weekday_name])
        if weekday_values:
            placeholders = ", ".join("?" for _ in weekday_values)
            where_clauses.append(
                f"CAST(strftime('%w', collected_at) AS INTEGER) IN ({placeholders})"
            )
            parameters.extend(weekday_values)

    if start_time:
        start = str(start_time).strip()
        if start:
            where_clauses.append("time(collected_at) >= ?")
            parameters.append(start)
    if end_time:
        end = str(end_time).strip()
        if end:
            where_clauses.append("time(collected_at) <= ?")
            parameters.append(end)

    query = f"""
        SELECT
            collected_at,
            route_key,
            route_name,
            origin_label,
            destination_label,
            duration_minutes
        FROM travel_samples
        WHERE {' AND '.join(where_clauses)}
        ORDER BY duration_minutes ASC, id DESC
        LIMIT 1
    """

    connection = open_connection(db_path)
    try:
        row = connection.execute(query, parameters).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return dict(row)


def fetch_summary_stats(
    db_path: str | Path,
    retention_days: int = 7,
    route_key: str | None = None,
) -> dict[str, float | None]:
    route_clause = ""
    route_parameters: list[Any] = []
    if route_key is not None:
        route_clause = " AND route_key = ?"
        route_parameters.append(route_key)
    connection = open_connection(db_path)
    try:
        query = f"""
            SELECT
                MIN(duration_minutes) AS fastest,
                MAX(duration_minutes) AS slowest,
                AVG(duration_minutes) AS average,
                COUNT(*) AS total_samples,
                MAX(collected_at) AS latest_collected_at
            FROM travel_samples
            WHERE collected_at >= datetime('now', ?)
              AND status = 'success'{route_clause}
        """
        row = connection.execute(
            query,
            [f'-{int(retention_days)} days', *route_parameters],
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return {
            "fastest": None,
            "slowest": None,
            "average": None,
            "total_samples": 0,
            "latest_collected_at": None,
        }
    return {
        "fastest": row["fastest"],
        "slowest": row["slowest"],
        "average": row["average"],
        "total_samples": row["total_samples"],
        "latest_collected_at": row["latest_collected_at"],
    }


def fetch_daily_summary(
    db_path: str | Path,
    retention_days: int = 7,
    route_key: str | None = None,
) -> list[dict[str, Any]]:
    route_clause = ""
    route_parameters: list[Any] = []
    if route_key is not None:
        route_clause = " AND route_key = ?"
        route_parameters.append(route_key)
    connection = open_connection(db_path)
    try:
        query = f"""
            SELECT
                date(collected_at) AS date,
                strftime('%w', collected_at) AS weekday_index,
                strftime('%W', collected_at) AS week_index,
                COUNT(*) AS samples,
                ROUND(AVG(duration_minutes), 2) AS avg_duration_minutes,
                ROUND(MIN(duration_minutes), 2) AS min_duration_minutes,
                ROUND(MAX(duration_minutes), 2) AS max_duration_minutes,
                ROUND(AVG(distance_km), 2) AS avg_distance_km,
                ROUND(AVG(distance_miles), 2) AS avg_distance_miles
            FROM travel_samples
            WHERE collected_at >= datetime('now', ?)
              AND status = 'success'{route_clause}
            GROUP BY date(collected_at), weekday_index, week_index
            ORDER BY date(collected_at) DESC
        """
        rows = connection.execute(
            query,
            [f'-{int(retention_days)} days', *route_parameters],
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def get_route_activity(
    db_path: str | Path,
    retention_days: int = 7,
) -> list[dict[str, Any]]:
    connection = open_connection(db_path)
    try:
        rows = connection.execute(
            """
            SELECT
                COALESCE(route_key, '') AS route_key,
                COALESCE(route_name, 'Legacy route') AS route_name,
                origin_label,
                destination_label,
                MAX(collected_at) AS latest_collected_at,
                ROUND(MIN(duration_minutes), 2) AS fastest_minutes,
                ROUND(MAX(duration_minutes), 2) AS slowest_minutes,
                ROUND(AVG(duration_minutes), 2) AS average_minutes,
                COUNT(*) AS samples
            FROM travel_samples
            WHERE collected_at >= datetime('now', ?)
              AND status = 'success'
                        GROUP BY
                                COALESCE(route_key, ''),
                                COALESCE(route_name, 'Legacy route')
            ORDER BY latest_collected_at DESC
            """,
            (f'-{int(retention_days)} days',),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def export_rows(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2, sort_keys=True)
