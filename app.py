import os
import requests
import re
import json
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
def home():
    return jsonify({"status": "CMA API v3 - Zillow"})

@app.route("/comps")
def get_comps():
    address = request.args.get("address", "")
    beds    = int(request.args.get("beds", 3))
    months  = int(request.args.get("months", 6))

    zip_m = re.search(r'\b(5[23]\d{3})\b', address)
    zip_code = zip_m.group(1) if zip_m else "53209"

    # Zillow search API - search for recently sold homes
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.zillow.com/",
        "cookie": "",
    }

    # Zillow recently sold search
    search_params = {
        "searchQueryState": json.dumps({
            "pagination": {},
            "isMapVisible": True,
            "mapBounds": {},
            "regionSelection": [{"regionId": 0, "regionType": 7}],
            "filterState": {
                "isRecentlySold": {"value": True},
                "doz": {"value": f"{months}m"},
                "beds": {"min": beds - 1, "max": beds + 1},
            },
            "isListVisible": True,
            "customRegionId": None,
        }),
        "wants": json.dumps({"cat1": ["listResults"]}),
        "requestId": "1",
        "searchValue": f"{zip_code} Milwaukee WI",
    }

    try:
        # Use Zillow's search endpoint
        r = requests.get(
            "https://www.zillow.com/search/GetSearchPageState.htm",
            params=search_params,
            headers=headers,
            timeout=15
        )

        if r.ok:
            data = r.json()
            results = data.get("cat1", {}).get("searchResults", {}).get("listResults", [])
            comps = []
            for item in results[:8]:
                price = item.get("unformattedPrice") or item.get("price", 0)
                if isinstance(price, str):
                    price = int(price.replace("$","").replace(",","").replace("K","000"))
                sqft_v = item.get("area", 0)
                ppsf = round(price/sqft_v) if sqft_v else None
                addr = item.get("address","")
                if not addr or not price:
                    continue
                comps.append({
                    "address": addr,
                    "price": price,
                    "beds": item.get("beds", beds),
                    "baths": item.get("baths", 1),
                    "sqft": sqft_v,
                    "pricePerSqft": ppsf,
                    "soldDate": item.get("soldPrice", {}).get("date","") if isinstance(item.get("soldPrice"),dict) else "",
                    "source": "Zillow",
                    "url": "https://www.zillow.com" + item.get("detailUrl",""),
                    "latitude": item.get("latLong", {}).get("latitude"),
                    "longitude": item.get("latLong", {}).get("longitude"),
                })
            if comps:
                return jsonify({"comps": comps[:6], "zip": zip_code, "source": "Zillow"})

        # Fallback: use Rentcast if available
        rentcast_key = os.environ.get("RENTCAST_KEY", "508e798f776b4a5e929d81747e2d7ccb")
        rp = {
            "address": address, "bedrooms": beds, "bathrooms": 1,
            "squareFootage": 1000, "propertyType": "Single Family",
            "maxRadius": 0.5, "daysOld": months * 30, "compCount": 6,
        }
        rr = requests.get(
            "https://api.rentcast.io/v1/avm/value",
            params=rp,
            headers={"X-Api-Key": rentcast_key, "Accept": "application/json"},
            timeout=15
        )
        if rr.ok:
            rd = rr.json()
            comps = []
            for c in rd.get("comparables", [])[:6]:
                price = c.get("price") or c.get("lastSalePrice", 0)
                sqft_v = c.get("squareFootage", 0)
                comps.append({
                    "address": c.get("formattedAddress",""),
                    "price": price,
                    "beds": c.get("bedrooms", beds),
                    "baths": c.get("bathrooms", 1),
                    "sqft": sqft_v,
                    "pricePerSqft": round(price/sqft_v) if sqft_v and price else None,
                    "soldDate": c.get("lastSaleDate","")[:7] if c.get("lastSaleDate") else "",
                    "source": "Rentcast MLS",
                    "url": "",
                    "latitude": c.get("latitude"),
                    "longitude": c.get("longitude"),
                })
            if comps:
                return jsonify({"comps": comps, "zip": zip_code, "source": "Rentcast"})

        return jsonify({"comps": [], "error": "No data found", "zip": zip_code})

    except Exception as e:
        return jsonify({"error": str(e), "comps": []}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
