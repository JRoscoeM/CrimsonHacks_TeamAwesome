import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY1")

def get_api_data():
    url = "https://ridb.recreation.gov/api/v1/recareas"

    headers = {
        "apikey": API_KEY
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=10
    )

    response.raise_for_status()

    return response.json()

if __name__ == "__main__":
    data = get_api_data()

    for area in data["RECDATA"]:
        print(area["RecAreaName"])