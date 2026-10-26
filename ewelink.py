#!/usr/bin/env python3
"""Haalt temperatuur en luchtvochtigheid van twee sensors uit de eWeLink-cloud en schrijft indoor.json.
Alleen standaardbibliotheek (Python 3.9+). Werkt met een gratis APP ID van dev.ewelink.cc, dus via OAuth2.0.

  python ewelink.py --login   eenmalig op je eigen computer: inloggen in de browser, tokens gaan als
                              GitHub-secret EWELINK_TOKENS naar de repository (via gh), daarna volgt --list
  python ewelink.py --list    toont alle apparaten met hun velden
  python ewelink.py           schrijft indoor.json (zo draait het in GitHub Actions)

Omgevingsvariabelen: EWELINK_APPID, EWELINK_APPSECRET, EWELINK_REGION (standaard eu), EWELINK_TOKENS,
EWELINK_DEVICE_BENEDEN, EWELINK_DEVICE_BOVEN (apparaat-ID of naam), EWELINK_REDIRECT_URL,
EWELINK_FORCE_REFRESH (true: tokens nu verversen, om het verversen te testen).
Bronnen: github.com/coolkit-carl/eWeLink-API (OAuth2.0.md, UIIDProtocol.md) en github.com/nocmt/ewelink-api-next."""
import base64, hashlib, hmac, http.server, json, os, secrets, subprocess, sys, time, urllib.error, urllib.parse, urllib.request, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "indoor.json")
REDIRECT = os.environ.get("EWELINK_REDIRECT_URL") or "http://127.0.0.1:8000/redirectUrl"
DAY = 86400000
REFRESH_BEFORE = 10 * DAY            # access token (30 dagen geldig) verversen als hij binnen 10 dagen verloopt

class Fout(Exception):
    pass

def env(name, default=None):
    v = os.environ.get(name, "").strip()
    if not v and default is None:
        raise Fout("omgevingsvariabele %s ontbreekt" % name)
    return v or default

def now_ms():
    return int(time.time() * 1000)

def domain(region):
    return "https://%s-apia.coolkit.%s" % (region, "cn" if region == "cn" else "cc")

def sign(msg):
    """HMAC-SHA256 met de APP SECRET als sleutel, Base64."""
    return base64.b64encode(hmac.new(env("EWELINK_APPSECRET").encode(), msg.encode(), hashlib.sha256).digest()).decode()

def call(region, method, path, body=None, params=None, at=None):
    url = domain(region) + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {"X-CK-Appid": env("EWELINK_APPID"), "X-CK-Nonce": secrets.token_hex(4)}
    data = None
    if body is not None:
        data = json.dumps(body, separators=(",", ":"))   # precies deze tekst wordt ondertekend en verstuurd
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = "Sign " + sign(data)
        data = data.encode()
    else:
        headers["Authorization"] = "Bearer " + at
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        raise Fout("eWeLink gaf HTTP %d op %s (403 kan betekenen dat het maandlimiet van de gratis APP ID op is)" % (e.code, path))
    except (urllib.error.URLError, TimeoutError) as e:
        raise Fout("geen verbinding met eWeLink (%s)" % e)
    if res.get("error") != 0:
        uitleg = {401: "token ongeldig, misschien is er elders opnieuw ingelogd", 402: "token verlopen",
                  406: "ondertekening of rechten afgewezen, controleer APP ID en APP SECRET",
                  407: "deze APP ID mag deze functie niet gebruiken", 412: "maandlimiet van de APP ID bereikt"}
        code = res.get("error")
        raise Fout("eWeLink-fout %s op %s: %s" % (code, path, uitleg.get(code, res.get("msg") or "onbekend")))
    return res.get("data") or {}

def mask(*values):
    if os.environ.get("GITHUB_ACTIONS"):
        for v in values:
            print("::add-mask::" + v)

def save_tokens(tok):
    """Zet de tokens als GitHub-secret EWELINK_TOKENS. Lokaal met je gh-login, in Actions met EWELINK_GH_TOKEN."""
    cmd = ["gh", "secret", "set", "EWELINK_TOKENS"]
    if os.environ.get("GITHUB_REPOSITORY"):
        cmd += ["--repo", os.environ["GITHUB_REPOSITORY"]]
    e = dict(os.environ)
    if os.environ.get("EWELINK_GH_TOKEN"):
        e["GH_TOKEN"] = os.environ["EWELINK_GH_TOKEN"]
    try:
        p = subprocess.run(cmd, input=json.dumps(tok), text=True, capture_output=True, cwd=HERE, env=e, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as x:
        raise Fout("kon gh niet starten om het secret op te slaan (%s)" % x)
    if p.returncode != 0:
        raise Fout("secret EWELINK_TOKENS opslaan mislukte: %s" % (p.stderr.strip() or p.stdout.strip()))

def load_tokens():
    try:
        tok = json.loads(env("EWELINK_TOKENS"))
        tok["at"], tok["rt"]
    except (ValueError, KeyError, TypeError):
        raise Fout("EWELINK_TOKENS is leeg of onleesbaar. Draai op je computer: python ewelink.py --login")
    mask(tok["at"], tok["rt"])
    if tok.get("rtExp", 0) and tok["rtExp"] < now_ms():
        raise Fout("de refresh token is verlopen. Draai op je computer: python ewelink.py --login")
    if tok.get("atExp", 0) - now_ms() < REFRESH_BEFORE or os.environ.get("EWELINK_FORCE_REFRESH") == "true":
        d = call(tok.get("region") or env("EWELINK_REGION", "eu"), "POST", "/v2/user/refresh", body={"rt": tok["rt"]})
        tok.update(at=d["at"], rt=d["rt"], atExp=now_ms() + 30 * DAY, rtExp=now_ms() + 60 * DAY)
        mask(tok["at"], tok["rt"])
        print("Token ververst.")
        try:
            save_tokens(tok)
            print("Nieuwe tokens opgeslagen in secret EWELINK_TOKENS.")
        except Fout as x:
            # De nieuwe tokens werken nu wel, maar gaan na deze run verloren.
            print("LET OP: %s. Draai op je computer: python ewelink.py --login" % x, file=sys.stderr)
            tok["opslagFout"] = True
    return tok

def login():
    """OAuth2.0: inlogpagina van eWeLink, code opvangen via het redirect URL, binnen 30 seconden omwisselen."""
    state, seq = secrets.token_hex(8), str(now_ms())
    q = {"clientId": env("EWELINK_APPID"), "seq": seq, "authorization": sign(env("EWELINK_APPID") + "_" + seq),
         "redirectUrl": REDIRECT, "grantType": "authorization_code", "state": state,
         "nonce": secrets.token_hex(4), "showQRCode": "false"}
    url = "https://c2ccdn.coolkit.cc/oauth/index.html?" + urllib.parse.urlencode(q)
    print("Open deze pagina en log in met je eWeLink-account (als hij niet vanzelf opent):\n\n" + url + "\n")
    red = urllib.parse.urlparse(REDIRECT)
    if red.hostname in ("127.0.0.1", "localhost"):
        got = {}
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                p = urllib.parse.urlparse(self.path)
                if p.path != red.path:
                    self.send_response(404); self.end_headers(); return
                got.update(urllib.parse.parse_qs(p.query))
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers()
                self.wfile.write("Ingelogd. Je kunt dit venster sluiten en teruggaan naar de terminal.".encode())
            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer((red.hostname, red.port or 80), H)
        webbrowser.open(url)
        print("Wachten op de inlog (Ctrl+C om te stoppen)...")
        while "code" not in got:
            srv.handle_request()
        srv.server_close()
    else:
        webbrowser.open(url)
        back = input("Plak hier meteen het adres waar je browser na het inloggen op uitkomt (de code is 30 seconden geldig):\n> ")
        got = urllib.parse.parse_qs(urllib.parse.urlparse(back.strip()).query)
    if got.get("state", [""])[0] != state:
        raise Fout("het antwoord hoort niet bij deze inlogpoging (state klopt niet)")
    region = got.get("region", [env("EWELINK_REGION", "eu")])[0]
    d = call(region, "POST", "/v2/user/oauth/token",
             body={"code": got["code"][0], "redirectUrl": REDIRECT, "grantType": "authorization_code"})
    tok = {"at": d["accessToken"], "rt": d["refreshToken"], "atExp": d.get("atExpiredTime", now_ms() + 30 * DAY),
           "rtExp": d.get("rtExpiredTime", now_ms() + 60 * DAY), "region": region}
    print("Ingelogd, regio %s." % region)
    save_tokens(tok)
    print("Tokens opgeslagen als GitHub-secret EWELINK_TOKENS (niet in een bestand).")
    return tok

def things(tok):
    out, begin = [], -9999999
    while True:
        d = call(tok.get("region") or env("EWELINK_REGION", "eu"), "GET", "/v2/device/thing",
                 params={"num": 30, "beginIndex": begin}, at=tok["at"])
        lst = d.get("thingList") or []
        out += [x["itemData"] for x in lst if x.get("itemType") in (1, 2)]
        if not lst or len(lst) < 30:
            return out
        begin = lst[-1]["index"]

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def reading(dev):
    """Geeft (t, h, at, uitleg). Zigbee-sensor (UIID 1770): temperature en humidity als tekst x100, trigTime in ms.
    Waarden boven 100 delen we door 100; binnen is dat altijd het geval bij het x100-formaat."""
    p = dev.get("params") or {}
    t = num(p.get("temperature", p.get("currentTemperature")))
    h = num(p.get("humidity", p.get("currentHumidity")))
    if t is not None and abs(t) > 100:
        t /= 100
    if h is not None and h > 100:
        h /= 100
    at = num(p.get("trigTime"))
    if at and not (1.5e12 < at < now_ms() + 300000):
        at = None
    if t is None or not -40 < t < 80:
        return None, None, None, "geen bruikbare temperatuur"
    if h is None or not 0 <= h <= 100:
        return None, None, None, "geen bruikbare luchtvochtigheid"
    if not at:
        if not dev.get("online"):
            return None, None, None, "offline en zonder meettijd"
        at = now_ms()
    return round(t, 1), (round(h) if h is not None else None), int(at), ""

def show(devs):
    print("%d apparaten gevonden:\n" % len(devs))
    for d in devs:
        t, h, at, why = reading(d)
        meting = ("%.1f °C, %d%%, gemeten %s" % (t, h, time.strftime("%d-%m %H:%M", time.localtime(at / 1000)))) if t is not None else why
        print("- %s\n  ID: %s   model: %s   UIID: %s   %s\n  velden: %s\n  meting: %s\n" % (
            d.get("name"), d.get("deviceid"), d.get("productModel", "?"), (d.get("extra") or {}).get("uiid", "?"),
            "online" if d.get("online") else "offline", ", ".join(sorted((d.get("params") or {}).keys())) or "(geen)", meting))

def find(devs, key):
    want = env(key)
    hits = [d for d in devs if d.get("deviceid") == want] or [d for d in devs if (d.get("name") or "").strip().lower() == want.lower()]
    if len(hits) != 1:
        raise Fout("%s=%s: %s. Gebruik --list om de juiste ID te vinden" % (key, want, "niet gevonden" if not hits else "meerdere apparaten met die naam"))
    return hits[0]

def write(devs):
    res = {}
    for loc, key in (("beneden", "EWELINK_DEVICE_BENEDEN"), ("boven", "EWELINK_DEVICE_BOVEN")):
        d = find(devs, key)
        t, h, at, why = reading(d)
        if t is None:
            raise Fout("sensor %s (%s): %s" % (loc, d.get("name"), why))
        res[loc] = {"t": t, "h": h, "at": at}
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f, separators=(",", ":"))
    os.replace(tmp, OUT)
    print("indoor.json geschreven: beneden %.1f °C, boven %.1f °C." % (res["beneden"]["t"], res["boven"]["t"]))

def main():
    args = sys.argv[1:]
    if not args and not os.environ.get("EWELINK_TOKENS"):
        print("eWeLink is niet ingesteld (secret EWELINK_TOKENS ontbreekt), sensors overgeslagen.")
        return 0
    try:
        tok = login() if "--login" in args else load_tokens()
        devs = things(tok)
        if "--login" in args or "--list" in args:
            show(devs)
            if not (os.environ.get("EWELINK_DEVICE_BENEDEN") and os.environ.get("EWELINK_DEVICE_BOVEN")):
                return 0
        write(devs)
        return 1 if tok.get("opslagFout") else 0
    except Fout as x:
        print("FOUT: %s. indoor.json is niet aangepast." % x, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nGestopt.", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
