#!/usr/bin/env python3
"""
Discord AQI Alert Bot

Checks the Open-Meteo Air Quality forecast for a configured ZIP code and
posts a status update to a Discord webhook every run, rate-limited to at
most one post per configured interval (default: 1 hour), even if the
script is run more frequently (e.g. from a cron job). Posts use a red
"AQI Index over 50" alert format when the forecast US AQI exceeds the
configured threshold, and a plain status format otherwise.

Configuration is read entirely from environment variables (see
.env.example) -- nothing is hardcoded.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

GEOCODE_URL_TEMPLATE = "https://api.zippopotam.us/{country}/{zip_code}"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

DEFAULT_THRESHOLD = 50
DEFAULT_MIN_INTERVAL_SECONDS = 3600
DEFAULT_STATE_FILE = "state/last_alert.json"
DEFAULT_COUNTRY = "us"
ALERT_COLOR_HEX = "#FF0000"
ALERT_COLOR_DECIMAL = 0xFF0000
STATUS_COLOR_DECIMAL = 0x2ECC71

ANSI_ESC = "\x1b"


class ConfigError(RuntimeError):
    pass


def get_env(name, default=None, required=False):
    value = os.environ.get(name, default)
    if required and not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config():
    return {
        "webhook_url": get_env("DISCORD_WEBHOOK_URL", required=True),
        "zip_code": get_env("ZIP_CODE", "54017"),
        "country_code": get_env("COUNTRY_CODE", DEFAULT_COUNTRY),
        "aqi_threshold": float(get_env("AQI_THRESHOLD", str(DEFAULT_THRESHOLD))),
        "min_interval_seconds": int(
            get_env("MIN_ALERT_INTERVAL_SECONDS", str(DEFAULT_MIN_INTERVAL_SECONDS))
        ),
        "state_file": get_env("STATE_FILE", DEFAULT_STATE_FILE),
    }


def geocode_zip(zip_code, country_code):
    url = GEOCODE_URL_TEMPLATE.format(country=country_code, zip_code=zip_code)
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    place = data["places"][0]
    return {
        "latitude": float(place["latitude"]),
        "longitude": float(place["longitude"]),
        "place_name": place.get("place name", ""),
        "state": place.get("state abbreviation", ""),
    }


def fetch_aqi_forecast(latitude, longitude):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "us_aqi",
        "timezone": "auto",
    }
    response = requests.get(AIR_QUALITY_URL, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def get_current_aqi(forecast):
    hourly = forecast.get("hourly", {})
    times = hourly.get("time", [])
    values = hourly.get("us_aqi", [])
    if not times or not values:
        raise ValueError("Air quality forecast response missing hourly us_aqi data")

    now = datetime.now(timezone.utc)
    current_tz = forecast.get("timezone", "UTC")

    # Open-Meteo returns local timestamps (no offset) when timezone=auto,
    # so compare against the local time in that same timezone.
    try:
        from zoneinfo import ZoneInfo

        now_local = datetime.now(ZoneInfo(current_tz))
    except Exception:
        now_local = now

    now_str = now_local.strftime("%Y-%m-%dT%H:00")

    if now_str in times:
        index = times.index(now_str)
    else:
        # Fall back to the closest past hour, or the first entry.
        index = 0
        for i, t in enumerate(times):
            if t <= now_str:
                index = i
            else:
                break

    return {"time": times[index], "aqi": values[index]}


def load_last_alert_timestamp(state_file):
    path = Path(state_file)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data.get("last_alert_epoch")
    except (json.JSONDecodeError, OSError):
        return None


def save_last_alert_timestamp(state_file, epoch_seconds):
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_alert_epoch": epoch_seconds}))


def build_discord_payload(aqi_value, zip_code, place_label, observed_time, aqi_threshold):
    location_suffix = f" ({place_label})" if place_label else ""

    if aqi_value > aqi_threshold:
        return {
            "content": f"```ansi\n{ANSI_ESC}[31mAQI Index over 50{ANSI_ESC}[0m\n```",
            "embeds": [
                {
                    "title": "AQI Index over 50",
                    "description": (
                        f"Forecasted Air Quality Index for **{zip_code}**{location_suffix} "
                        f"is **{aqi_value}**, above the alert threshold."
                    ),
                    "color": ALERT_COLOR_DECIMAL,
                    "fields": [
                        {"name": "AQI", "value": str(aqi_value), "inline": True},
                        {"name": "ZIP Code", "value": zip_code, "inline": True},
                        {"name": "Forecast Hour", "value": observed_time, "inline": True},
                    ],
                    "footer": {"text": f"Alert color {ALERT_COLOR_HEX}"},
                }
            ],
        }

    return {
        "embeds": [
            {
                "title": "AQI Status Update",
                "description": (
                    f"Forecasted Air Quality Index for **{zip_code}**{location_suffix} "
                    f"is **{aqi_value}**, at or below the alert threshold."
                ),
                "color": STATUS_COLOR_DECIMAL,
                "fields": [
                    {"name": "AQI", "value": str(aqi_value), "inline": True},
                    {"name": "ZIP Code", "value": zip_code, "inline": True},
                    {"name": "Forecast Hour", "value": observed_time, "inline": True},
                ],
            }
        ],
    }


def post_discord_update(webhook_url, aqi_value, zip_code, place_label, observed_time, aqi_threshold):
    payload = build_discord_payload(aqi_value, zip_code, place_label, observed_time, aqi_threshold)
    response = requests.post(webhook_url, json=payload, timeout=15)
    response.raise_for_status()


def main():
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    location = geocode_zip(config["zip_code"], config["country_code"])
    forecast = fetch_aqi_forecast(location["latitude"], location["longitude"])
    current = get_current_aqi(forecast)
    aqi_value = current["aqi"]

    print(f"ZIP {config['zip_code']}: forecasted AQI = {aqi_value} at {current['time']}")

    if aqi_value is None:
        print("No AQI value available; skipping this run.")
        return 0

    last_alert_epoch = load_last_alert_timestamp(config["state_file"])
    now_epoch = time.time()

    if last_alert_epoch is not None:
        elapsed = now_epoch - last_alert_epoch
        if elapsed < config["min_interval_seconds"]:
            remaining = int(config["min_interval_seconds"] - elapsed)
            print(
                f"Already posted {int(elapsed)}s ago; "
                f"waiting {remaining}s before the next post."
            )
            return 0

    place_label = ", ".join(
        part for part in [location.get("place_name"), location.get("state")] if part
    )
    post_discord_update(
        config["webhook_url"],
        aqi_value,
        config["zip_code"],
        place_label,
        current["time"],
        config["aqi_threshold"],
    )
    save_last_alert_timestamp(config["state_file"], now_epoch)

    if aqi_value > config["aqi_threshold"]:
        print("Alert posted to Discord (AQI above threshold).")
    else:
        print("Status update posted to Discord (AQI at or below threshold).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
