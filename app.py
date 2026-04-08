import os
import requests
import json
import re
from flask import Flask, request, jsonify

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.redfin.com/",
}

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
def home():
    return jsonify({"status": "CMA API running - Redfin free data"})

@app.route("/comps")
def get_comps():
    address = request.args.get("address", "")
    beds    = int(request.args.get("beds", 3))
    months  = int(request.args.get("months", 6))

    # Extract ZIP
    m = re.search(r'\b(5[23]\d{3})\b', address)
    zip_code = m.group(1) if m else "53209"

    params = {
        "al": 1,
        "market": "milwaukee",
        "min_num_beds": max(1, beds - 1),
        "max_num_beds": beds + 1,
        "num_homes": 50,
        "region_id": zip_code,
        "region_type": 6,
        "sf": "1,2,3,5,6,7",
        "status": 9,
        "sold_within_days": months * 30,
        "uipt": "1,2,3",
        "v": 8,
    }

    try:
        r = requests.get(
            "https://www.redfin.com/stingray/api/gis-csv",
            params=params,
            headers=HEADERS,
            timeout=15
        )

        if not r.ok:
            return jsonify({"error": f"Redfin {r.status_code}"}), 500

        lines = r.text.strip().split("\n")
        if len(lines) < 2:
            return jsonify({"comps": []})

        hdrs = lines[0].split(",")
        def idx(name):
            for i, h in enumerate(hdrs):
                if name.lower() in h.lower():
                    return i
            return -1

        comps = []
        for line in lines[1:]:
            if not line.strip():
                continue
            # Handle quoted fields
            cols = []
            cur = ""
            inq = False
            for ch in line:
                if ch == '"':
                    inq = not inq
                elif ch == ',' and not inq:
                    cols.append(cur.strip().strip('"'))
                    cur = ""
                else:
                    cur += ch
            cols.append(cur.strip().strip('"'))

            def g(name):
                i = idx(name)
                return cols[i] if i >= 0 and i < len(cols) else ""

            price_str = g("PRICE")
            try:
                price = int(float(price_str.replace("$","").replace(",","")))
            except:
                continue

            if price < 10000:
                continue

            sqft_str = g("SQUARE FEET")
            sqft_val = int(float(sqft_str)) if sqft_str else 0
            ppsf = round(price / sqft_val) if sqft_val > 0 else None

            addr      = g("ADDRESS")
            city      = g("CITY")
            state     = g("STATE")
            zip_v     = g("ZIP")
            beds_v    = g("BEDS")
            baths_v   = g("BATHS")
            sold_date = g("SOLD DATE") or g("DATE")
            lat_v     = g("LATITUDE")
            lng_v     = g("LONGITUDE")
            url_v     = g("URL")

            full_addr = f"{addr}, {city}, {state} {zip_v}".strip(", ")
            if not addr:
                continue

            comps.append({
                "address": full_addr,
                "price": price,
                "beds": int(float(beds_v)) if beds_v else beds,
                "baths": float(baths_v) if baths_v else 1,
                "sqft": sqft_val,
                "pricePerSqft": ppsf,
                "soldDate": sold_date,
                "source": "Redfin",
                "url": url_v if url_v and url_v.startswith("http") else ("https://www.redfin.com" + url_v if url_v else ""),
                "latitude": float(lat_v) if lat_v else None,
                "longitude": float(lng_v) if lng_v else None,
            })

        comps = sorted(comps, key=lambda x: x["soldDate"] or "", reverse=True)[:6]
        return jsonify({"comps": comps, "zip": zip_code, "source": "Redfin"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
