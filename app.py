import os
import requests
import re
from flask import Flask, request, jsonify

app = Flask(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.redfin.com/city/12064/WI/Milwaukee/filter/include=sold-3mo",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# Milwaukee ZIP -> Redfin region_id mapping
ZIP_REGION = {
    "53202": 29440, "53204": 29441, "53205": 29442, "53206": 29443,
    "53207": 29444, "53208": 29445, "53209": 29446, "53210": 29447,
    "53211": 29448, "53212": 29449, "53213": 29450, "53214": 29451,
    "53215": 29452, "53216": 29453, "53218": 29454, "53219": 29455,
    "53220": 29456, "53221": 29457, "53222": 29458,
}

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/")
def home():
    return jsonify({"status": "CMA API running", "version": "2.1"})

@app.route("/comps")
def get_comps():
    address = request.args.get("address", "")
    beds    = int(request.args.get("beds", 3))
    months  = int(request.args.get("months", 6))

    m = re.search(r'\b(5[23]\d{3})\b', address)
    zip_code = m.group(1) if m else "53209"

    # Use Redfin's CSV download - status=9 is sold
    # region_type=6 = zip code, use zip code string directly as region_id
    params = {
        "al": "1",
        "market": "milwaukee",
        "min_num_beds": str(max(1, beds - 1)),
        "max_num_beds": str(beds + 1),
        "num_homes": "100",
        "page_number": "1",
        "region_id": zip_code,
        "region_type": "6",
        "sf": "1,2,3,5,6,7",
        "status": "9",
        "uipt": "1,2,3",
        "sold_within_days": str(months * 30),
        "v": "8",
    }

    try:
        session = requests.Session()
        # First hit the main page to get cookies
        session.get("https://www.redfin.com/city/12064/WI/Milwaukee", 
                   headers=HEADERS, timeout=10)
        
        r = session.get(
            "https://www.redfin.com/stingray/api/gis-csv",
            params=params,
            headers=HEADERS,
            timeout=20
        )

        if not r.ok:
            return jsonify({"error": f"Redfin {r.status_code}", "comps": []}), 200

        text = r.text.strip()
        if not text or len(text) < 50:
            return jsonify({"comps": [], "debug": "empty response"})

        lines = text.split("\n")
        if len(lines) < 2:
            return jsonify({"comps": []})

        # Parse headers
        raw_headers = lines[0].split(",")
        hdrs = [h.strip().strip('"').upper() for h in raw_headers]

        def col(row_cols, *names):
            for name in names:
                for i, h in enumerate(hdrs):
                    if name.upper() in h and i < len(row_cols):
                        v = row_cols[i].strip().strip('"')
                        if v: return v
            return ""

        comps = []
        for line in lines[1:]:
            if not line.strip(): continue
            # Parse CSV with quote handling
            cols = []
            cur = ""
            inq = False
            for ch in line:
                if ch == '"': inq = not inq
                elif ch == ',' and not inq:
                    cols.append(cur.strip().strip('"'))
                    cur = ""
                else:
                    cur += ch
            cols.append(cur.strip().strip('"'))

            price_str = col(cols, "PRICE")
            try:
                price = int(float(price_str.replace("$","").replace(",","")))
            except:
                continue
            if price < 5000: continue

            sqft_str = col(cols, "SQUARE FEET", "SQFT")
            sqft_val = int(float(sqft_str)) if sqft_str else 0
            ppsf = round(price / sqft_val) if sqft_val > 0 else None

            addr  = col(cols, "ADDRESS")
            city  = col(cols, "CITY")
            state = col(cols, "STATE OR PROVINCE", "STATE")
            zipv  = col(cols, "ZIP OR POSTAL CODE", "ZIP")
            bedsv = col(cols, "BEDS", "BEDROOMS")
            bathv = col(cols, "BATHS", "BATHROOMS")
            sold  = col(cols, "SOLD DATE", "DATE SOLD", "DATE")
            lat   = col(cols, "LATITUDE")
            lng   = col(cols, "LONGITUDE")
            url   = col(cols, "URL")

            if not addr: continue

            full = f"{addr}, {city}, {state} {zipv}".strip(", ")
            comps.append({
                "address": full,
                "price": price,
                "beds": int(float(bedsv)) if bedsv else beds,
                "baths": float(bathv) if bathv else 1,
                "sqft": sqft_val,
                "pricePerSqft": ppsf,
                "soldDate": sold,
                "source": "Redfin",
                "url": ("https://www.redfin.com" + url) if url and not url.startswith("http") else url,
                "latitude": float(lat) if lat else None,
                "longitude": float(lng) if lng else None,
            })

        comps = sorted(comps, key=lambda x: x.get("soldDate",""), reverse=True)[:6]
        return jsonify({"comps": comps, "zip": zip_code, "total": len(comps)})

    except Exception as e:
        return jsonify({"error": str(e), "comps": []}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
