# multi_tool_agent/agent.py
import datetime
from zoneinfo import ZoneInfo
from google.adk.agents import Agent
from typing import Dict, Any, Optional
import os
import logging

import requests
from utility.tracing import get_tracer

logger = logging.getLogger(__name__)

GEOCODING_URL = os.getenv("GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search")
WEATHER_URL = os.getenv("WEATHER_URL", "https://api.open-meteo.com/v1/forecast")

def _geocode_city(city: str) -> Optional[Dict[str, Any]]:
    """
    Resolve city name to latitude, longitude, and timezone
    using Open-Meteo Geocoding API.
    """
    tracer = get_tracer(__name__)
    span = None
    if tracer:
        span = tracer.start_span("geocode_city")
        span.set_attribute("city", city)
    
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
        
        results = data.get("results") or []
        if not results:
            if span:
                span.set_attribute("found", False)
            return None

        result = results[0]
        if span:
            span.set_attribute("found", True)
            span.set_attribute("latitude", result.get("latitude", 0))
            span.set_attribute("longitude", result.get("longitude", 0))
        
        return result
    except requests.RequestException as e:
        if span:
            from opentelemetry.trace import Status, StatusCode
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
        return None
    finally:
        if span:
            span.end()

def _get_weather_for_coords(lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """
    Get current weather from Open-Meteo for given latitude & longitude.
    """
    tracer = get_tracer(__name__)
    span = None
    if tracer:
        span = tracer.start_span("get_weather_for_coords")
        span.set_attribute("latitude", lat)
        span.set_attribute("longitude", lon)
    
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
        
        current = data.get("current_weather")
        if not current:
            if span:
                span.set_attribute("weather_available", False)
            return None

        result = {
            "temperature_c": current.get("temperature"),
            "windspeed_kmh": current.get("windspeed"),
            "weather_code": current.get("weathercode"),
            "raw": current,
        }
        
        if span:
            span.set_attribute("weather_available", True)
            span.set_attribute("temperature_c", result.get("temperature_c", 0))
            span.set_attribute("windspeed_kmh", result.get("windspeed_kmh", 0))
        
        return result
    except requests.RequestException as e:
        if span:
            from opentelemetry.trace import Status, StatusCode
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
        return None
    finally:
        if span:
            span.end()
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
    tracer = get_tracer(__name__)
    span = None
    if tracer:
        span = tracer.start_span("get_city_weather_and_time")
        span.set_attribute("city", city)
    
    try:
        location = _geocode_city(city)
        if not location:
            result = {
                "status": "error",
                "error_message": f"Could not find location for '{city}'.",
            }
            if span:
                span.set_attribute("status", "error")
                span.set_attribute("error", result["error_message"])
            return result

        lat = location["latitude"]
        lon = location["longitude"]
        tz_name = location.get("timezone")
        city_name = location.get("name", city)
        country = location.get("country")

        weather = _get_weather_for_coords(lat, lon)
        if not weather:
            result = {
                "status": "error",
                "error_message": f"Weather not available for '{city_name}'.",
            }
            if span:
                span.set_attribute("status", "error")
                span.set_attribute("error", result["error_message"])
            return result

        # Fallback: if geocoding didn't give timezone, you could also use
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

        result = {
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
        
        if span:
            span.set_attribute("status", "success")
            span.set_attribute("result_city", city_name)
            span.set_attribute("temperature_c", weather["temperature_c"])
        
        return result
    except Exception as e:
        if span:
            from opentelemetry.trace import Status, StatusCode
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
        return {
            "status": "error",
            "error_message": f"Unexpected error: {str(e)}",
        }
    finally:
        if span:
            span.end()

root_agent = Agent(
    name="weather_time_agent",
    model="gemini-2.0-flash",
    description="Answers time and weather questions for cities.",
    instruction="Use the tools to fetch city weather and time.",
    tools = [get_city_weather_and_time]
    #tools=[get_weather, get_current_time]
)

