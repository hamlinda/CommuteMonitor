# Travel Tracker

A self-contained local Python application that monitors travel time between two locations every 30 minutes, stores the results in SQLite, and visualizes the last 7 days of commute history in a Streamlit dashboard.

## What it does

- Resolves origin and destination from either coordinates or plaintext addresses.
- Queries Nominatim for geocoding and OSRM for route travel time, distance, and geometry.
- Stores one sample every 30 minutes in `travel_data.db`.
- Keeps a rolling 7-day analytics window by pruning older rows.
- Shows metrics, line charts, sortable tables, and the latest route map in the UI.

## Project Layout

```text
travel-tracker/
├── config.yaml
├── database.py
├── tracker.py
├── app.py
├── setup.sh
├── shutdown.sh
├── requirements.txt
└── README.md
```

## Prerequisites

- Python 3.10 or newer
- Network access to:
  - `https://nominatim.openstreetmap.org`
  - `https://router.project-osrm.org`

## Setup

1. Edit `config.yaml` if you want to change the origin, destination, interval, retention window, or port.
2. Run:

```bash
./setup.sh
```

The script will:

- verify Python 3.10+
- create `.venv`
- install dependencies
- initialize the SQLite schema
- run an immediate route sample
- start the background collector daemon
- start the Streamlit UI on port `8585`

Open the dashboard at:

```text
http://localhost:8585
```

The Streamlit server binds to `0.0.0.0`, so other devices on the same network
can also open `http://<your-machine-ip>:8585`.

## Shutdown

```bash
./shutdown.sh
```

This terminates the worker and the web UI using the saved PID files.

## Configuration

The key settings live in `config.yaml`:

- `app.port`: Streamlit port, default `8585`
- `app.interval_seconds`: collection interval, default `1800`
- `app.retention_days`: rolling analytics window, default `7`
- `app.database_path`: SQLite database file
- `tracking.origin` / `tracking.destination`: labels, addresses, and optional coordinates
- `tracking.routing_profile`: OSRM profile, default `driving`
- `tracking.user_agent`: required by Nominatim usage policy

If coordinates are omitted, the tracker will geocode the configured address automatically.

## Data Model

Each successful sample stores:

- timestamp
- day of week
- time of day
- duration in minutes
- distance in kilometers and miles
- OSRM route summary
- full route geometry for map rendering

Failed collections are logged with status metadata so you can troubleshoot network or API issues if needed.

## Rate Limits and API Etiquette

Nominatim and OSRM are free public services. Keep requests polite:

- use a descriptive `User-Agent`
- avoid tight polling loops
- prefer cached coordinates in `config.yaml` for long-running use
- do not hammer the endpoints if you see timeouts or 429 responses

For production or heavy use, consider a dedicated geocoding and routing service rather than the public endpoints.

## Troubleshooting

- If the UI shows no data, wait for the first sample or run `python tracker.py --once`.
- If geocoding fails, verify the address text in `config.yaml` or provide latitude/longitude directly.
- If the worker is not updating, inspect `.worker.log`.
- If Streamlit does not appear, inspect `.web.log`.
- If the route map is empty, confirm OSRM returned geometry for the latest sample.

## Manual Commands

Run one sample manually:

```bash
source .venv/bin/activate
python tracker.py --once
```

Run the daemon manually:

```bash
source .venv/bin/activate
python tracker.py --daemon --no-initial
```

Run the UI manually:

```bash
source .venv/bin/activate
streamlit run app.py --server.port 8585 --server.address 127.0.0.1
```
