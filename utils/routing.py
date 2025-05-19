"""Routing utilities: ORS Directions with 2-level cache (memory + file).
No external Redis dependency required.
"""
import json
import os
import pathlib
import time
from functools import lru_cache
import logging

import requests
from dotenv import load_dotenv

# Load ENV
load_dotenv()
ORS_API_KEY = "5b3ce3597851110001cf62480e7559e09dc140e9bfd9a773f454500a"

# Logger setup
logger = logging.getLogger("routing")
logging.basicConfig(level=logging.INFO)

# File-based cache
CACHE_FILE = pathlib.Path(__file__).with_name("ors_cache.json")
_FILE_CACHE: dict[str, dict] = {}

def _load_file_cache():
    global _FILE_CACHE
    if CACHE_FILE.exists():
        try:
            _FILE_CACHE = json.loads(CACHE_FILE.read_text())
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            _FILE_CACHE = {}

def _save_file_cache():
    try:
        CACHE_FILE.write_text(json.dumps(_FILE_CACHE))
    except IOError as e:
        logger.warning(f"Failed to save cache: {e}")

_load_file_cache()

# Helpers
def _check_api_key():
    if not ORS_API_KEY:
        raise EnvironmentError("ORS_API_KEY not set in environment variables")

def _build_headers():
    return {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}

def _make_key(origin: tuple[float, float], dest: tuple[float, float]) -> str:
    """Create cache key in consistent (lon, lat) order"""
    return f"{origin[0]:.6f},{origin[1]:.6f}:{dest[0]:.6f},{dest[1]:.6f}"

# Core request (private, no cache)
def _raw_ors_directions(origin: tuple[float, float], destination: tuple[float, float], profile="driving-car"):
    _check_api_key()
    body = {
        "coordinates": [
            [float(origin[0]), float(origin[1])],  # lon, lat
            [float(destination[0]), float(destination[1])],
        ],
        "units": "km",
    }
    r = None
    try:
        r = requests.post(
            f"https://api.openrouteservice.org/v2/directions/{profile}",
            headers=_build_headers(),
            json=body,
            timeout=10,
        )
        r.raise_for_status()
        summary = r.json()["routes"][0]["summary"]
        return round(summary["duration"] / 3600, 2), round(summary["distance"], 2)  # (hours, km)
    except Exception as exc:
        logger.error(f"ORS Directions error: {exc}")
        if r is not None and r.text:
            try:
                pathlib.Path("ors_directions_error.json").write_text(r.text)
            except Exception as file_exc:
                logger.warning(f"Failed to write error file: {file_exc}")
        return None, None

# Public API (with cache)
@lru_cache(maxsize=20_000)
def ors_directions_request(origin: tuple[float, float], destination: tuple[float, float], profile: str = "driving-car"):
    """Return (duration_minutes, distance_km) with caching."""
    k = _make_key(origin, destination)
    if (cached := _FILE_CACHE.get(k)) is not None:
        return cached["d"], cached["s"]

    dur, dist = _raw_ors_directions(origin, destination, profile)

    # Fallback default kalau ORS gagal
    if dur is None or dist is None:
        print(f"[WARNING] ORS gagal antara {origin} ke {destination}, fallback ke 15m, 1km")
        dur = 15.0  # default durasi: 15 menit
        dist = 1.0  # default jarak: 1 km

    _FILE_CACHE[k] = {"d": dur, "s": dist, "ts": time.time()}
    _save_file_cache()

    return dur, dist

# Optional preload matrix
def precompute_matrix(points: list[tuple[float, float]], profile="driving-car"):
    if len(points) > 50:
        raise ValueError("ORS Matrix API limited to 50 points max")

    _check_api_key()
    body = {"locations": points, "metrics": ["distance", "duration"], "units": "km"}
    try:
        r = requests.post(
            f"https://api.openrouteservice.org/v2/matrix/{profile}",
            headers=_build_headers(),
            json=body,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        durs = data["durations"]
        dists = data["distances"]
        n = len(points)
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                dur_h = round(durs[i][j] / 3600, 2)
                dist_km = round(dists[i][j], 2)
                _FILE_CACHE[_make_key(points[i], points[j])] = {
                    "d": dur_h,
                    "s": dist_km,
                    "ts": time.time(),
                }
        _save_file_cache()
    except Exception as exc:
        logger.error(f"ORS Matrix preload error: {exc}")

# Legacy
def ors_matrix_request_with_adjustment(*_args, **_kwargs):
    raise RuntimeError(
        "ors_matrix_request_with_adjustment is deprecated. "
        "Use ors_directions_request (cached) instead."
    )
