import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY1 = os.getenv("RIDB_API_KEY")
API_KEY2 = os.getenv("GOOGLE_MAPS_API_KEY")

def get_api_data():
    url = "https://ridb.recreation.gov/api/v1/recareas"

    headers = {
        "apikey": API_KEY1
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    return response.json()

def get_google_maps_data():
    url = "https://places.googleapis.com/v1/places:searchNearby"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY2,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.rating,places.location"
    }

    payload = {
        "includedTypes": ["park"],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": 40.7608,
                    "longitude": -111.8910
                },
                "radius": 10000.0
            }
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=15
    )

    print("Google API Status:", response.status_code)

    if response.status_code != 200:
        print("Google API Error:", response.text)

    response.raise_for_status()

    return response.json()

if __name__ == "__main__":
    data = get_api_data()

    for area in data["RECDATA"]:
        print(area["RecAreaName"])

    google_data = get_google_maps_data()

    for place in google_data["places"]:
        print(place["displayName"]["text"])