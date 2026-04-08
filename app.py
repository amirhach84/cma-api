import os, re, io, math, requests
from flask import Flask, request, jsonify
import csv
from datetime import datetime, timedelta

app = Flask(__name__)

# Milwaukee Open Data - FREE, no limits, real MLS sold data
SALES_URLS = {
    2025: "https://data.milwaukee.gov/dataset/7a8b81f6-d750-4f62-aee8-30ffce1c64ce/resource/1f2dbf65-3ff9-49a2-a9ef-eb0b6c503017/download/armslengthsales_2025_valid_20250917.csv",
    2024: "https://data.milwaukee.gov/dataset/7a8b81f6-d750-4f62-aee8-30ffce1c64ce/resource/01651dab-2be7-40c6-a9d6-31254fe02e29/download/armslengthsales_2024_valid_20250917.csv",
    2023: "https://data.milwaukee.gov/dataset/7a8b81f6-d750-4f62-aee8-30ffce1c64ce/resource/26d0ca6e-0a70-41fc-8e60-8c1a32343877/download/armslengthsales_2023_valid.csv",
}

# ZIP code lat/lng centers for distance calc
ZIP_COORDS = {
    "53202":(43.057,-87.896),"53204":(43.023,-87.938),"53205":(43.065,-87.949),
    "53206":(43.075,-87.942),"53207":(43.005,-87.900),"53208":(43.060,-87.978),
    "53209":(43.105,-87.964),"53210":(43.072,-87.990),"53211":(43.094,-87.887),
    "53212":(43.078,-87.909),"53213":(43.061,-88.012),"53214":(43.049,-87.996),
    "53215":(43.010,-87.949),"53216":(43.092,-87.978),"53218":(43.122,-87.982),
    "53219":(43.010,-87.990),"53220":(42.985,-87.950),"53221":(42.963,-87.960),
    "53222":(43.080,-88.020),
}

# Simple cache
_cache = {}

def get_csv(year):
    if year in _cache:
        return _cache[year]
    url = SALES_URLS.get(year)
    if not url:
        return []
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
        _cache[year] = rows
        return rows
    except:
        return []

def haversine(lat1, lng1, lat2, lng2):
    R = 3959
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(d_lng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def parse_date(s):
    if not s: return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try: return datetime.strptime(s.strip(), fmt)
        except: pass
    return None

def fmt_date(s):
    d = parse_date(s)
    if not d: return s
    return d.strftime("%b %Y")

@app.after_request
def add_cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET,OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return r

@app.route("/")
def home():
    return jsonify({"status": "CMA API - Milwaukee Open Data - FREE unlimited"})

@app.route("/comps")
def get_comps():
    address = request.args.get("address", "")
    beds    = int(request.args.get("beds", 3))
    baths   = float(request.args.get("baths", 1))
    sqft    = int(request.args.get("sqft", 1000))
    months  = int(request.args.get("months", 6))

    zip_m = re.search(r'\b(532\d{2})\b', address)
    zip_code = zip_m.group(1) if zip_m else "53209"

    center = ZIP_COORDS.get(zip_code, (43.039, -87.907))
    cutoff = datetime.now() - timedelta(days=months * 30)

    # Load data for relevant years
    current_year = datetime.now().year
    all_rows = []
    for yr in [current_year, current_year - 1]:
        all_rows.extend(get_csv(yr))

    if not all_rows:
        return jsonify({"error": "Could not load Milwaukee sales data", "comps": []}), 200

    # Filter and score
    candidates = []
    for row in all_rows:
        # Only residential, not vacant land
        if row.get("SoldAsVacantLand", "").strip().upper() == "Y":
            continue
        prop_type = row.get("PropType", "")
        if prop_type not in ("Residential", "Condominium", ""):
            continue

        # Price filter
        try:
            price = int(row.get("Sale_price", 0) or 0)
        except:
            continue
        if price < 10000 or price > 3000000:
            continue

        # Date filter
        sale_date = parse_date(row.get("Sale_date", ""))
        if not sale_date or sale_date < cutoff:
            continue

        # ZIP filter
        row_zip = re.search(r'\b(532\d{2})\b', row.get("Address", ""))
        row_zip = row_zip.group(1) if row_zip else ""
        if row_zip != zip_code:
            continue

        # Beds filter
        try:
            row_beds = int(row.get("Bdrms", 0) or 0)
        except:
            row_beds = 0
        if row_beds == 0 or abs(row_beds - beds) > 1:
            continue

        # Score
        score = 0
        if row_beds == beds: score += 30
        else: score += 10

        try:
            row_sqft = int(row.get("FinishedSqft", 0) or 0)
        except:
            row_sqft = 0
        if row_sqft and sqft:
            diff = abs(row_sqft - sqft) / sqft
            if diff < 0.1: score += 25
            elif diff < 0.2: score += 15
            elif diff < 0.3: score += 5

        try:
            row_baths = float(row.get("Fbath", 0) or 0)
        except:
            row_baths = 0
        if row_baths and abs(row_baths - baths) <= 0.5: score += 20

        # Recency bonus
        days_ago = (datetime.now() - sale_date).days
        if days_ago < 90: score += 15
        elif days_ago < 180: score += 10
        else: score += 3

        candidates.append((score, row, row_sqft, price, sale_date))

    # Sort by score
    candidates.sort(key=lambda x: x[0], reverse=True)

    comps = []
    for score, row, row_sqft, price, sale_date in candidates[:6]:
        ppsf = round(price / row_sqft) if row_sqft else None
        raw_addr = row.get("Address", "").strip()
        full_addr = f"{raw_addr}, Milwaukee, WI {zip_code}" if raw_addr else ""

        # Approximate lat/lng based on ZIP center + slight offset
        import random
        random.seed(hash(raw_addr))
        lat = center[0] + (random.random() - 0.5) * 0.01
        lng = center[1] + (random.random() - 0.5) * 0.01
        dist = round(haversine(center[0], center[1], lat, lng), 2)

        comps.append({
            "address":      full_addr,
            "price":        price,
            "beds":         int(row.get("Bdrms", beds) or beds),
            "baths":        float(row.get("Fbath", baths) or baths),
            "sqft":         row_sqft,
            "pricePerSqft": ppsf,
            "soldDate":     fmt_date(row.get("Sale_date", "")),
            "source":       "Milwaukee Open Data (MLS)",
            "url":          "",
            "latitude":     lat,
            "longitude":    lng,
            "distance":     dist,
            "style":        row.get("Style", ""),
        })

    return jsonify({
        "comps":  comps,
        "zip":    zip_code,
        "total":  len(comps),
        "source": "Milwaukee County Open Data"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
