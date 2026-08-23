"""
Weather tools — current conditions and forecasts using wttr.in (no API key required).
"""

import httpx


async def fetch_weather(client: httpx.AsyncClient, location: str) -> dict:
    """Fetch weather data from wttr.in for a given location."""
    # wttr.in format: %l=location, %C=condition, %t=temperature, %f=feels like,
    # %h=humidity, %w=wind, %p=precipitation, %P=pressure
    url = f"https://wttr.in/{location}?format=j1"
    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"error": str(e)}


def format_current_weather(data: dict, location: str) -> str:
    """Format current weather from wttr.in JSON response."""
    if "error" in data:
        return f"Weather grid offline for {location}: {data['error']}"

    try:
        current = data["current_condition"][0]
        area = data["nearest_area"][0]

        location_name = area["areaName"][0]["value"]
        country = area["country"][0]["value"]
        temp_c = current["temp_C"]
        temp_f = current["temp_F"]
        condition = current["weatherDesc"][0]["value"]
        feels_like_c = current["FeelsLikeC"]
        feels_like_f = current["FeelsLikeF"]
        humidity = current["humidity"]
        wind_kph = current["windspeedKmph"]
        wind_dir = current["winddir16Point"]
        pressure = current["pressure"]
        visibility = current["visibility"]
        uv_index = current["uvIndex"]

        report = [
            f"### WEATHER REPORT: {location_name}, {country}",
            f"**Condition:** {condition}",
            (
                f"**Temperature:** {temp_c}°C / {temp_f}°F "
                f"(feels like {feels_like_c}°C / {feels_like_f}°F)"
            ),
            f"**Humidity:** {humidity}%",
            f"**Wind:** {wind_kph} km/h {wind_dir}",
            f"**Pressure:** {pressure} mb",
            f"**Visibility:** {visibility} km",
            f"**UV Index:** {uv_index}",
        ]
        return "\n".join(report)
    except (KeyError, IndexError):
        return f"Unable to parse weather data for {location}"


def format_forecast(data: dict, location: str, days: int = 3) -> str:
    """Format weather forecast from wttr.in JSON response."""
    if "error" in data:
        return f"Weather grid offline for {location}: {data['error']}"

    try:
        area = data["nearest_area"][0]
        location_name = area["areaName"][0]["value"]
        country = area["country"][0]["value"]

        report = [f"### {days}-DAY FORECAST: {location_name}, {country}\n"]

        for _i, day in enumerate(data["weather"][:days]):
            date = day["date"]
            max_temp_c = day["maxtempC"]
            min_temp_c = day["mintempC"]
            max_temp_f = day["maxtempF"]
            min_temp_f = day["mintempF"]

            # Get daytime condition (first hourly entry around noon)
            hourly = day["hourly"]
            midday = hourly[4] if len(hourly) > 4 else hourly[0]
            condition = midday["weatherDesc"][0]["value"]
            precip = midday.get("chanceofrain", "0")
            humidity = midday.get("humidity", "0")

            report.append(f"**{date}**")
            report.append(
                f"  {condition} | High: {max_temp_c}°C/{max_temp_f}°F"
                f" | Low: {min_temp_c}°C/{min_temp_f}°F"
            )
            report.append(f"  Rain: {precip}% | Humidity: {humidity}%\n")

        return "\n".join(report)
    except (KeyError, IndexError):
        return f"Unable to parse forecast data for {location}"


def register(mcp):
    @mcp.tool()
    async def get_weather(location: str) -> str:
        """
        Get current weather conditions for a location.
        Example: get_weather("New York") or get_weather("London,UK")
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            data = await fetch_weather(client, location)
        return format_current_weather(data, location)

    @mcp.tool()
    async def get_weather_forecast(location: str, days: int = 3) -> str:
        """
        Get weather forecast for a location (1-3 days).
        Example: get_weather_forecast("Tokyo", 2)
        """
        days = max(1, min(3, days))  # Clamp to 1-3 days
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            data = await fetch_weather(client, location)
        return format_forecast(data, location, days)
