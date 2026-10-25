# Energiekompas (online versie)

Een webpagina die je zonder eigen computer online zet. De volledige handleiding staat in de app zelf, onder het tabblad **Handleiding**. Hieronder staat alleen het online zetten.

## Bestanden

| Bestand | Doel |
|---|---|
| `index.html` | de app |
| `data.json` | startgegevens (weer en prijzen); wordt elk uur bijgewerkt |
| `settings.json` | optioneel: standaardwaarden voor alle apparaten. Zet hier geen persoonlijke gegevens in als de pagina openbaar staat |
| `update.py` | haalt weer (KNMI HARMONIE via Open-Meteo) en EPEX-prijzen op; ook handmatig te draaien |
| `.github/workflows/update.yml` | taak voor GitHub: draait `update.py` elk uur |
| `manifest.webmanifest`, `icon-*.png`, `favicon.png` | pictogram en naam voor op je beginscherm |
| `.nojekyll` | zorgt dat GitHub Pages de bestanden ongewijzigd deelt |

## Binnen invullen en ventileren

Bij het openen vraagt de app naar de temperatuur en luchtvochtigheid van de sensoren beneden en boven (niet als je ze het afgelopen uur al invulde). Onder **Instellingen**, bovenaan bij **Metingen binnen**, zie je welke waarden er zijn en wanneer ze zijn ingevuld, en kun je ze aanpassen of wissen. Op het overzicht staat het blok **Ventileren** met advies op basis van de luchtvochtigheid. Zie de **Handleiding** in de app.

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
