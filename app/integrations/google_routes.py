"""Travel-time facts from Google Maps Routes API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx


class RoutingIntegrationError(RuntimeError):
    pass


class GoogleRoutesClient:
    ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(self, api_key: str, *, http: httpx.Client | None = None) -> None:
        if not api_key:
            raise RoutingIntegrationError("GOOGLE_MAPS_API_KEY is not configured")
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=10)

    def duration_minutes(
        self, origin: str, destination: str, departure: datetime, mode: str
    ) -> int:
        payload: dict[str, Any] = {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": mode,
            "computeAlternativeRoutes": False,
        }
        if mode == "DRIVE":
            payload["routingPreference"] = "TRAFFIC_AWARE"
            payload["departureTime"] = departure.isoformat()
        try:
            response = self.http.post(
                self.ENDPOINT,
                headers={
                    "X-Goog-Api-Key": self.api_key,
                    "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise RoutingIntegrationError("Google Routes could not be reached") from exc
        if response.is_error:
            raise RoutingIntegrationError(f"Route estimate failed ({response.status_code})")
        routes = response.json().get("routes", [])
        if not routes:
            raise RoutingIntegrationError("No route was found between the event and gym")
        seconds = _seconds(routes[0].get("duration"))
        return max(1, (seconds + 59) // 60)


def _seconds(value: Any) -> int:
    raw = str(value or "")
    if not raw.endswith("s"):
        raise RoutingIntegrationError("Route response had no duration")
    try:
        return int(round(float(raw[:-1])))
    except ValueError as exc:
        raise RoutingIntegrationError("Route response had an invalid duration") from exc


def _waypoint(value: str) -> dict[str, str]:
    raw = value.strip()
    if raw.lower().startswith("place_id:"):
        place_id = raw.split(":", 1)[1].strip()
        if not place_id:
            raise RoutingIntegrationError("Saved Place ID is empty")
        return {"placeId": place_id}
    return {"address": raw}
