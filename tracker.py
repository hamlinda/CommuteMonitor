from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml
from apscheduler.schedulers.background import BackgroundScheduler

import database


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
UTC = timezone.utc
AUSTIN_TIMEZONE = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class Location:
    label: str
    address: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RouteSample:
    route_key: str
    route_name: str
    collected_at: str
    origin: Location
    destination: Location
    duration_seconds: float
    distance_meters: float
    route_summary: str
    route_geometry_json: str

    @property
    def duration_minutes(self) -> float:
        return round(self.duration_seconds / 60.0, 2)

    @property
    def distance_km(self) -> float:
        return round(self.distance_meters / 1000.0, 2)

    @property
    def distance_miles(self) -> float:
        return round(self.distance_meters / 1609.344, 2)


def load_config(config_path: str | Path) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    app_config = config.setdefault("app", {})
    app_config.setdefault("port", 8585)
    app_config.setdefault("interval_seconds", 1800)
    app_config.setdefault("retention_days", 7)
    app_config.setdefault("database_path", "travel_data.db")
    app_config.setdefault("timezone", "America/Chicago")
    tracking = config.setdefault("tracking", {})
    tracking.setdefault("routing_profile", "driving")
    tracking.setdefault(
        "user_agent",
        "CommuteMonitor/1.0 (local travel tracker)",
    )
    tracking.setdefault("nominatim_email", None)
    tracking.setdefault("routing_provider", "tomtom")
    tracking.setdefault("tomtom_api_key", os.getenv("TOMTOM_API_KEY"))
    tracking.setdefault("routes", [])
    if not tracking["routes"] and (
        tracking.get("origin") or tracking.get("destination")
    ):
        tracking["routes"] = [
            {
                "name": "Legacy route",
                "origin": tracking.get("origin", {}),
                "destination": tracking.get("destination", {}),
                "routing_profile": tracking.get("routing_profile", "driving"),
            }
        ]
    tracking.pop("origin", None)
    tracking.pop("destination", None)
    return config


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "route"


def normalize_route_definition(
    route_config: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    origin = route_config.get("origin") or {}
    destination = route_config.get("destination") or {}
    route_name = str(
        route_config.get("name")
        or (
            f"{origin.get('label', 'Origin')} to "
            f"{destination.get('label', 'Destination')}"
        )
    )
    route_key = str(route_config.get("key") or slugify(route_name))
    if not route_key:
        route_key = f"route-{index + 1}"
    return {
        "key": route_key,
        "name": route_name,
        "origin": origin,
        "destination": destination,
        "routing_profile": str(route_config.get("routing_profile", "driving")),
    }


def get_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    tracking = config.setdefault("tracking", {})
    routes = tracking.get("routes") or []
    normalized = [
        normalize_route_definition(route, index)
        for index, route in enumerate(routes)
    ]
    if len(normalized) > 3:
        logging.warning(
            (
                "Only the first 3 routes will be tracked; ignoring %s extra "
                "route(s)"
            ),
            len(normalized) - 3,
        )
        normalized = normalized[:3]
    return normalized


def set_routes(config: dict[str, Any], routes: list[dict[str, Any]]) -> None:
    tracking = config.setdefault("tracking", {})
    tracking["routes"] = routes
    if routes:
        tracking["origin"] = routes[0]["origin"]
        tracking["destination"] = routes[0]["destination"]
    else:
        tracking.pop("origin", None)
        tracking.pop("destination", None)


def save_config(config_path: str | Path, config: dict[str, Any]) -> None:
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


def current_timestamp() -> str:
    return datetime.now(AUSTIN_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def build_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    return session


def geocode_location(
    session: requests.Session,
    query: str,
    email: str | None = None,
) -> tuple[float, float]:
    params = {"q": query, "format": "jsonv2", "limit": 1}
    if email:
        params["email"] = email
    response = session.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise ValueError(f"No geocoding results found for '{query}'")
    match = results[0]
    return float(match["lat"]), float(match["lon"])


def resolve_location(
    session: requests.Session,
    location_config: dict[str, Any],
    email: str | None = None,
) -> Location:
    label = str(
        location_config.get("label")
        or location_config.get("address")
        or "Unknown location"
    )
    address = str(location_config.get("address") or label)
    latitude = location_config.get("latitude")
    longitude = location_config.get("longitude")
    if latitude is None or longitude is None:
        latitude, longitude = geocode_location(session, address, email=email)
    return Location(
        label=label,
        address=address,
        latitude=float(latitude),
        longitude=float(longitude),
    )


def fetch_route(
    session: requests.Session,
    origin: Location,
    destination: Location,
    routing_profile: str,
    routing_provider: str,
    tomtom_api_key: str | None = None,
) -> dict[str, Any]:
    provider = str(routing_provider or "osrm").strip().lower()
    if provider == "tomtom":
        return fetch_route_tomtom(
            session=session,
            origin=origin,
            destination=destination,
            routing_profile=routing_profile,
            tomtom_api_key=tomtom_api_key,
        )
    return fetch_route_osrm(session, origin, destination, routing_profile)


def fetch_route_osrm(
    session: requests.Session,
    origin: Location,
    destination: Location,
    routing_profile: str,
) -> dict[str, Any]:
    route_url = f"https://router.project-osrm.org/route/v1/{routing_profile}/"
    route_url += (
        f"{origin.longitude},{origin.latitude};"
        f"{destination.longitude},{destination.latitude}"
    )
    params = {
        "overview": "full",
        "geometries": "geojson",
        "alternatives": "true",
        "steps": "false",
    }
    response = session.get(route_url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        raise ValueError("OSRM returned no routes for the requested locations")
    return routes[0]


def fetch_route_tomtom(
    session: requests.Session,
    origin: Location,
    destination: Location,
    routing_profile: str,
    tomtom_api_key: str | None,
) -> dict[str, Any]:
    if not tomtom_api_key:
        raise ValueError(
            "TomTom routing provider selected but no API key configured"
        )

    travel_mode = {
        "driving": "car",
        "walking": "pedestrian",
        "cycling": "bicycle",
    }.get(routing_profile, "car")

    route_url = (
        "https://api.tomtom.com/routing/1/calculateRoute/"
        f"{origin.latitude},{origin.longitude}:"
        f"{destination.latitude},{destination.longitude}/json"
    )
    params = {
        "key": tomtom_api_key,
        "traffic": "true",
        "travelMode": travel_mode,
        "computeBestOrder": "false",
        "routeRepresentation": "polyline",
    }
    response = session.get(route_url, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        raise ValueError("TomTom returned no routes for the requested locations")

    route = routes[0]
    summary = route.get("summary") or {}
    route_points = route.get("legs", [{}])[0].get("points") or []
    coordinates = []
    for point in route_points:
        lat = point.get("latitude")
        lon = point.get("longitude")
        if lat is None or lon is None:
            continue
        coordinates.append([float(lon), float(lat)])

    if not coordinates:
        raise ValueError("TomTom route geometry did not include coordinates")

    return {
        "duration": float(summary.get("travelTimeInSeconds", 0.0)),
        "distance": float(summary.get("lengthInMeters", 0.0)),
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates,
        },
        "legs": [
            {
                "summary": (
                    "Traffic-aware route "
                    f"(delay: {float(summary.get('trafficDelayInSeconds', 0.0)) / 60.0:.1f} mins)"
                )
            }
        ],
    }


def extract_route_sample(
    config: dict[str, Any],
    route_config: dict[str, Any],
) -> RouteSample:
    tracking = config["tracking"]
    user_agent = str(tracking["user_agent"])
    session = build_session(user_agent)
    email = tracking.get("nominatim_email")
    routing_provider = str(tracking.get("routing_provider", "osrm"))
    tomtom_api_key = tracking.get("tomtom_api_key")
    origin = resolve_location(session, route_config["origin"], email=email)
    destination = resolve_location(
        session,
        route_config["destination"],
        email=email,
    )
    routing_profile = str(
        route_config.get(
            "routing_profile",
            tracking.get("routing_profile", "driving"),
        )
    )
    try:
        route = fetch_route(
            session=session,
            origin=origin,
            destination=destination,
            routing_profile=routing_profile,
            routing_provider=routing_provider,
            tomtom_api_key=(str(tomtom_api_key) if tomtom_api_key else None),
        )
    except (
        requests.RequestException,
        ValueError,
    ) as exc:
        if routing_provider.lower() != "tomtom":
            raise
        logging.warning(
            "TomTom routing failed (%s). Falling back to OSRM for %s.",
            exc,
            route_config.get("name", route_config.get("key", "route")),
        )
        route = fetch_route_osrm(
            session=session,
            origin=origin,
            destination=destination,
            routing_profile=routing_profile,
        )
    summary = (
        route.get("legs", [{}])[0].get("summary")
        or route.get("name")
        or "Optimized route"
    )
    geometry_json = json.dumps(
        route.get("geometry") or {},
        separators=(",", ":"),
    )
    return RouteSample(
        route_key=str(route_config["key"]),
        route_name=str(route_config["name"]),
        collected_at=current_timestamp(),
        origin=origin,
        destination=destination,
        duration_seconds=float(route["duration"]),
        distance_meters=float(route["distance"]),
        route_summary=str(summary),
        route_geometry_json=geometry_json,
    )


def persist_sample(db_path: str | Path, sample: RouteSample) -> int:
    return database.insert_sample(
        db_path,
        database.TravelSample(
            route_key=sample.route_key,
            route_name=sample.route_name,
            collected_at=sample.collected_at,
            origin_label=sample.origin.label,
            destination_label=sample.destination.label,
            origin_address=sample.origin.address,
            destination_address=sample.destination.address,
            origin_lat=sample.origin.latitude,
            origin_lon=sample.origin.longitude,
            destination_lat=sample.destination.latitude,
            destination_lon=sample.destination.longitude,
            duration_seconds=sample.duration_seconds,
            duration_minutes=sample.duration_minutes,
            distance_meters=sample.distance_meters,
            distance_km=sample.distance_km,
            distance_miles=sample.distance_miles,
            route_summary=sample.route_summary,
            route_geometry_json=sample.route_geometry_json,
            status="success",
            error_message=None,
        ),
    )


def collect_route(
    config: dict[str, Any],
    route_config: dict[str, Any],
    db_path: Path,
) -> dict[str, Any]:
    sample = extract_route_sample(config, route_config)
    row_id = persist_sample(db_path, sample)
    logging.info(
        "Stored sample #%s for %s: %.2f mins, %.2f km, %s",
        row_id,
        sample.route_name,
        sample.duration_minutes,
        sample.distance_km,
        sample.route_summary,
    )
    return {
        "row_id": row_id,
        "route_key": sample.route_key,
        "route_name": sample.route_name,
        "duration_minutes": sample.duration_minutes,
        "distance_km": sample.distance_km,
        "distance_miles": sample.distance_miles,
        "route_summary": sample.route_summary,
    }


def collect_and_store(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    config = load_config(config_path)
    app_config = config["app"]
    db_path = BASE_DIR / str(app_config["database_path"])
    retention_days = int(app_config["retention_days"])
    database.initialize_database(db_path)
    routes = get_routes(config)
    if len(routes) == 1:
        database.backfill_route_metadata(
            db_path,
            routes[0]["key"],
            routes[0]["name"],
        )
    results: list[dict[str, Any]] = []
    max_workers = min(3, max(1, len(routes)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(collect_route, config, route, db_path): route
            for route in routes
        }
        for future in as_completed(future_map):
            route = future_map[future]
            try:
                results.append(future.result())
            except (requests.RequestException, ValueError, OSError) as exc:
                logging.warning(
                    "Route collection skipped for %s: %s",
                    route.get("name", route.get("key", "route")),
                    exc,
                )
    database.prune_old_records(db_path, retention_days)
    return {"routes": results}


def run_once(config_path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    result = collect_and_store(config_path)
    logging.info("Immediate route check complete: %s", result)


def run_daemon(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    run_initial: bool = True,
) -> None:
    config = load_config(config_path)
    app_config = config["app"]
    interval_seconds = int(app_config["interval_seconds"])
    configured_timezone = str(app_config.get("timezone", "America/Chicago"))
    job_timezone = ZoneInfo(configured_timezone)
    database.initialize_database(BASE_DIR / str(app_config["database_path"]))

    stop_event = threading.Event()
    scheduler = BackgroundScheduler(timezone=job_timezone)
    scheduler.add_job(
        lambda: collect_and_store(config_path),
        "interval",
        seconds=interval_seconds,
        id="route_collection",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=min(300, interval_seconds),
    )
    scheduler.start()

    def handle_signal(signum: int, _frame: Any) -> None:
        logging.info("Received signal %s, stopping tracker daemon", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if run_initial:
        try:
            collect_and_store(config_path)
        except (requests.RequestException, ValueError, OSError):
            logging.warning(
                "Initial collection failed; daemon will keep running",
            )

    logging.info(
        "Tracker daemon started with %s second interval in %s timezone",
        interval_seconds,
        configured_timezone,
    )
    try:
        while not stop_event.wait(1):
            pass
    finally:
        scheduler.shutdown(wait=False)
        logging.info("Tracker daemon stopped")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect commute travel times on a schedule.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single collection and exit",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run the background scheduler",
    )
    parser.add_argument(
        "--no-initial",
        action="store_true",
        help=(
            "Do not perform an immediate collection before the scheduler "
            "starts"
        ),
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    args = parse_args()
    config_path = Path(args.config)
    if args.once:
        run_once(config_path)
    elif args.daemon:
        run_daemon(config_path, run_initial=not args.no_initial)
    else:
        run_once(config_path)


if __name__ == "__main__":
    main()
