from __future__ import annotations

import json
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

import database
import tracker


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"

DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


st.set_page_config(
    page_title="Travel Tracker",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
    }
    .metric-card {
        background: linear-gradient(
            135deg,
            rgba(13, 37, 63, 0.95),
            rgba(19, 86, 116, 0.92)
        );
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        color: white;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.16);
    }
    .metric-label {
        font-size: 0.82rem;
        opacity: 0.82;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }
    .metric-value {
        font-size: 1.85rem;
        font-weight: 700;
        line-height: 1.1;
    }
    .metric-subtitle {
        margin-top: 0.3rem;
        font-size: 0.88rem;
        opacity: 0.8;
    }
    .section-title {
        margin: 1.15rem 0 0.45rem 0;
        font-size: 1.05rem;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_app_config() -> dict:
    return tracker.load_config(CONFIG_PATH)


@st.cache_data(show_spinner=False)
def load_history(
    window_days: int,
    route_key: str | None = None,
) -> pd.DataFrame:
    settings = load_app_config()
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.initialize_database(db_path)
    rows = database.fetch_samples(
        db_path,
        retention_days=window_days,
        only_successful=True,
        route_key=route_key,
    )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["Timestamp"] = pd.to_datetime(frame["collected_at"], utc=True)
    frame["Day"] = frame["Timestamp"].dt.day_name()
    frame["Time of Day"] = frame["Timestamp"].dt.strftime("%H:%M")
    frame["Duration (mins)"] = frame["duration_minutes"].round(2)
    frame["Distance (km)"] = frame["distance_km"].round(2)
    frame["Distance (mi)"] = frame["distance_miles"].round(2)
    fastest = float(frame["Duration (mins)"].min())
    frame["Delta vs Fastest Route (mins)"] = (
        frame["Duration (mins)"] - fastest
    ).round(2)
    frame["Route Summary"] = frame["route_summary"].fillna("")
    frame["Timestamp Sort"] = frame["Timestamp"]
    return frame


@st.cache_data(show_spinner=False)
def load_latest_record() -> dict | None:
    settings = load_app_config()
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.initialize_database(db_path)
    return database.fetch_latest_sample(db_path)


@st.cache_data(show_spinner=False)
def load_summary(window_days: int, route_key: str | None = None) -> dict:
    settings = load_app_config()
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.initialize_database(db_path)
    return database.fetch_summary_stats(
        db_path,
        retention_days=window_days,
        route_key=route_key,
    )


@st.cache_data(show_spinner=False)
def load_daily_summary(
    window_days: int,
    route_key: str | None = None,
) -> pd.DataFrame:
    settings = load_app_config()
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.initialize_database(db_path)
    rows = database.fetch_daily_summary(
        db_path,
        retention_days=window_days,
        route_key=route_key,
    )
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["Day"] = frame["date"].dt.day_name()
    frame["Time Bucket"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame


@st.cache_data(show_spinner=False)
def load_route_activity(window_days: int) -> list[dict]:
    settings = load_app_config()
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.initialize_database(db_path)
    return database.get_route_activity(db_path, retention_days=window_days)


def unique_route_key(base_key: str, existing_keys: set[str]) -> str:
    candidate = base_key
    suffix = 2
    while candidate in existing_keys:
        candidate = f"{base_key}-{suffix}"
        suffix += 1
    return candidate


def build_route_entry(
    route_title_text: str,
    origin_label_text: str,
    origin_address_text: str,
    destination_label_text: str,
    destination_address_text: str,
    routing_profile_text: str,
    origin_latitude_text: str,
    origin_longitude_text: str,
    destination_latitude_text: str,
    destination_longitude_text: str,
) -> dict:
    origin: dict[str, object] = {
        "label": origin_label_text.strip(),
        "address": origin_address_text.strip(),
    }
    destination: dict[str, object] = {
        "label": destination_label_text.strip(),
        "address": destination_address_text.strip(),
    }
    if origin_latitude_text.strip() and origin_longitude_text.strip():
        origin["latitude"] = float(origin_latitude_text)
        origin["longitude"] = float(origin_longitude_text)
    if (
        destination_latitude_text.strip()
        and destination_longitude_text.strip()
    ):
        destination["latitude"] = float(destination_latitude_text)
        destination["longitude"] = float(destination_longitude_text)
    route_title_value = route_title_text.strip() or (
        f"{origin_label_text.strip()} to {destination_label_text.strip()}"
    )
    route_key = tracker.slugify(route_title_value)
    return {
        "key": route_key,
        "name": route_title_value,
        "origin": origin,
        "destination": destination,
        "routing_profile": routing_profile_text,
    }


def validate_route_form_inputs(
    origin_label_text: str,
    origin_address_text: str,
    destination_label_text: str,
    destination_address_text: str,
    origin_latitude_text: str,
    origin_longitude_text: str,
    destination_latitude_text: str,
    destination_longitude_text: str,
) -> list[str]:
    errors: list[str] = []

    if not origin_label_text.strip():
        errors.append("Origin label is required. Example: Home")
    if not origin_address_text.strip():
        errors.append(
            "Origin address is required. Example: 123 Main St, Austin, TX 78701"
        )
    if not destination_label_text.strip():
        errors.append("Destination label is required. Example: Office")
    if not destination_address_text.strip():
        errors.append(
            "Destination address is required. Example: 7171 Southwest Pkwy, Austin, TX"
        )

    origin_lat_value = origin_latitude_text.strip()
    origin_lon_value = origin_longitude_text.strip()
    destination_lat_value = destination_latitude_text.strip()
    destination_lon_value = destination_longitude_text.strip()

    if bool(origin_lat_value) != bool(origin_lon_value):
        errors.append(
            "Origin coordinates must include both latitude and longitude, or leave both blank."
        )
    if bool(destination_lat_value) != bool(destination_lon_value):
        errors.append(
            "Destination coordinates must include both latitude and longitude, or leave both blank."
        )

    if origin_lat_value and origin_lon_value:
        try:
            origin_lat = float(origin_lat_value)
            origin_lon = float(origin_lon_value)
            if origin_lat < -90 or origin_lat > 90:
                errors.append("Origin latitude must be between -90 and 90.")
            if origin_lon < -180 or origin_lon > 180:
                errors.append("Origin longitude must be between -180 and 180.")
        except ValueError:
            errors.append(
                "Origin coordinates must be numeric. Example: 30.2672 and -97.7431"
            )

    if destination_lat_value and destination_lon_value:
        try:
            destination_lat = float(destination_lat_value)
            destination_lon = float(destination_lon_value)
            if destination_lat < -90 or destination_lat > 90:
                errors.append("Destination latitude must be between -90 and 90.")
            if destination_lon < -180 or destination_lon > 180:
                errors.append("Destination longitude must be between -180 and 180.")
        except ValueError:
            errors.append(
                "Destination coordinates must be numeric. Example: 30.2672 and -97.7431"
            )

    return errors


def validate_route_form_field_errors(
    origin_label_text: str,
    origin_address_text: str,
    destination_label_text: str,
    destination_address_text: str,
    origin_latitude_text: str,
    origin_longitude_text: str,
    destination_latitude_text: str,
    destination_longitude_text: str,
) -> dict[str, list[str]]:
    field_errors: dict[str, list[str]] = {}

    def add_error(field_name: str, message: str) -> None:
        field_errors.setdefault(field_name, []).append(message)

    if not origin_label_text.strip():
        add_error("origin_label", "Required. Example: Home")
    if not origin_address_text.strip():
        add_error(
            "origin_address",
            "Required. Example: 123 Main St, Austin, TX 78701",
        )
    if not destination_label_text.strip():
        add_error("destination_label", "Required. Example: Office")
    if not destination_address_text.strip():
        add_error(
            "destination_address",
            "Required. Example: 7171 Southwest Pkwy, Austin, TX",
        )

    origin_lat_value = origin_latitude_text.strip()
    origin_lon_value = origin_longitude_text.strip()
    destination_lat_value = destination_latitude_text.strip()
    destination_lon_value = destination_longitude_text.strip()

    if origin_lat_value and not origin_lon_value:
        add_error("origin_longitude", "Required when origin latitude is provided")
    if origin_lon_value and not origin_lat_value:
        add_error("origin_latitude", "Required when origin longitude is provided")
    if destination_lat_value and not destination_lon_value:
        add_error(
            "destination_longitude",
            "Required when destination latitude is provided",
        )
    if destination_lon_value and not destination_lat_value:
        add_error(
            "destination_latitude",
            "Required when destination longitude is provided",
        )

    if origin_lat_value:
        try:
            origin_lat = float(origin_lat_value)
            if origin_lat < -90 or origin_lat > 90:
                add_error("origin_latitude", "Must be between -90 and 90")
        except ValueError:
            add_error("origin_latitude", "Must be numeric, for example 30.2672")
    if origin_lon_value:
        try:
            origin_lon = float(origin_lon_value)
            if origin_lon < -180 or origin_lon > 180:
                add_error("origin_longitude", "Must be between -180 and 180")
        except ValueError:
            add_error("origin_longitude", "Must be numeric, for example -97.7431")

    if destination_lat_value:
        try:
            destination_lat = float(destination_lat_value)
            if destination_lat < -90 or destination_lat > 90:
                add_error("destination_latitude", "Must be between -90 and 90")
        except ValueError:
            add_error(
                "destination_latitude",
                "Must be numeric, for example 30.2672",
            )
    if destination_lon_value:
        try:
            destination_lon = float(destination_lon_value)
            if destination_lon < -180 or destination_lon > 180:
                add_error("destination_longitude", "Must be between -180 and 180")
        except ValueError:
            add_error(
                "destination_longitude",
                "Must be numeric, for example -97.7431",
            )

    return field_errors


def render_inline_form_errors(
    error_slots: dict[str, st.delta_generator.DeltaGenerator],
    field_errors: dict[str, list[str]],
) -> None:
    for field_name, slot in error_slots.items():
        messages = field_errors.get(field_name) or []
        if messages:
            slot.error("; ".join(messages), icon="⚠️")
        else:
            slot.empty()


def validate_route_location_resolution(
    origin_label_text: str,
    origin_address_text: str,
    destination_label_text: str,
    destination_address_text: str,
    origin_latitude_text: str,
    origin_longitude_text: str,
    destination_latitude_text: str,
    destination_longitude_text: str,
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}

    def add_error(field_name: str, message: str) -> None:
        errors.setdefault(field_name, []).append(message)

    # If coordinates are provided, tracker will not geocode that location.
    skip_origin_geocode = bool(
        origin_latitude_text.strip() and origin_longitude_text.strip()
    )
    skip_destination_geocode = bool(
        destination_latitude_text.strip() and destination_longitude_text.strip()
    )
    if skip_origin_geocode and skip_destination_geocode:
        return errors

    config = tracker.load_config(CONFIG_PATH)
    tracking_config = config.get("tracking") or {}
    user_agent = str(tracking_config.get("user_agent") or "CommuteMonitor/1.0")
    email = tracking_config.get("nominatim_email")
    session = tracker.build_session(user_agent)
    try:
        if not skip_origin_geocode:
            try:
                tracker.resolve_location(
                    session,
                    {
                        "label": origin_label_text.strip(),
                        "address": origin_address_text.strip(),
                    },
                    email=email,
                )
            except (ValueError, OSError, TypeError, RuntimeError) as exc:
                add_error(
                    "origin_address",
                    f"Address lookup failed: {str(exc)}",
                )

        if not skip_destination_geocode:
            try:
                tracker.resolve_location(
                    session,
                    {
                        "label": destination_label_text.strip(),
                        "address": destination_address_text.strip(),
                    },
                    email=email,
                )
            except (ValueError, OSError, TypeError, RuntimeError) as exc:
                add_error(
                    "destination_address",
                    f"Address lookup failed: {str(exc)}",
                )
    finally:
        session.close()

    return errors


def save_new_route(route_entry: dict) -> None:
    config = tracker.load_config(CONFIG_PATH)
    routes = tracker.get_routes(config)
    if len(routes) >= 3:
        raise ValueError("You can track at most 3 routes")
    existing_keys = {existing_route["key"] for existing_route in routes}
    route_entry["key"] = unique_route_key(route_entry["key"], existing_keys)
    routes.append(route_entry)
    tracker.set_routes(config, routes)
    tracker.save_config(CONFIG_PATH, config)


def update_existing_route(route_key: str, route_update_payload: dict) -> None:
    config = tracker.load_config(CONFIG_PATH)
    routes = tracker.get_routes(config)
    updated = []
    found = False
    for saved_route in routes:
        if saved_route["key"] == route_key:
            updated.append({**route_update_payload, "key": route_key})
            found = True
        else:
            updated.append(saved_route)
    if not found:
        raise ValueError("Selected route no longer exists")
    tracker.set_routes(config, updated)
    tracker.save_config(CONFIG_PATH, config)


def delete_existing_route(route_key: str) -> None:
    config = tracker.load_config(CONFIG_PATH)
    routes = tracker.get_routes(config)
    remaining = [route for route in routes if route["key"] != route_key]
    if len(remaining) == len(routes):
        raise ValueError("Selected route no longer exists")
    tracker.set_routes(config, remaining)
    tracker.save_config(CONFIG_PATH, config)
    # Delete all history for this route from database
    settings = tracker.load_config(CONFIG_PATH)
    db_path = BASE_DIR / str(settings["app"]["database_path"])
    database.delete_samples_for_route(db_path, route_key)


def render_route_card(route_record: dict, activity: dict | None) -> None:
    latest_collected_at = "No samples yet"
    average_minutes = "--"
    samples = "0"
    if activity:
        latest_collected_at = str(
            activity.get("latest_collected_at") or latest_collected_at
        )
        average_minutes = f"{activity.get('average_minutes', '--')} mins"
        samples = str(activity.get("samples", 0))
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{route_record['name']}</div>
            <div class="metric-value">
                {route_record['origin']['label']} →
                {route_record['destination']['label']}
            </div>
            <div class="metric-subtitle">
                Key: {route_record['key']} | Samples: {samples} | Avg:
                {average_minutes}
            </div>
            <div class="metric-subtitle">Latest: {latest_collected_at}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def route_form_defaults(route_record: dict) -> dict[str, str]:
    origin = route_record.get("origin") or {}
    destination = route_record.get("destination") or {}
    source_latitude = origin.get("latitude")
    source_longitude = origin.get("longitude")
    destination_latitude = destination.get("latitude")
    destination_longitude = destination.get("longitude")
    profile_value = str(route_record.get("routing_profile") or "driving")
    return {
        "route_title": str(route_record.get("name") or ""),
        "origin_label": str(origin.get("label") or ""),
        "origin_address": str(origin.get("address") or ""),
        "origin_latitude": (
            "" if source_latitude is None else str(source_latitude)
        ),
        "origin_longitude": (
            "" if source_longitude is None else str(source_longitude)
        ),
        "destination_label": str(destination.get("label") or ""),
        "destination_address": str(destination.get("address") or ""),
        "destination_latitude": (
            "" if destination_latitude is None else str(destination_latitude)
        ),
        "destination_longitude": (
            "" if destination_longitude is None else str(destination_longitude)
        ),
        "routing_profile": profile_value,
    }


def render_metric_card(title: str, value: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


loaded_config = load_app_config()
app_config = loaded_config["app"]
tracking = loaded_config["tracking"]
retention_days = int(app_config["retention_days"])
route_catalog = tracker.get_routes(loaded_config)
route_activity = load_route_activity(retention_days)
activity_by_key = {
    row["route_key"] or "": row for row in route_activity
}

selected_route_options = [("__all__", "All routes")]
selected_route_options.extend(
    (route["key"], route["name"]) for route in route_catalog
)

with st.sidebar:
    st.header("Tracked Routes")
    st.caption(f"{len(route_catalog)} configured, max 3 active routes")
    if route_catalog:
        for route_item in route_catalog:
            render_route_card(
                route_item,
                activity_by_key.get(route_item["key"]),
            )
    else:
        st.info("No routes configured yet.")

    st.divider()
    st.subheader("Add Route")
    st.session_state.setdefault("add_field_errors", {})
    with st.form("add_route_form", clear_on_submit=False):
        add_error_slots: dict[str, st.delta_generator.DeltaGenerator] = {}
        route_title = st.text_input(
            "Route name (optional)",
            placeholder="Home to Office",
            help=(
                "Optional. If left blank, name defaults to 'Origin label to Destination label'."
            ),
        )
        origin_label = st.text_input(
            "Origin label *",
            placeholder="Home",
            help="Required format: short place label, for example 'Home'.",
        )
        add_error_slots["origin_label"] = st.empty()
        origin_address = st.text_input(
            "Origin address *",
            placeholder="123 Main St, City",
            help=(
                "Required format: full street address with city/state. "
                "Example: 123 Main St, Austin, TX 78701"
            ),
        )
        add_error_slots["origin_address"] = st.empty()
        origin_latitude = st.text_input(
            "Origin latitude (optional)",
            help=(
                "Optional format: decimal degrees between -90 and 90. "
                "Example: 30.2672"
            ),
        )
        add_error_slots["origin_latitude"] = st.empty()
        origin_longitude = st.text_input(
            "Origin longitude (optional)",
            help=(
                "Optional format: decimal degrees between -180 and 180. "
                "Example: -97.7431"
            ),
        )
        add_error_slots["origin_longitude"] = st.empty()
        destination_label = st.text_input(
            "Destination label *",
            placeholder="Office",
            help="Required format: short place label, for example 'Office'.",
        )
        add_error_slots["destination_label"] = st.empty()
        destination_address = st.text_input(
            "Destination address *",
            placeholder="456 Market St, City",
            help=(
                "Required format: full street address with city/state. "
                "Example: 7171 Southwest Pkwy, Austin, TX"
            ),
        )
        add_error_slots["destination_address"] = st.empty()
        destination_latitude = st.text_input(
            "Destination latitude (optional)",
            help=(
                "Optional format: decimal degrees between -90 and 90. "
                "Example: 30.2672"
            ),
        )
        add_error_slots["destination_latitude"] = st.empty()
        destination_longitude = st.text_input(
            "Destination longitude (optional)",
            help=(
                "Optional format: decimal degrees between -180 and 180. "
                "Example: -97.7431"
            ),
        )
        add_error_slots["destination_longitude"] = st.empty()
        render_inline_form_errors(
            add_error_slots,
            st.session_state.get("add_field_errors", {}),
        )
        routing_profile = st.selectbox(
            "Routing profile *",
            ["driving", "walking", "cycling"],
            help="Required. Choose one of: driving, walking, cycling.",
        )
        add_route_clicked = st.form_submit_button("Save route")
        if add_route_clicked:
            if len(route_catalog) >= 3:
                st.error("You can track at most 3 routes.")
            else:
                field_errors = validate_route_form_field_errors(
                    origin_label,
                    origin_address,
                    destination_label,
                    destination_address,
                    origin_latitude,
                    origin_longitude,
                    destination_latitude,
                    destination_longitude,
                )
                st.session_state["add_field_errors"] = field_errors
                render_inline_form_errors(add_error_slots, field_errors)
                validation_errors = validate_route_form_inputs(
                    origin_label,
                    origin_address,
                    destination_label,
                    destination_address,
                    origin_latitude,
                    origin_longitude,
                    destination_latitude,
                    destination_longitude,
                )
                if validation_errors:
                    st.error("Please fix the following route configuration errors:")
                    for validation_error in validation_errors:
                        st.write(f"- {validation_error}")
                else:
                    try:
                        location_resolution_errors = (
                            validate_route_location_resolution(
                                origin_label,
                                origin_address,
                                destination_label,
                                destination_address,
                                origin_latitude,
                                origin_longitude,
                                destination_latitude,
                                destination_longitude,
                            )
                        )
                        if location_resolution_errors:
                            st.session_state["add_field_errors"] = {
                                **st.session_state["add_field_errors"],
                                **location_resolution_errors,
                            }
                            render_inline_form_errors(
                                add_error_slots,
                                st.session_state["add_field_errors"],
                            )
                            st.error(
                                "Address validation failed. Update address format or provide latitude/longitude."
                            )
                            for field_name, field_messages in (
                                location_resolution_errors.items()
                            ):
                                st.write(
                                    f"- {field_name}: {'; '.join(field_messages)}"
                                )
                            raise ValueError("Route not saved due to invalid address")

                        st.session_state["add_field_errors"] = {}
                        new_route = build_route_entry(
                            route_title,
                            origin_label,
                            origin_address,
                            destination_label,
                            destination_address,
                            routing_profile,
                            origin_latitude,
                            origin_longitude,
                            destination_latitude,
                            destination_longitude,
                        )
                        save_new_route(new_route)
                        st.cache_data.clear()
                        st.success(
                            f"Added route: {new_route['name']}. "
                            "Use 'Pull Data Now' to collect immediately."
                        )
                        st.rerun()
                    except (
                        ValueError,
                        OSError,
                        TypeError,
                        RuntimeError,
                    ) as exc:
                        if str(exc) != "Route not saved due to invalid address":
                            st.error(str(exc))

    st.divider()
    st.subheader("Edit / Delete Route")
    st.session_state.setdefault("edit_field_errors", {})
    if not route_catalog:
        st.info("Add a route first to edit or delete it.")
    else:
        route_selection = st.selectbox(
            "Select route",
            [route["key"] for route in route_catalog],
            format_func=lambda value: next(
                (
                    route["name"]
                    for route in route_catalog
                    if route["key"] == value
                ),
                value,
            ),
            key="route_edit_selector",
        )
        selected_route_record = next(
            route
            for route in route_catalog
            if route["key"] == route_selection
        )
        edit_defaults = route_form_defaults(selected_route_record)
        with st.form("edit_route_form", clear_on_submit=False):
            edit_error_slots: dict[str, st.delta_generator.DeltaGenerator] = {}
            edited_route_title = st.text_input(
                "Route name (optional)",
                value=edit_defaults["route_title"],
                help=(
                    "Optional. If left blank, name defaults to 'Origin label to Destination label'."
                ),
            )
            edited_origin_label = st.text_input(
                "Origin label *",
                value=edit_defaults["origin_label"],
                help="Required format: short place label, for example 'Home'.",
            )
            edit_error_slots["origin_label"] = st.empty()
            edited_origin_address = st.text_input(
                "Origin address *",
                value=edit_defaults["origin_address"],
                help=(
                    "Required format: full street address with city/state. "
                    "Example: 123 Main St, Austin, TX 78701"
                ),
            )
            edit_error_slots["origin_address"] = st.empty()
            edited_origin_latitude = st.text_input(
                "Origin latitude (optional)",
                value=edit_defaults["origin_latitude"],
                help=(
                    "Optional format: decimal degrees between -90 and 90. "
                    "Example: 30.2672"
                ),
            )
            edit_error_slots["origin_latitude"] = st.empty()
            edited_origin_longitude = st.text_input(
                "Origin longitude (optional)",
                value=edit_defaults["origin_longitude"],
                help=(
                    "Optional format: decimal degrees between -180 and 180. "
                    "Example: -97.7431"
                ),
            )
            edit_error_slots["origin_longitude"] = st.empty()
            edited_destination_label = st.text_input(
                "Destination label *",
                value=edit_defaults["destination_label"],
                help="Required format: short place label, for example 'Office'.",
            )
            edit_error_slots["destination_label"] = st.empty()
            edited_destination_address = st.text_input(
                "Destination address *",
                value=edit_defaults["destination_address"],
                help=(
                    "Required format: full street address with city/state. "
                    "Example: 7171 Southwest Pkwy, Austin, TX"
                ),
            )
            edit_error_slots["destination_address"] = st.empty()
            edited_destination_latitude = st.text_input(
                "Destination latitude (optional)",
                value=edit_defaults["destination_latitude"],
                help=(
                    "Optional format: decimal degrees between -90 and 90. "
                    "Example: 30.2672"
                ),
            )
            edit_error_slots["destination_latitude"] = st.empty()
            edited_destination_longitude = st.text_input(
                "Destination longitude (optional)",
                value=edit_defaults["destination_longitude"],
                help=(
                    "Optional format: decimal degrees between -180 and 180. "
                    "Example: -97.7431"
                ),
            )
            edit_error_slots["destination_longitude"] = st.empty()
            render_inline_form_errors(
                edit_error_slots,
                st.session_state.get("edit_field_errors", {}),
            )
            edited_routing_profile = st.selectbox(
                "Routing profile *",
                ["driving", "walking", "cycling"],
                index=["driving", "walking", "cycling"].index(
                    edit_defaults["routing_profile"]
                    if edit_defaults["routing_profile"] in [
                        "driving",
                        "walking",
                        "cycling",
                    ]
                    else "driving"
                ),
                help="Required. Choose one of: driving, walking, cycling.",
            )
            update_clicked = st.form_submit_button("Update route")
            if update_clicked:
                field_errors = validate_route_form_field_errors(
                    edited_origin_label,
                    edited_origin_address,
                    edited_destination_label,
                    edited_destination_address,
                    edited_origin_latitude,
                    edited_origin_longitude,
                    edited_destination_latitude,
                    edited_destination_longitude,
                )
                st.session_state["edit_field_errors"] = field_errors
                render_inline_form_errors(edit_error_slots, field_errors)
                validation_errors = validate_route_form_inputs(
                    edited_origin_label,
                    edited_origin_address,
                    edited_destination_label,
                    edited_destination_address,
                    edited_origin_latitude,
                    edited_origin_longitude,
                    edited_destination_latitude,
                    edited_destination_longitude,
                )
                if validation_errors:
                    st.error("Please fix the following route configuration errors:")
                    for validation_error in validation_errors:
                        st.write(f"- {validation_error}")
                else:
                    try:
                        location_resolution_errors = (
                            validate_route_location_resolution(
                                edited_origin_label,
                                edited_origin_address,
                                edited_destination_label,
                                edited_destination_address,
                                edited_origin_latitude,
                                edited_origin_longitude,
                                edited_destination_latitude,
                                edited_destination_longitude,
                            )
                        )
                        if location_resolution_errors:
                            st.session_state["edit_field_errors"] = {
                                **st.session_state["edit_field_errors"],
                                **location_resolution_errors,
                            }
                            render_inline_form_errors(
                                edit_error_slots,
                                st.session_state["edit_field_errors"],
                            )
                            st.error(
                                "Address validation failed. Update address format or provide latitude/longitude."
                            )
                            for field_name, field_messages in (
                                location_resolution_errors.items()
                            ):
                                st.write(
                                    f"- {field_name}: {'; '.join(field_messages)}"
                                )
                            raise ValueError("Route not updated due to invalid address")

                        st.session_state["edit_field_errors"] = {}
                        updated_route = build_route_entry(
                            edited_route_title,
                            edited_origin_label,
                            edited_origin_address,
                            edited_destination_label,
                            edited_destination_address,
                            edited_routing_profile,
                            edited_origin_latitude,
                            edited_origin_longitude,
                            edited_destination_latitude,
                            edited_destination_longitude,
                        )
                        update_existing_route(route_selection, updated_route)
                        st.cache_data.clear()
                        st.success(
                            "Route updated. Use 'Pull Data Now' to collect immediately."
                        )
                        st.rerun()
                    except (
                        ValueError,
                        OSError,
                        TypeError,
                        RuntimeError,
                    ) as exc:
                        if str(exc) != "Route not updated due to invalid address":
                            st.error(str(exc))

        with st.form("delete_route_form"):
            confirm_delete = st.checkbox(
                f"Delete {selected_route_record['name']}",
                value=False,
            )
            delete_clicked = st.form_submit_button("Delete route")
            if delete_clicked:
                if not confirm_delete:
                    st.error("Confirm delete before continuing.")
                else:
                    try:
                        delete_existing_route(route_selection)
                        st.cache_data.clear()
                        st.success("Route deleted")
                        st.rerun()
                    except (
                        ValueError,
                        OSError,
                        TypeError,
                        RuntimeError,
                    ) as exc:
                        st.error(str(exc))


st.title("Travel Tracker")
st.caption(
    (
        f"Monitoring {len(route_catalog)} route(s) every "
        f"{int(app_config['interval_seconds']) // 60} minutes"
    )
)

pull_feedback = st.session_state.get("pull_data_feedback")
if pull_feedback:
    feedback_kind = str(pull_feedback.get("kind") or "")
    feedback_message = str(pull_feedback.get("message") or "")
    if feedback_kind == "success":
        st.success(feedback_message)
    elif feedback_kind == "error":
        st.error(feedback_message)

# Instant data pull button
if st.button("📡 Pull Data Now", width="stretch"):
    with st.spinner("Collecting data from all routes..."):
        try:
            pull_result = tracker.collect_and_store(CONFIG_PATH)
            st.cache_data.clear()
            result_items = []
            if isinstance(pull_result, dict):
                routes_result = pull_result.get("routes")
                if isinstance(routes_result, list):
                    result_items = routes_result
            expected_count = len(route_catalog)
            successful_count = len(result_items)
            failed_count = max(0, expected_count - successful_count)
            if failed_count > 0:
                feedback_message = (
                    "Data pull completed with errors. "
                    f"Success: {successful_count}, Failed: {failed_count}. "
                    "Reason: one or more routes could not be collected "
                    "(for example, geocoding or API request failure)."
                )
                st.session_state["pull_data_feedback"] = {
                    "kind": "error",
                    "message": feedback_message,
                }
            elif expected_count == 0:
                st.session_state["pull_data_feedback"] = {
                    "kind": "error",
                    "message": "No routes are configured. Add a route before pulling data.",
                }
            else:
                st.session_state["pull_data_feedback"] = {
                    "kind": "success",
                    "message": (
                        "Data pulled successfully. "
                        f"Collected {successful_count} of {expected_count} route(s)."
                    ),
                }
            st.rerun()
        except Exception as exc:
            st.session_state["pull_data_feedback"] = {
                "kind": "error",
                "message": f"Failed to pull data: {str(exc)}",
            }
            st.rerun()

selected_route_key = st.selectbox(
    "View route data",
    [option[0] for option in selected_route_options],
    format_func=lambda value: dict(selected_route_options)[value],
)
selected_route = (
    None if selected_route_key == "__all__" else selected_route_key
)
selected_route_name = "All routes"
if selected_route:
    selected_route_name = next(
        (
            route["name"]
            for route in route_catalog
            if route["key"] == selected_route
        ),
        selected_route,
    )

history = load_history(retention_days, route_key=selected_route)
summary = load_summary(retention_days, route_key=selected_route)
latest_record = load_latest_record()
daily_summary = load_daily_summary(retention_days, route_key=selected_route)

st.subheader(f"Viewing: {selected_route_name}")

col1, col2, col3 = st.columns(3)
with col1:
    if summary["fastest"] is not None:
        render_metric_card(
            "Fastest",
            f"{summary['fastest']:.2f} mins",
            (
                "Best observed travel time in the last "
                f"{retention_days} days"
            ),
        )
    else:
        render_metric_card(
            "Fastest",
            "No data",
            "Run setup.sh or wait for the first sample",
        )
with col2:
    if summary["slowest"] is not None:
        render_metric_card(
            "Slowest",
            f"{summary['slowest']:.2f} mins",
            (
                "Worst observed travel time in the last "
                f"{retention_days} days"
            ),
        )
    else:
        render_metric_card(
            "Slowest",
            "No data",
            "Run setup.sh or wait for the first sample",
        )
with col3:
    if latest_record:
        latest_label = f"{latest_record['duration_minutes']:.2f} mins"
        latest_subtitle = f"Captured at {latest_record['collected_at']} UTC"
    else:
        latest_label = "No data"
        latest_subtitle = "Awaiting the first route check"
    render_metric_card("Latest", latest_label, latest_subtitle)

st.markdown(
    '<div class="section-title">Tracked Routes</div>',
    unsafe_allow_html=True,
)
route_columns = st.columns(max(1, min(3, len(route_catalog))))
for index, route in enumerate(route_catalog):
    with route_columns[index % len(route_columns)]:
        render_route_card(route, activity_by_key.get(route["key"]))

st.markdown(
    '<div class="section-title">Route Overview</div>',
    unsafe_allow_html=True,
)

chart_tab, raw_tab, aggregate_tab, map_tab = st.tabs(
    ["Trend Chart", "Raw History", "Aggregated View", "Latest Route Map"]
)

with chart_tab:
    if history.empty:
        st.info("No route samples available yet.")
    else:
        chart_frame = history.sort_values(["Day", "Timestamp Sort"])
        chart_frame["Day"] = pd.Categorical(
            chart_frame["Day"],
            categories=DAY_ORDER,
            ordered=True,
        )
        chart_frame = chart_frame.sort_values(["Day", "Timestamp Sort"])
        x_order = sorted(chart_frame["Time of Day"].unique())
        fig = px.line(
            chart_frame,
            x="Time of Day",
            y="Duration (mins)",
            color="Day",
            markers=True,
            category_orders={"Day": DAY_ORDER, "Time of Day": x_order},
            title="Travel time by time of day",
        )
        fig.update_layout(
            height=520,
            xaxis_title="Time of Day",
            yaxis_title="Duration (minutes)",
            legend_title_text="Day of Week",
            margin=dict(l=20, r=20, t=50, b=20),
        )
        st.plotly_chart(fig, width="stretch")

with raw_tab:
    if history.empty:
        st.info("No data collected yet.")
    else:
        raw_columns = [
            "Timestamp",
            "Day",
            "Time of Day",
            "Duration (mins)",
            "Distance (km)",
            "Distance (mi)",
            "Delta vs Fastest Route (mins)",
            "Route Summary",
        ]
        display_frame = history.loc[:, raw_columns].sort_values(
            "Timestamp",
            ascending=False,
        )
        st.dataframe(
            display_frame,
            width="stretch",
            hide_index=True,
        )
        csv = display_frame.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download history as CSV",
            data=csv,
            file_name="travel_history.csv",
            mime="text/csv",
        )

with aggregate_tab:
    if daily_summary.empty:
        st.info("No aggregation available yet.")
    else:
        aggregate_frame = daily_summary.sort_values(["date"], ascending=False)
        aggregate_frame = aggregate_frame.rename(
            columns={
                "date": "Date",
                "samples": "Samples",
                "avg_duration_minutes": "Avg Duration (mins)",
                "min_duration_minutes": "Min Duration (mins)",
                "max_duration_minutes": "Max Duration (mins)",
                "avg_distance_km": "Avg Distance (km)",
                "avg_distance_miles": "Avg Distance (mi)",
            }
        )
        aggregate_frame = aggregate_frame[
            [
                "Date",
                "Day",
                "Samples",
                "Avg Duration (mins)",
                "Min Duration (mins)",
                "Max Duration (mins)",
                "Avg Distance (km)",
                "Avg Distance (mi)",
            ]
        ]
        st.dataframe(
            aggregate_frame,
            width="stretch",
            hide_index=True,
        )

with map_tab:
    map_record = latest_record
    if selected_route and history.empty:
        map_record = None
    if not map_record or not map_record.get("route_geometry_json"):
        st.info("No route geometry available yet.")
    else:
        geometry = json.loads(map_record["route_geometry_json"])
        coordinates = geometry.get("coordinates") or []
        if not coordinates:
            st.info("Latest route did not include geometry coordinates.")
        else:
            line_points = [(lat, lon) for lon, lat in coordinates]
            midpoint = line_points[len(line_points) // 2]
            folium_map = folium.Map(
                location=midpoint,
                zoom_start=12,
                control_scale=True,
            )
            folium.PolyLine(
                locations=line_points,
                color="#2563eb",
                weight=6,
                opacity=0.85,
            ).add_to(folium_map)
            start = line_points[0]
            end = line_points[-1]
            folium.Marker(
                location=start,
                popup=f"Origin: {map_record['origin_label']}",
                tooltip="Origin",
                icon=folium.Icon(color="green", icon="play"),
            ).add_to(folium_map)
            folium.Marker(
                location=end,
                popup=f"Destination: {map_record['destination_label']}",
                tooltip="Destination",
                icon=folium.Icon(color="red", icon="stop"),
            ).add_to(folium_map)
            folium.LayerControl().add_to(folium_map)
            st_folium(folium_map, height=520, width=None)

st.caption(
    f"SQLite database: {app_config['database_path']} | "
    f"Retention window: {retention_days} days | "
    f"Interval: {int(app_config['interval_seconds'])} seconds"
)
