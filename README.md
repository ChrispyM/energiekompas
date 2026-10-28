# Energiekompas (online versie)

Een webpagina die je zonder eigen computer online zet. De volledige handleiding staat in de app zelf, onder het tabblad **Handleiding**. Hieronder staat alleen het online zetten.

## Bestanden

| Bestand | Doel |
|---|---|
| `index.html` | de app |
| `data.json` | startgegevens (weer en prijzen); wordt elk uur bijgewerkt |
| `prices-history.json` | gasprijs en laagste/hoogste/gemiddelde stroomprijs per dag van het afgelopen jaar, voor de grafieken in de tegels; door `update.py` bijgehouden |
| `meldingen.py` | stuurt meldingen naar Telegram (ventileren, goedkope en dure stroom, prijsverandering van meer dan 10% ten opzichte van de week ervoor). Draait niet in de workflow maar elke 10 minuten op de server; zie bovenin het script |
| `settings.json` | optioneel: standaardwaarden voor alle apparaten. Zet hier geen persoonlijke gegevens in als de pagina openbaar staat |
| `ewelink.py` | haalt temperatuur en luchtvochtigheid van twee sensors uit eWeLink en schrijft `indoor.json` (zie hieronder) |
| `update.py` | haalt weer (KNMI HARMONIE via Open-Meteo) en EPEX-prijzen op; ook handmatig te draaien |
| `.github/workflows/update.yml` | taak voor GitHub: draait `update.py` elk uur |
| `manifest.webmanifest`, `icon-*.png`, `favicon.png` | pictogram en naam voor op je beginscherm |
| `.nojekyll` | zorgt dat GitHub Pages de bestanden ongewijzigd deelt |

## Binnen invullen en ventileren

Bij het openen vraagt de app naar de temperatuur en luchtvochtigheid van de sensoren beneden en boven (niet als je ze het afgelopen uur al invulde). Onder **Instellingen**, bovenaan bij **Metingen binnen**, zie je welke waarden er zijn en wanneer ze zijn ingevuld, en kun je ze aanpassen of wissen. Op het overzicht staat het blok **Ventileren** met advies op basis van de luchtvochtigheid. Zie de **Handleiding** in de app.

## Sensors uit eWeLink

`ewelink.py` haalt elk uur de temperatuur en luchtvochtigheid van twee Sonoff-sensors (bijvoorbeeld SNZB-02D via een Zigbee-gateway) uit de eWeLink-cloud. Het script schrijft die naar `indoor.json`. De app gebruikt een sensorwaarde tot 3 uur oud, of je handmatige invoer als die nieuwer is. Je hebt geen Home Assistant nodig en je computer hoeft niet aan te staan.

**Waarom niet inloggen met je wachtwoord?** Met een gratis APP ID van dev.ewelink.cc mag je volgens eWeLink alleen OAuth2.0 gebruiken. Daarom log je één keer in de browser in. Daarna gebruikt het script tokens:
- het access token is 30 dagen geldig;
- het refresh token is 60 dagen geldig.

Het script ververst de tokens zelf en zet de nieuwe tokens terug in GitHub. De gratis APP ID mag 50.000 aanroepen per maand doen. Dit script gebruikt er ongeveer 750.

### 1. App aanmaken bij eWeLink

Op dev.ewelink.cc: laat je account als ontwikkelaar verifiëren, maak een app aan en vul als **Redirect URL** dit in:

```
http://127.0.0.1:8000/redirectUrl
```

### 2. Secrets aanmaken in GitHub

Ga in de repository naar **Settings**, **Secrets and variables**, **Actions**, **New repository secret**. Maak deze secrets aan:

| Secret | Wat erin moet |
|---|---|
| `EWELINK_APPID` | de APP ID van je app op dev.ewelink.cc |
| `EWELINK_APPSECRET` | de APP SECRET van die app |
| `EWELINK_DEVICE_BENEDEN` | de apparaat-ID (of de exacte naam) van de sensor beneden, zie stap 3 |
| `EWELINK_DEVICE_BOVEN` | idem voor de sensor boven |
| `EWELINK_GH_TOKEN` | een GitHub-token waarmee de taak het secret `EWELINK_TOKENS` mag bijwerken, zie hieronder |
| `EWELINK_REGION` | alleen als je account niet in Europa staat: `us`, `as` of `cn`. Laat hem anders weg, dan geldt `eu` |

`EWELINK_TOKENS` maak je niet zelf aan. Dat doet `ewelink.py --login` in stap 3.

Zo maak je `EWELINK_GH_TOKEN`:
1. Ga op github.com naar je profielfoto, **Settings**, **Developer settings**, **Personal access tokens**, **Fine-grained tokens**, **Generate new token**.
2. Kies bij **Repository access**: **Only select repositories** en dan deze repository.
3. Zet bij **Permissions**, **Secrets** op **Read and write**. Andere rechten zijn niet nodig.
4. Kies een vervaldatum. Verloopt de token, dan moet je hem vervangen.

Je wachtwoord van eWeLink is niet nodig en hoort nergens in GitHub te staan.

### 3. Eén keer inloggen op je eigen computer

Hiervoor heb je `gh` nodig, ingelogd met `gh auth login`. Ga in een terminal naar deze map en typ:

```
read -rs -p "APP ID: " EWELINK_APPID; echo; export EWELINK_APPID
read -rs -p "APP SECRET: " EWELINK_APPSECRET; echo; export EWELINK_APPSECRET
python3 ewelink.py --login
```

Je browser opent de inlogpagina van eWeLink. Log daar in met je eWeLink-account. Daarna gebeurt dit vanzelf:
- het script vangt de code op;
- het zet de tokens als secret `EWELINK_TOKENS` in GitHub (niet in een bestand);
- het toont al je apparaten met naam, ID, velden en de laatste meting.

Kopieer de ID's van de twee sensors naar `EWELINK_DEVICE_BENEDEN` en `EWELINK_DEVICE_BOVEN`.

Wil je meteen een `indoor.json` maken? Zet de twee ID's dan ook in de terminal:

```
export EWELINK_DEVICE_BENEDEN=... EWELINK_DEVICE_BOVEN=...
```

Draai daarna `--login` nog een keer.

### 4. Controleren

Ga naar **Actions**, **Gegevens verversen**, **Run workflow**. In de stap **Sensors uit eWeLink ophalen** zie je wat er gebeurde. Gaat er iets mis, dan blijft `indoor.json` zoals hij was en gaan het weer en de prijzen gewoon door. Staat er "draai python ewelink.py --login", doe dan stap 3 opnieuw. Dat is nodig als:
- de tokens verlopen zijn;
- het opslaan van de tokens mislukte;
- je in een andere app met dezelfde APP ID bent ingelogd.

Let op: in een openbare repository kan iedereen `indoor.json` lezen, en dus de temperatuur en vochtigheid in je huis. Volgens eWeLink (Pricing.md in hun API-documentatie) is de gratis APP ID van een particuliere ontwikkelaar 1 jaar geldig. Dan moet je hem daarna op dev.ewelink.cc opnieuw aanmaken.

## Route A: GitHub Pages (aanbevolen)

1. Maak een gratis account op github.com. Kies + (rechtsboven), **New repository**, naam `energiekompas`, **Public**, **Create repository**.
2. Kies **uploading an existing file** en sleep alle bestanden uit de zip erin, behalve `update.yml`. Kies **Commit changes**. Wordt `.nojekyll` niet getoond, voeg het dan later toe via **Add file**, **Create new file**.
3. **Add file**, **Create new file**. Typ als naam `.github/workflows/update.yml` en plak de inhoud van `update.yml`. **Commit changes**.
4. **Settings**, **Actions**, **General**, **Workflow permissions**: kies **Read and write permissions**, **Save**.
5. **Settings**, **Pages**: Source **Deploy from a branch**, branch `main`, map `/ (root)`, **Save**. Na een paar minuten staat bovenaan je adres, zoals `https://jouwnaam.github.io/energiekompas/`.
6. Tabblad **Actions**, **Gegevens verversen**, **Run workflow**. Daarna draait het elk uur.

Let op: de repository is openbaar. De weer- en prijsgegevens zijn niet gevoelig, maar zet geen adres of naam in `settings.json`. Je instellingen in de app bewaart de pagina alleen op je eigen apparaat.

GitHub kan geplande taken uitzetten na 60 dagen zonder activiteit. Je krijgt dan een e-mail. Kies in **Actions** de taak en **Enable workflow**. De pagina haalt ondertussen zelf weer en prijzen op, voor zover de browser dat toestaat.

## Route B: Netlify of Cloudflare Pages (het snelst)

Pak de zip uit en sleep de map naar `app.netlify.com/drop`, of gebruik bij Cloudflare Pages "Direct upload". Je krijgt meteen een adres. Maak een gratis account zodat de site blijft staan. Er is hier geen geplande update: de pagina haalt zelf weer en prijzen op wanneer hij opent. Lukt dat in jouw browser niet, dan staan er verouderde gegevens of schattingen.

## Als app op je telefoon

Open het adres op je telefoon. iPhone (Safari): deelicoon, **Zet op beginscherm**. Android (Chrome): menu, **App installeren** of **Toevoegen aan startscherm**.

## Wat is getest en wat niet

Getest: de pagina in een browser, het live verwerken van weer en prijzen met nagebootste antwoorden, de handleiding en de berekeningen. Niet getest: het echte ophalen bij Open-Meteo en Energy-Charts (mijn omgeving heeft geen toegang), of Energy-Charts de pagina toestaat om rechtstreeks te lezen, en de GitHub-taak zelf. Staat er na route A na een uur nog dezelfde tijd bij "Weer van", kijk dan in **Actions** naar de foutmelding.
