# multi_tool_agent/agent.py
import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from typing import Dict, Any, Optional
import os

import requests

GEOCODING_URL = os.getenv("GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_URL = os.getenv("WEATHER_URL", "https://api.open-meteo.com/v1/forecast")

def _geocode_city(city: str) -> Optional[Dict[str, Any]]:
    """
    Resolve city name to latitude, longitude, and timezone
    using Open-Meteo Geocoding API.
    """
    try:
        resp = requests.get(
            GEOCODING_URL,
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json",
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    results = data.get("results") or []
    if not results:
        return None

    return results[0]

def _get_weather_for_coords(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Get current weather from Open-Meteo for given latitude & longitude.
    """
    try:
        resp = requests.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": "true",
                "timezone": "auto",  # Open-Meteo resolves local timezone
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    current = data.get("current_weather")
    if not current:
        return None

    return {
        "temperature_c": current.get("temperature"),
        "windspeed_kmh": current.get("windspeed"),
        "weather_code": current.get("weathercode"),
        "raw": current,
    }
def get_city_weather_and_time(city: str) -> Dict[str, Any]:
    """
    - takes a city name
    - finds lat/lon and timezone
    - returns weather + current local time
    - use to find weather and time for a city
    
    Returns a dict like:
    {
        "status": "success",
        "city": "New York",
        "country": "United States",
        "latitude": 40.71,
        "longitude": -74.01,
        "temperature_c": 25.3,
        "windspeed_kmh": 10.5,
        "local_time_iso": "...",
        "report": "In New York, United States it is 25.3 °C ...",
    }
    """
    location = _geocode_city(city)
    if not location:
        return {
            "status": "error",
            "error_message": f"Could not find location for '{city}'.",
        }

    lat = location["latitude"]
    lon = location["longitude"]
    tz_name = location.get("timezone")
    city_name = location.get("name", city)
    country = location.get("country")

    weather = _get_weather_for_coords(lat, lon)
    if not weather:
        return {
            "status": "error",
            "error_message": f"Weather not available for '{city_name}'.",
        }

    # Fallback: if geocoding didn’t give timezone, you could also use
    # the `timezone` field from the weather API response (if present).
    if not tz_name:
        tz_name = "UTC"

    try:
        tz = ZoneInfo(tz_name)
        now = datetime.datetime.now(tz)
    except Exception:
        now = datetime.datetime.utcnow()
        tz_name = "UTC"

    place_label = f"{city_name}, {country}" if country else city_name

    report = (
        f"In {place_label} it is {weather['temperature_c']} °C "
        f"with wind speed {weather['windspeed_kmh']} km/h. "
        f"Local time is {now:%Y-%m-%d %H:%M:%S %Z}."
    )

    return {
        "status": "success",
        "city": city_name,
        "country": country,
        "latitude": lat,
        "longitude": lon,
        "timezone": tz_name,
        "temperature_c": weather["temperature_c"],
        "windspeed_kmh": weather["windspeed_kmh"],
        "local_time_iso": now.isoformat(),
        "report": report,
        "raw": {
            "location": location,
            "weather": weather["raw"],
        },
    }

root_agent = Agent(
    name="weather_time_agent",
    model="gemini-2.0-flash",
    description="Answers time and weather questions for cities.",
    instruction="Use the tools to fetch city weather and time.",
    tools = [get_city_weather_and_time]
    #tools=[get_weather, get_current_time]
)

