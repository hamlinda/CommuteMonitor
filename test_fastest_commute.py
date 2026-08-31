from __future__ import annotations

from datetime import datetime, timedelta

import database


def test_fetch_latest_sample_for_route_key(tmp_path):
    db_path = tmp_path / "travel_data.db"
    database.initialize_database(db_path)

    older = "2026-08-01T08:00:00"
    newer = "2026-08-02T08:30:00"

    for route_key, collected_at, duration in [
        ("route-1", older, 20.0),
        ("route-2", newer, 11.5),
    ]:
        database.insert_sample(
            db_path,
            database.TravelSample(
                collected_at=collected_at,
                route_key=route_key,
                route_name=f"Route {route_key[-1]}",
                origin_label="Home",
                destination_label="Office",
                origin_address="Home address",
                destination_address="Office address",
                origin_lat=None,
                origin_lon=None,
                destination_lat=None,
                destination_lon=None,
                duration_seconds=duration * 60,
                duration_minutes=duration,
                distance_meters=1200,
                distance_km=1.2,
                distance_miles=0.75,
                route_summary="ok",
                route_geometry_json='{"type":"LineString","coordinates":[[-97.7,30.3],[-97.8,30.4]]}',
                status="success",
                error_message=None,
            ),
        )

    result = database.fetch_latest_sample(db_path, route_key="route-2")

    assert result is not None
    assert result["route_key"] == "route-2"
    assert result["duration_minutes"] == 11.5


def test_fetch_fastest_commute_for_weekday_time_window(tmp_path):
    db_path = tmp_path / "travel_data.db"
    database.initialize_database(db_path)

    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    tuesday = monday + timedelta(days=1)

    samples = [
        {
            "collected_at": (monday + timedelta(hours=8, minutes=15)).strftime("%Y-%m-%dT%H:%M:%S"),
            "route_key": "route-1",
            "route_name": "Route 1",
            "origin_label": "Home",
            "destination_label": "Office",
            "origin_address": "Home address",
            "destination_address": "Office address",
            "origin_lat": None,
            "origin_lon": None,
            "destination_lat": None,
            "destination_lon": None,
            "duration_seconds": 900,
            "duration_minutes": 15.0,
            "distance_meters": 2000,
            "distance_km": 2.0,
            "distance_miles": 1.2,
            "route_summary": "ok",
            "route_geometry_json": None,
            "status": "success",
            "error_message": None,
        },
        {
            "collected_at": (monday + timedelta(hours=9, minutes=20)).strftime("%Y-%m-%dT%H:%M:%S"),
            "route_key": "route-1",
            "route_name": "Route 1",
            "origin_label": "Home",
            "destination_label": "Office",
            "origin_address": "Home address",
            "destination_address": "Office address",
            "origin_lat": None,
            "origin_lon": None,
            "destination_lat": None,
            "destination_lon": None,
            "duration_seconds": 690,
            "duration_minutes": 11.5,
            "distance_meters": 1800,
            "distance_km": 1.8,
            "distance_miles": 1.1,
            "route_summary": "ok",
            "route_geometry_json": None,
            "status": "success",
            "error_message": None,
        },
        {
            "collected_at": (tuesday + timedelta(hours=7, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"),
            "route_key": "route-1",
            "route_name": "Route 1",
            "origin_label": "Home",
            "destination_label": "Office",
            "origin_address": "Home address",
            "destination_address": "Office address",
            "origin_lat": None,
            "origin_lon": None,
            "destination_lat": None,
            "destination_lon": None,
            "duration_seconds": 600,
            "duration_minutes": 10.0,
            "distance_meters": 1700,
            "distance_km": 1.7,
            "distance_miles": 1.05,
            "route_summary": "ok",
            "route_geometry_json": None,
            "status": "success",
            "error_message": None,
        },
    ]

    for sample in samples:
        database.insert_sample(
            db_path,
            database.TravelSample(
                collected_at=sample["collected_at"],
                route_key=sample["route_key"],
                route_name=sample["route_name"],
                origin_label=sample["origin_label"],
                destination_label=sample["destination_label"],
                origin_address=sample["origin_address"],
                destination_address=sample["destination_address"],
                origin_lat=sample["origin_lat"],
                origin_lon=sample["origin_lon"],
                destination_lat=sample["destination_lat"],
                destination_lon=sample["destination_lon"],
                duration_seconds=sample["duration_seconds"],
                duration_minutes=sample["duration_minutes"],
                distance_meters=sample["distance_meters"],
                distance_km=sample["distance_km"],
                distance_miles=sample["distance_miles"],
                route_summary=sample["route_summary"],
                route_geometry_json=sample["route_geometry_json"],
                status=sample["status"],
                error_message=sample["error_message"],
            ),
        )

    result = database.fetch_fastest_commute_for_timeframe(
        db_path,
        retention_days=30,
        route_key="route-1",
        weekdays=["Monday", "Tuesday"],
        start_time="08:00",
        end_time="10:00",
    )

    assert result is not None
    assert result["duration_minutes"] == 11.5
    assert result["collected_at"].startswith((monday + timedelta(hours=9, minutes=20)).strftime("%Y-%m-%dT"))
