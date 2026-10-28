#!/usr/bin/env python3
"""Haalt weer (KNMI HARMONIE via Open-Meteo, met MET Norway als reserve) en EPEX day-ahead prijzen (Energy-Charts) en
de gasprijs van de beurs (EnergyZero) op en schrijft data.json.
Alleen standaardbibliotheek (Python 3.9+). Draai dit elke dag rond 13:30, dan zijn de prijzen van morgen bekend."""
import json, os, sys, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LAT, LON = 52.37, 4.90               # pas aan naar je eigen woonplaats
CONTACT = "mijn@emailadres.nl"       # MET Norway eist een herkenbare User-Agent met contactgegevens
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data.json")
TZ = ZoneInfo("Europe/Amsterdam")
DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "energiekompas-thuis/1.0 " + CONTACT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def stamp(dt):
    dt = dt.astimezone(TZ)
    return "%s %d %s %d, %02d:%02d" % (DAGEN[dt.weekday()], dt.day, MAANDEN[dt.month - 1], dt.year, dt.hour, dt.minute)

def build_weather(ts, now_utc):
    """ts: lijst van (datetime utc, temp, wolken). Geeft start (ms), temp[], cloud[] per uur tot 23:00 lokaal van dag+2."""
    ts = sorted(ts)
    start = now_utc.replace(minute=0, second=0, microsecond=0)
    end_local = (now_utc.astimezone(TZ) + timedelta(days=2)).replace(hour=23, minute=0, second=0, microsecond=0)
    end = end_local.astimezone(timezone.utc)
    temp, cloud = [], []
    t = start
    while t <= end:
        prev = [x for x in ts if x[0] <= t]
        nxt = [x for x in ts if x[0] >= t]
        if not prev and not nxt:
            raise ValueError("geen weerdata")
        a = prev[-1] if prev else nxt[0]
        b = nxt[0] if nxt else prev[-1]
        if a[0] == b[0]:
            f = 0.0
        else:
            f = (t - a[0]).total_seconds() / (b[0] - a[0]).total_seconds()
        temp.append(round(a[1] + (b[1] - a[1]) * f, 1))
        cloud.append(round(a[2] + (b[2] - a[2]) * f, 1))
        t += timedelta(hours=1)
    return int(start.timestamp() * 1000), temp, cloud

def fetch_openmeteo(now_utc):
    """KNMI HARMONIE (2 km boven Nederland, ververst elk uur) via Open-Meteo, plus ECMWF na 2,5 dag.
    Geeft ook de instraling van het model zelf. Open-Meteo is gratis voor niet-commercieel gebruik (CC BY 4.0)."""
    q = urllib.parse.urlencode({
        "latitude": "%.4f" % LAT, "longitude": "%.4f" % LON, "models": "knmi_seamless", "timezone": "GMT",
        "forecast_days": 4, "past_days": 1,
        "hourly": "temperature_2m,cloud_cover,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,relative_humidity_2m"})
    j = get_json("https://api.open-meteo.com/v1/forecast?" + q)
    h = j["hourly"]
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
    return build_hourly(times, h["temperature_2m"], h["cloud_cover"], h["shortwave_radiation"],
                        h["direct_normal_irradiance"], h["diffuse_radiation"], now_utc, h.get("relative_humidity_2m"))

def build_hourly(times, temp, cloud, ghi, dni, dhi, now_utc, rh=None):
    """Open-Meteo geeft straling als gemiddelde over het voorgaande uur. Een uur dat om t begint,
    hoort dus bij de waarde met tijdlabel t+1 uur. Alle reeksen lopen van het huidige uur tot 23:00 lokaal van dag+2."""
    idx = {t: i for i, t in enumerate(times)}
    start = now_utc.replace(minute=0, second=0, microsecond=0)
    end = ((now_utc.astimezone(TZ) + timedelta(days=2)).replace(hour=23, minute=0, second=0, microsecond=0)).astimezone(timezone.utc)
    out = {"temp": [], "cloud": [], "ghi": [], "dni": [], "dhi": []}
    if rh is not None:
        out["rh"] = []
    t = start
    while t <= end:
        if t not in idx:
            raise ValueError("uur ontbreekt in de verwachting: %s" % t.isoformat())
        i = idx[t]
        j = idx.get(t + timedelta(hours=1), i)
        for k, arr, src in (("temp", temp, i), ("cloud", cloud, i), ("ghi", ghi, j), ("dni", dni, j), ("dhi", dhi, j)):
            v = arr[src]
            if v is None:
                raise ValueError("lege waarde in %s op %s" % (k, t.isoformat()))
            out[k].append(round(float(v), 1))
        if rh is not None:
            if rh[i] is None:
                raise ValueError("lege waarde in rh op %s" % t.isoformat())
            out["rh"].append(int(round(float(rh[i]))))
        t += timedelta(hours=1)
    return int(start.timestamp() * 1000), out

def fetch_weather(now_utc):
    j = get_json("https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=%.4f&lon=%.4f" % (LAT, LON))
    ts = []
    for e in j["properties"]["timeseries"]:
        d = e["data"]["instant"]["details"]
        if "air_temperature" in d and "cloud_area_fraction" in d:
            t = datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            ts.append((t, float(d["air_temperature"]), float(d["cloud_area_fraction"])))
    return build_weather(ts, now_utc)

def hourly_prices(unix, price):
    """Middelt (kwartier)prijzen naar lokale uren. Behoudt alleen dagen met precies 24 volledige uren (€/MWh)."""
    days = {}
    for u, p in zip(unix, price):
        if p is None:
            continue
        dt = datetime.fromtimestamp(u, timezone.utc).astimezone(TZ)
        days.setdefault(dt.strftime("%Y-%m-%d"), {}).setdefault(dt.hour, []).append(float(p))
    out = {}
    for k, hours in days.items():
        if sorted(hours) != list(range(24)):
            continue
        counts = {len(v) for v in hours.values()}
        if len(counts) != 1:
            continue          # een uur met ontbrekende kwartieren: liever niets dan een verkeerde dag
        out[k] = [round(sum(hours[h]) / len(hours[h]), 2) for h in range(24)]
    return out

def fetch_epex(now_utc):
    d0 = now_utc.astimezone(TZ).date()
    q = urllib.parse.urlencode({"bzn": "NL", "start": d0.isoformat(), "end": (d0 + timedelta(days=2)).isoformat()})
    j = get_json("https://api.energy-charts.info/price?" + q)
    return hourly_prices(j["unix_seconds"], j["price"])

def fetch_gas(now_utc):
    """Gasprijs van de beurs per m3, excl. btw, zonder belasting en opslag. Staat vast per dag, nieuw om 05:00 UTC."""
    f = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    q = urllib.parse.urlencode({"fromDate": f(now_utc - timedelta(days=1)), "tillDate": f(now_utc),
                                "interval": 4, "usageType": 2, "inclBtw": "false"})
    j = get_json("https://api.energyzero.nl/v1/energyprices?" + q)
    now = []
    for p in j["Prices"]:
        at = datetime.fromisoformat(p["readingDate"].replace("Z", "+00:00"))
        if at <= now_utc:
            now.append((at, float(p["price"])))
    if not now:
        raise ValueError("geen gasprijs voor nu")
    at, v = max(now)
    return {"v": round(v, 3), "at": int(at.timestamp() * 1000), "stamp": stamp(now_utc)}

HIST_OUT = os.path.join(HERE, "prices-history.json")

def day_minmax(unix, price):
    """Per lokale dag de laagste en hoogste uurprijs en het daggemiddelde (€/MWh). Dagen met minder dan 20 uren vallen af;
    zo tellen de dagen van de zomertijdwissel (23 of 25 uur) wel mee."""
    days = {}
    for u, p in zip(unix, price):
        if p is None:
            continue
        dt = datetime.fromtimestamp(u, timezone.utc).astimezone(TZ)
        days.setdefault(dt.strftime("%Y-%m-%d"), {}).setdefault(dt.hour, []).append(float(p))
    out = {}
    for k, hours in days.items():
        if len(hours) < 20:
            continue
        avg = [sum(v) / len(v) for v in hours.values()]
        out[k] = [round(min(avg), 2), round(max(avg), 2), round(sum(avg) / len(avg), 2)]
    return out

def gas_days(prices):
    """EnergyZero geeft de gasprijs per uur; hij wisselt om 06:00 lokale tijd. Eén waarde per gasdag."""
    out = {}
    for p in prices:
        at = datetime.fromisoformat(p["readingDate"].replace("Z", "+00:00")).astimezone(TZ)
        out[(at - timedelta(hours=6)).strftime("%Y-%m-%d")] = round(float(p["price"]), 3)
    return out

def update_history(now_utc):
    """prices-history.json: per dag de gasprijs (beurs, excl. btw) en de laagste, hoogste en gemiddelde stroomprijs (EPEX).
    Een jaar terug. Is de reeks nog niet compleet, dan haal ik het hele jaar op, anders alleen de laatste dagen."""
    try:
        old = json.load(open(HIST_OUT))
    except Exception:
        old = {}
    today = now_utc.astimezone(TZ).date()
    first = today - timedelta(days=365)
    gas, power = dict(old.get("gas") or {}), dict(old.get("power") or {})
    full = (len(power) < 350 or len(gas) < 350 or min(power) > (first + timedelta(days=7)).isoformat()
            or any(len(v) < 3 for v in power.values()))
    since = first if full else today - timedelta(days=4)
    errors = []
    try:
        q = urllib.parse.urlencode({"bzn": "NL", "start": since.isoformat(), "end": (today + timedelta(days=1)).isoformat()})
        j = get_json("https://api.energy-charts.info/price?" + q)
        power.update(day_minmax(j["unix_seconds"], j["price"]))
    except Exception as e:
        errors.append("stroomhistorie: %s" % e)
    try:
        f = lambda d: datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        q = urllib.parse.urlencode({"fromDate": f(since), "tillDate": now_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                                    "interval": 4, "usageType": 2, "inclBtw": "false"})
        gas.update(gas_days(get_json("https://api.energyzero.nl/v1/energyprices?" + q)["Prices"]))
    except Exception as e:
        errors.append("gashistorie: %s" % e)
    keep = lambda d: {k: d[k] for k in sorted(d) if k >= first.isoformat()}
    new = {"gas": keep(gas), "power": keep(power)}
    if new != {"gas": old.get("gas"), "power": old.get("power")}:
        tmp = HIST_OUT + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(new, fh, separators=(",", ":"))
        os.replace(tmp, HIST_OUT)
    return errors

def main():
    now_utc = datetime.now(timezone.utc)
    try:
        old = json.load(open(OUT))
    except Exception:
        old = {}
    new = dict(old)
    errors = []
    try:
        start, w = fetch_openmeteo(now_utc)
        new.update(start=start, temp=w["temp"], cloud=w["cloud"], ghi=w["ghi"], dni=w["dni"], dhi=w["dhi"],
                   rh=w.get("rh"),
                   src="KNMI HARMONIE via Open-Meteo.com (CC BY 4.0)", stamp=stamp(now_utc),
                   fetched=int(time.time() * 1000), lat=LAT, lon=LON)
    except Exception as e1:
        errors.append("KNMI/Open-Meteo: %s (reserve: MET Norway)" % e1)
        try:
            start, temp, cloud = fetch_weather(now_utc)
            for k in ("ghi", "dni", "dhi", "rh"):
                new.pop(k, None)
            new.update(start=start, temp=temp, cloud=cloud, src="MET Norway (api.met.no), licentie CC BY 4.0",
                       stamp=stamp(now_utc), fetched=int(time.time() * 1000), lat=LAT, lon=LON)
        except Exception as e2:
            errors.append("weer: %s" % e2)
    try:
        fresh = fetch_epex(now_utc)
        today = now_utc.astimezone(TZ).strftime("%Y-%m-%d")
        ep = {k: v for k, v in (old.get("epex") or {}).items() if k >= today}
        ep.update(fresh)
        if fresh:
            new["epexStamp"] = stamp(now_utc)
        new["epex"] = ep
    except Exception as e:
        errors.append("prijzen: %s" % e)
    new.pop("ttf", None)                  # oude, niet bijgewerkte waarde
    try:
        new["gas"] = fetch_gas(now_utc)
    except Exception as e:
        errors.append("gasprijs: %s" % e)
    errors += update_history(now_utc)
    if "temp" not in new:
        print("Geen weerdata beschikbaar, data.json niet geschreven.", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f)
    os.replace(tmp, OUT)
    print("data.json bijgewerkt:", stamp(now_utc), "| prijsdagen:", ", ".join(sorted(new.get("epex", {}))) or "geen")
    for e in errors:
        print("Let op, mislukt ->", e, file=sys.stderr)
    return 0 if not errors else 2

if __name__ == "__main__":
    sys.exit(main())
