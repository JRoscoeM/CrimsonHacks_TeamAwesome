"""Google Places (New) address autocomplete, called only while editing an origin.

The key stays on the server. Predictions and selected addresses are not written
to the places cache. A session token joins predictions to the selected details.
"""

import json
import math
import os
from urllib.parse import quote

from .. import keys
from .http import SourceError, request_json

BASE_URL = "https://places.googleapis.com/v1/places"


def enabled() -> bool:
    return bool(keys.GOOGLE_MAPS_API_KEY) and os.environ.get("GOOGLE_AUTOCOMPLETE", "on").lower() not in {"off", "0", "false"}


def _headers(fields: str) -> dict:
    if not enabled():
        raise SourceError("Address suggestions are not configured")
    return {"X-Goog-Api-Key": keys.GOOGLE_MAPS_API_KEY,
            "Content-Type": "application/json", "X-Goog-FieldMask": fields}


def suggest(query: str, token: str) -> list[dict[str, str]]:
    """Up to five US addresses/places, with a soft geographic bias toward Utah."""
    if len(query.strip()) < 3:
        return []
    payload = {
        "input": query.strip()[:200], "sessionToken": token,
        "includedRegionCodes": ["us"], "languageCode": "en",
        "locationBias": {"rectangle": {
            "low": {"latitude": 36.4, "longitude": -114.6},
            "high": {"latitude": 42.6, "longitude": -108.4},
        }},
    }
    response = request_json(
        BASE_URL + ":autocomplete", data=json.dumps(payload).encode(),
        headers=_headers("suggestions.placePrediction.placeId,suggestions.placePrediction.text.text"),
        retries=1, timeout=5,
    )
    try:
        predictions = [item["placePrediction"] for item in response.get("suggestions", []) if "placePrediction" in item]
        return [{"id": p["placeId"], "label": p["text"]["text"], "source": "google"}
                for p in predictions[:5] if p.get("placeId") and p.get("text", {}).get("text")]
    except (AttributeError, TypeError, KeyError) as error:
        raise SourceError("Invalid address suggestions response") from error


def resolve(place_id: str, token: str) -> dict:
    """Fetch only the address and coordinates needed to set the trip origin."""
    response = request_json(
        BASE_URL + "/" + quote(place_id, safe=""),
        params={"sessionToken": token}, headers=_headers("formattedAddress,location"),
        retries=1, timeout=5,
    )
    try:
        lat, lon = float(response["location"]["latitude"]), float(response["location"]["longitude"])
        label = response["formattedAddress"]
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 and label):
            raise ValueError("Invalid location")
        return {"lat": lat, "lon": lon, "label": label}
    except (KeyError, TypeError, ValueError) as error:
        raise SourceError("No address coordinates returned") from error
