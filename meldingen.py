#!/usr/bin/env python3
"""Stuurt meldingen van Energiekompas naar Telegram. Draait elke 10 minuten op de server (cron), los van de app.
Leest data.json, indoor.json en prices-history.json van de gepubliceerde site en onthoudt in STATE wat al gemeld is.

Meldingen:
- Ventileren heeft geen zin (per verdieping): binnen vochtig maar buiten niet droger, of binnen droog en buiten droger.
- Stroom: rond 13:30 de goedkope en dure uren van morgen, en 30 minuten voor een goedkoop of duur blok een herinnering.
- Gas en stroom: de prijs van vandaag (gas) of morgen (stroom) wijkt meer dan 10% af van het gemiddelde van de week ervoor.

Alleen standaardbibliotheek (Python 3.9+). Test met: python3 meldingen.py --droog [--nu 2026-10-28T13:40]"""
import argparse, json, os, subprocess, sys, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SITE = os.environ.get("EK_SITE", "https://chrispym.github.io/energiekompas/")   # voor een test: file:///pad/naar/map/
NOTIFY = "/root/scripts/notify.sh"
STATE = "/var/lib/energiekompas-meldingen.json"
OPSLAG = 0.14            # belasting en opslag per kWh incl. btw, zoals de standaard in de app
DREMPEL = 0.10           # prijsverandering ten opzichte van de week ervoor
STIL = (22, 7)           # geen meldingen tussen 22:00 en 07:00 (wat dan speelt, komt om 07:00)
VOORAF = 30              # minuten voor een goedkoop of duur blok
MIN_BLOK = 2             # herinnering alleen voor blokken van minstens zoveel uur
TZ = ZoneInfo("Europe/Amsterdam")
DAGEN = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]

def get_json(name):
    req = urllib.request.Request(SITE + name, headers={"Cache-Control": "no-cache", "User-Agent": "energiekompas-meldingen/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def eur(v, d=2):
    return ("-" if v < 0 else "") + "€ " + ("%.*f" % (d, abs(v))).replace(".", ",")

def nf(v, d=0):
    return ("%.*f" % (d, v)).replace(".", ",")

def uren(s, e):
    return "%02d:00–%02d:00" % (s, e)

def abs_hum(t, rh):
    """Gram waterdamp per m³, dezelfde formule als in de app."""
    es = 6.112 * 2.718281828459045 ** (17.62 * t / (243.12 + t))
    return 216.7 * (rh / 100 * es) / (273.15 + t)

def consumer(mwh):
    return mwh / 1000 * 1.21 + OPSLAG

# ---------- Stroom: goedkope en dure blokken ----------

def blokken(prices):
    """Indeling zoals de app: goedkoopste derde (8 uur) en duurste derde. Aaneengesloten uren vormen een blok."""
    srt = sorted(prices)
    t1, t2 = srt[7], srt[15]
    cls = [0 if p <= t1 else (1 if p <= t2 else 2) for p in prices]
    out = []
    for h, c in enumerate(cls):
        if c == 1:
            continue
        if out and out[-1]["c"] == c and out[-1]["e"] == h:
            out[-1]["e"] = h + 1
            out[-1]["p"].append(prices[h])
        else:
            out.append({"c": c, "s": h, "e": h + 1, "p": [prices[h]]})
    return out

def beste_venster(prices, n, sign):
    best = None
    for s in range(0, 25 - n):
        v = sum(prices[s:s + n]) / n
        if best is None or sign * v > sign * best[1]:
            best = (s, v)
    return best

def dagoverzicht(key, mwh, wk):
    prices = [consumer(v) for v in mwh]
    d = datetime.strptime(key, "%Y-%m-%d")
    bl = blokken(prices)
    lo, hi = beste_venster(prices, 3, -1), beste_venster(prices, 3, 1)
    regels = ["⚡ <b>Stroom %s %d %s</b>" % (DAGEN[d.weekday()], d.day, MAANDEN[d.month - 1]),
              "Goedkoopste 3 uur: <b>%s</b> (gem. %s/kWh)" % (uren(lo[0], lo[0] + 3), eur(lo[1], 3)),
              "Duurste 3 uur: <b>%s</b> (gem. %s/kWh)" % (uren(hi[0], hi[0] + 3), eur(hi[1], 3))]
    g = [b for b in bl if b["c"] == 0]
    r = [b for b in bl if b["c"] == 2]
    if g:
        regels.append("🟢 Goedkoop: " + ", ".join(uren(b["s"], b["e"]) for b in g))
    if r:
        regels.append("🔴 Duur: " + ", ".join(uren(b["s"], b["e"]) for b in r))
    regels.append("Prijs per uur %s tot %s, incl. btw en %s opslag." % (eur(min(prices)), eur(max(prices)), eur(OPSLAG)))
    if wk:
        regels.append(wk)
    return "\n".join(regels)

# ---------- Prijsverandering ten opzichte van de week ervoor ----------

def weekverschil(serie, key, waarde):
    """Vergelijkt waarde met het gemiddelde van de 7 dagen voor key. Geeft (fractie, gemiddelde) of None."""
    d = datetime.strptime(key, "%Y-%m-%d").date()
    vorige = [serie[k] for k in ((d - timedelta(days=i)).isoformat() for i in range(1, 8)) if k in serie]
    if len(vorige) < 5:
        return None
    gem = sum(vorige) / len(vorige)
    if gem <= 0:
        return None
    return (waarde - gem) / gem, gem

def wk_tekst(naam, f, gem, nu, eenheid, d):
    pijl = "📈 gestegen" if f > 0 else "📉 gedaald"
    return "%s <b>%s %s%%</b> ten opzichte van de week ervoor: %s%s tegen gemiddeld %s%s." % (
        naam, pijl, nf(abs(f) * 100), eur(nu, d), eenheid, eur(gem, d), eenheid)

# ---------- Ventileren per verdieping ----------

def buiten_per_uur(data, now):
    """Lijst (ms, g/m³) per uur uit data.json. Zonder vochtigheid neemt de app 85% aan; ik doe hetzelfde."""
    start, temp, rh = data.get("start"), data.get("temp") or [], data.get("rh") or []
    if not isinstance(start, (int, float)):
        return []
    out = []
    for i, t in enumerate(temp):
        h = rh[i] if i < len(rh) and isinstance(rh[i], (int, float)) else 85
        out.append((start + i * 3600000, abs_hum(t, h)))
    return out

def vent_status(naam, m, buiten, now):
    """Geeft (sleutel, tekst) als ventileren op deze verdieping niet rendabel is, anders None."""
    if not m or not isinstance(m.get("h"), (int, float)) or not isinstance(m.get("t"), (int, float)):
        return None
    if now.timestamp() * 1000 - m.get("at", 0) > 3 * 3600000:
        return None                       # meting te oud
    ah_in = abs_hum(m["t"], m["h"])
    nu_ms = now.timestamp() * 1000
    nu = [g for ms, g in buiten if ms <= nu_ms < ms + 3600000]
    if not nu:
        return None
    gain = ah_in - nu[0]
    eind = now.replace(hour=22, minute=0, second=0, microsecond=0).timestamp() * 1000
    later = [(ms, ah_in - g) for ms, g in buiten if nu_ms < ms <= eind]
    kop = "<b>%s</b> %s%% bij %s °C (%s g/m³, buiten %s g/m³)" % (
        naam, nf(m["h"]), nf(m["t"], 1), nf(ah_in, 1), nf(nu[0], 1))
    if m["h"] > 60 and gain < 1.0:
        venster = None
        for ms, g in later:
            if g >= 1.0:
                if venster is None:
                    venster = [ms, ms]
                elif ms - venster[1] == 3600000:
                    venster[1] = ms
                else:
                    break
        if venster:
            s = datetime.fromtimestamp(venster[0] / 1000, TZ).hour
            e = datetime.fromtimestamp(venster[1] / 1000, TZ).hour + 1
            return ("vochtig-later",
                    kop + "\nNu niet ventileren: buiten is het niet droger. Ventileer %s, dan is de lucht buiten droger dan binnen." % uren(s, e))
        return ("vochtig-geen",
                kop + "\nVentileren heeft vandaag geen zin: buiten is de lucht niet droger. Houd de WTW hoog zonder ramen open, "
                      "zet de verwarming een halve graad hoger en laat de was niet binnen drogen.")
    if m["h"] < 40 and gain > 1.0:
        return ("droog",
                kop + "\nNiet extra ventileren: buiten is de lucht droger, dus het wordt binnen nog droger. Houd de ventilatie op de gewone stand.")
    return None

# ---------- Hoofdlijn ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--droog", action="store_true", help="niet versturen en niets onthouden, alleen tonen")
    ap.add_argument("--nu", help="doe alsof het nu dit tijdstip is (lokale tijd, bijv. 2026-10-28T13:40)")
    a = ap.parse_args()
    now = datetime.fromisoformat(a.nu).replace(tzinfo=TZ) if a.nu else datetime.now(TZ)
    try:
        state = json.load(open(STATE))
    except Exception:
        state = {}
    if a.droog:
        state = {}
    data, indoor, hist = get_json("data.json"), get_json("indoor.json"), get_json("prices-history.json")
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    stil = now.hour >= STIL[0] or now.hour < STIL[1]
    berichten = []
    epex = data.get("epex") or {}
    avg = {k: consumer(v[2]) for k, v in (hist.get("power") or {}).items() if len(v) > 2}

    # Dagoverzicht van morgen, zodra de prijzen er zijn (rond 13:00).
    if not stil and tomorrow in epex and len(epex[tomorrow]) == 24 and state.get("overzicht") != tomorrow:
        prices = [consumer(v) for v in epex[tomorrow]]
        nu_gem = sum(prices) / 24
        w = weekverschil(avg, tomorrow, nu_gem)
        wk = wk_tekst("De gemiddelde stroomprijs van morgen is", w[0], w[1], nu_gem, "/kWh", 3) if w and abs(w[0]) > DREMPEL else None
        berichten.append(dagoverzicht(tomorrow, epex[tomorrow], wk))
        state["overzicht"] = tomorrow

    # Herinnering 30 minuten voor een goedkoop of duur blok van vandaag (of net na middernacht van morgen).
    if not stil:
        gemeld = set(state.get("blokken") or [])
        for key in (today, tomorrow):
            if key not in epex or len(epex[key]) != 24:
                continue
            d = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=TZ)
            for b in blokken([consumer(v) for v in epex[key]]):
                if b["e"] - b["s"] < MIN_BLOK:
                    continue
                begin = d.replace(hour=b["s"])
                if begin.hour < STIL[1] or begin.hour >= STIL[0]:
                    continue                   # nachtblokken staan in het dagoverzicht
                tag = "%s-%02d-%d" % (key, b["s"], b["c"])
                if tag in gemeld or not (begin - timedelta(minutes=VOORAF) <= now < begin):
                    continue
                gem = sum(b["p"]) / len(b["p"])
                if b["c"] == 0:
                    berichten.append("🟢 <b>Goedkope stroom %s</b> (gem. %s/kWh). Goed moment voor de vaatwasser, de was of de droger." % (uren(b["s"], b["e"]), eur(gem, 3)))
                else:
                    berichten.append("🔴 <b>Dure stroom %s</b> (gem. %s/kWh). Stel grote verbruikers uit tot daarna." % (uren(b["s"], b["e"]), eur(gem, 3)))
                gemeld.add(tag)
        state["blokken"] = sorted(t for t in gemeld if t[:10] >= today)

    # Gasprijs van vandaag tegen de week ervoor (nieuwe prijs om 06:00).
    gas = hist.get("gas") or {}
    if not stil and today in gas and state.get("gas") != today:
        w = weekverschil(gas, today, gas[today])
        if w and abs(w[0]) > DREMPEL:
            berichten.append("🔥 " + wk_tekst("De gasprijs van de beurs is", w[0], w[1], gas[today], "/m³", 2) + " Excl. btw.")
        state["gas"] = today

    # Ventileren: per verdieping, één melding zolang de toestand dezelfde blijft.
    buiten = buiten_per_uur(data, now)
    vent = state.get("vent") or {}
    delen = []
    for loc, naam in (("beneden", "Beneden"), ("boven", "Boven")):
        r = vent_status(naam, indoor.get(loc), buiten, now)
        sleutel = r[0] + "@" + today if r else None
        if r and vent.get(loc) != sleutel and not stil:
            delen.append(r[1])
            vent[loc] = sleutel
        elif not r:
            vent.pop(loc, None)
    if delen:
        berichten.append("💨 <b>Ventileren</b>\n" + "\n\n".join(delen))
    state["vent"] = vent

    for b in berichten:
        if a.droog:
            print(b + "\n---")
        else:
            subprocess.run([NOTIFY, b], check=False)
    if not a.droog:
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE)
    if a.droog and not berichten:
        print("Geen meldingen op", now.isoformat())
    return 0

if __name__ == "__main__":
    sys.exit(main())
