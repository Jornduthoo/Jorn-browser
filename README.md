# Jorn Browser

Een snelle privacybrowser voor Windows met **Chrome-extensies** en een knop
**"Nieuwe identiteit"**, zoals in Tor Browser, maar veel sneller.

Jorn Browser is een venster rond **Chromium** (de open-source basis van Chrome).
Elke identiteit is een Chromium-venster met een **gloednieuw, tijdelijk profiel**.
Bij "Nieuwe identiteit" (of Ctrl+N) gebeurt dit binnen 1 à 2 seconden:

1. Alle vensters sluiten.
2. Cookies, cache, geschiedenis en logins worden gewist.
3. Er start een vers venster, met een **ander IP** als je de proxylijst gebruikt.

Ook inbegrepen:

- **Chrome-extensies**: plak een link uit de Chrome Web Store, klaar.
- **WebRTC-lekbescherming**: websites kunnen je echte IP niet zien buiten de VPN om.
- **Meerdere identiteiten tegelijk**, elk in een apart venster met een eigen IP.
- Alles wordt gewist bij het sluiten, en restjes na een crash bij de volgende start.

## Installatie (Windows)

1. **Chromium installeren**: open PowerShell en typ
   ```
   winget install eloston.ungoogled-chromium
   ```
   (gewone Google Chrome werkt niet: die laadt geen extensies via de app).
2. **JornBrowser.exe downloaden**: GitHub, tabblad *Actions*, laatste geslaagde
   build "Windows .exe bouwen", onderaan *Artifacts*, dan `JornBrowser-windows`.
   Zet het bestand in een eigen map, bv. `C:\JornBrowser\`.
3. Dubbelklik. Windows SmartScreen kan waarschuwen omdat de exe niet
   ondertekend is: kies *Meer info*, dan *Toch uitvoeren*.

Heb je Python? Dan kan je ook gewoon `jornbrowser.pyw` dubbelklikken.

## Van IP wisselen: twee manieren

### A. Met je VPN-app (bv. VPN Unlimited)
Tabblad *Netwerk*, kies "Geen proxy". Wissel in je VPN-app van server en klik
daarna op **Nieuwe identiteit**. Het werkt, maar het kost telkens enkele seconden
om de VPN opnieuw te verbinden.

### B. Proxylijst: automatisch een ander IP per identiteit (aanrader)
Tabblad *Netwerk*, kies "Proxylijst". Elke nieuwe identiteit pakt dan een
andere proxy uit `data\proxies.txt`.

**Beste combinatie: Mullvad VPN (€5/maand)**
1. Installeer Mullvad en verbind via WireGuard (bv. met een server in België of Nederland).
2. Klik in Jorn Browser op **Mullvad-lijst ophalen**.
3. Elke "Nieuwe identiteit" geeft nu meteen een ander uitgangs-IP, zonder dat
   je de VPN opnieuw verbindt. De SOCKS5-proxies van Mullvad werken alleen
   terwijl je met Mullvad verbonden bent, dus je verkeer blijft versleuteld.

Andere proxies kan je met de hand in `proxies.txt` zetten (`socks5://host:poort`).
Chromium ondersteunt geen proxies met gebruikersnaam/wachtwoord.

Klik op **Toon mijn IP** om te controleren welk IP een website ziet.

## Eerlijk over privacy

- **Sneller dan Tor** betekent dat je de VPN-aanbieder vertrouwt (1 tussenstap
  in plaats van 3). Kies er een die geen logs bijhoudt.
- **Extensies maken je herkenbaarder** (fingerprinting). Gebruik er zo weinig
  mogelijk. Een adblocker zoals uBlock Origin Lite is wel aan te raden.
- Je IP en cookies zijn telkens nieuw, maar je scherm, lettertypes en
  tijdzone blijven dezelfde. Tegen echt gerichte tracking is Tor Browser sterker.

## Mappen

| Wat | Waar |
|---|---|
| Instellingen, `proxies.txt`, extensies | `data\` naast JornBrowser.exe |
| Tijdelijke profielen (worden gewist) | `%TEMP%\JornBrowser\profiles` |
