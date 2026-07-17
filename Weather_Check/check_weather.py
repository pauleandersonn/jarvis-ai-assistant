"""Get current weather for a city using wttr.in's JSON endpoint.

The original implementation scraped HTML and broke when wttr.in changed
its layout. The JSON endpoint (?format=j1) is stable and free.
"""

import json
import urllib.parse
import urllib.request

from TextToSpeech.Fast_DF_TTS import speak


def _fetch_json(city: str) -> dict:
    encoded = urllib.parse.quote(city)
    url = f"https://wttr.in/{encoded}?format=j1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def get_weather_by_address(city: str) -> str:
    """Return a short human-readable weather description for `city`."""
    if not city or not city.strip():
        return "I need a city name to check the weather."

    try:
        data = _fetch_json(city)
    except Exception as exc:  # noqa: BLE001
        return f"Could not fetch weather: {exc}"

    try:
        current = data["current_condition"][0]
        area = data["nearest_area"][0]["areaName"][0]["value"]
        region = data["nearest_area"][0]["region"][0]["value"]
        country = data["nearest_area"][0]["country"][0]["value"]

        temp_c = current["temp_C"]
        feels_c = current["FeelsLikeC"]
        humidity = current["humidity"]
        desc = current["weatherDesc"][0]["value"]
        wind_kph = current["windspeedKmph"]

        msg = (
            f"Currently in {area}, {region}, {country}: {desc}, "
            f"{temp_c} degrees Celsius, feels like {feels_c}. "
            f"Humidity {humidity} percent, wind {wind_kph} kilometers per hour."
        )
        speak(msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse weather data: {exc}"