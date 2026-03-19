# Bridge IDE — Tor Hardening Plan: Level 9+Ultra
# Autor: Viktor (Systemarchitekt) | Stand: 2026-03-19
# Ziel: Maximum was technisch möglich ist gegen moderne Forensik

---

## THREAT MODEL

**Adversary**: Resourced actor mit ISP-Kooperation, eigenen Tor-Relays, ML-basierter Traffic-Analyse (RECTor-Level), Browser-Fingerprinting und Behavioral Biometrics.

**Ziel**: Maximale Kosten für Deanonymisierung. Nicht "unmöglich" versprechen — aber den teuersten Stack bauen der existiert.

---

## ARCHITEKTUR: 3-TIER ANONYMITY STACK

```
┌────────────────────────────────────────────────────────┐
│  TIER 3: BEHAVIORAL LAYER                               │
│  Kloak (Keystroke), Bezier-Maus (humanize),             │
│  Random Delays, Session-Isolation                       │
├────────────────────────────────────────────────────────┤
│  TIER 2: BROWSER LAYER                                  │
│  Camoufox + resistFingerprinting + Tor-UA              │
│  Canvas/WebGL/Audio OFF, WebRTC OFF, Letterboxing      │
├────────────────────────────────────────────────────────┤
│  TIER 1: NETWORK LAYER                                  │
│  Tor Daemon + Vanguards + Traffic Padding              │
│  stem Circuit Control + DNS-over-Tor                   │
│  Optional: Whonix VM für Air-Gap                       │
└────────────────────────────────────────────────────────┘
```

---

## 1. TLS FINGERPRINT MATCHING (JA3/JA4)

### Problem
Playwright/Camoufox haben einen TLS-Handshake der nicht zum behaupteten User-Agent passt. JA4 erkennt Automation passiv — kein JavaScript nötig.

### Lösung A: Camoufox (EMPFOHLEN)
Camoufox ist ein Firefox-Fork mit C++ Patches. Der TLS-Handshake ist IDENTISCH mit echtem Firefox, weil es echtes Firefox IST. JA3/JA4 Fingerprint = Firefox 135.

**Aktion:** Camoufox mit Tor Browser UA String:
```python
with Camoufox(
    config={"general.useragent.override": "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"},
    block_webrtc=True,
    block_webgl=True,
) as browser:
    ...
```

### Lösung B: curl_cffi für Non-Browser-Requests
Für API-Calls/HTTP-Requests ohne Browser:
```python
from curl_cffi import requests
session = requests.Session(impersonate="firefox128")
session.proxies = {"https": "socks5h://127.0.0.1:9050"}
resp = session.get("https://target.com")
```
JA3/JA4 = echtes Firefox. Kein Playwright nötig.

### Status: MACHBAR — Camoufox liefert echten Firefox TLS-Stack.

---

## 2. WHONIX VS SOCKS-PROXY STRATEGIE

### Option A: SOCKS-Proxy (Schnell, leichtgewichtig)
```
Agent → Camoufox → socks5://127.0.0.1:9050 → Tor → Internet
```
- Pro: Einfach, kein VM-Overhead, sofort nutzbar
- Contra: DNS-Leaks möglich bei falschem Proxy-Typ, System-Level Leaks wenn App den Proxy umgeht

### Option B: Whonix-Gateway (Maximum Isolation)
```
Agent → Whonix Workstation VM → Whonix Gateway VM → Tor → Internet
```
- Pro: ALLES geht durch Tor, keine Leaks möglich, VM-Isolation
- Contra: VM-Overhead (~2GB RAM), komplexeres Setup, Latenz

### Option C: Hybrid (EMPFOHLEN)
- **Standard-Tasks**: SOCKS-Proxy (Option A) — schnell, ausreichend für IP-Masking
- **Hochsensitive Tasks**: Whonix-VM (Option B) — für Operations wo maximale Anonymität nötig ist
- **Entscheidung per Task-Flag**: `anonymity_level="standard"` vs `anonymity_level="maximum"`

### Implementierung Whonix:
```bash
# Whonix Gateway + Workstation als KVM VMs
sudo apt install qemu-kvm libvirt-daemon
# Download Whonix Gateway + Workstation Images
# Gateway: Internal Network → Tor → Internet
# Workstation: Internal Network only → Gateway
```

### Status: MACHBAR — SOCKS sofort, Whonix braucht KVM-Setup.

---

## 3. KLOAK INTEGRATION (Keystroke-Anonymisierung)

### Problem
Tastatur-Dynamik: 92-94% Identifizierung. Angreifer kann Tor- und Clearnet-Typing-Muster korrelieren.

### Lösung: Kloak
Kloak ist ein Linux-Kernel-Level Keystroke-Anonymizer. Fängt Keyboard-Events ab und injiziert randomisierten Timing-Jitter.

```bash
# Installation
git clone https://github.com/vmonaco/kloak
cd kloak && make
sudo ./kloak  # Läuft als Root, interceptt /dev/input/event*
```

**Effektivität:** Reduziert Identifizierung von 94% auf 15-19%.

### Bridge-Integration
Neues MCP-Tool:
```python
bridge_kloak_start()  # Startet Kloak daemon
bridge_kloak_stop()   # Stoppt Kloak
bridge_kloak_status()  # Prüft ob aktiv
```

### Risiko
Kloak-Usage selbst ist detektierbar ("unnatürlich gleichmäßig"). Aber: Ohne Kloak = 94% Identifizierung. Mit = 15-19%. Der Trade-Off ist klar.

### Status: MACHBAR — braucht sudo für /dev/input Zugriff. Leo muss einmalig installieren.

---

## 4. TRAFFIC PADDING / KONSTANTE DATENRATE

### Problem
Traffic-Analyse korreliert Timing + Volume zwischen Entry und Exit. Bursts sind einzigartig.

### Lösung A: Tor-Level Padding (begrenzt)
Tor hat seit 2019 Circuit-Level Padding. Schützt gegen Website-Fingerprinting, NICHT gegen Timing-Korrelation.

### Lösung B: Application-Level Padding (EMPFOHLEN)
Bridge generiert konstanten Hintergrund-Traffic durch den Tor-Circuit:
```python
async def _tor_traffic_padding(interval_ms=500, jitter_ms=200):
    """Sendet dummy HTTPS-Requests um Traffic-Pattern zu verschleiern."""
    while padding_active:
        delay = (interval_ms + random.randint(-jitter_ms, jitter_ms)) / 1000
        await asyncio.sleep(delay)
        # Dummy request an harmlose Seite (Wikipedia, etc.)
        async with httpx.AsyncClient(proxies={"all://": "socks5h://127.0.0.1:9050"}) as c:
            await c.get("https://en.wikipedia.org/wiki/Special:Random", timeout=10)
```

### Lösung C: Obfs4 Bridge (gegen ISP-Level Detection)
Wenn der ISP Tor-Traffic erkennt:
```
torrc:
Bridge obfs4 IP:PORT FINGERPRINT cert=... iat-mode=0
ClientTransportPlugin obfs4 exec /usr/bin/obfs4proxy
```
Obfs4 verschleiert Tor-Traffic als normalen HTTPS.

### Status: MACHBAR — Application-Level Padding sofort, Obfs4 braucht Bridge-Relays.

---

## 5. RESISTFINGERPRINTING (Canvas, WebGL, AudioContext)

### Camoufox Config für Maximum Anti-Fingerprinting:
```python
with Camoufox(
    config={
        "privacy.resistFingerprinting": True,          # Master-Switch
        "privacy.resistFingerprinting.letterboxing": True,  # Window-Size normalisierung
        "webgl.disabled": True,                        # WebGL komplett aus
        "media.peerconnection.enabled": False,         # WebRTC aus
        "dom.webaudio.enabled": False,                 # AudioContext aus
        "canvas.capturestream.enabled": False,          # Canvas Stream aus
        "privacy.trackingprotection.enabled": True,
        "privacy.firstparty.isolate": True,            # Cross-Site Isolation
        "geo.enabled": False,                          # Geolocation aus
        "dom.battery.enabled": False,                  # Battery API aus
        "media.navigator.enabled": False,              # MediaDevices aus
        "dom.gamepad.enabled": False,                  # Gamepad API aus
        "dom.vr.enabled": False,                       # VR API aus
    },
    block_webrtc=True,
    block_webgl=True,
    screen={"width": 1280, "height": 720},   # Standardisierte Auflösung
    fonts=[],  # Nur System-Default-Fonts
) as browser:
    ...
```

### Status: MACHBAR — Camoufox Config, kein neuer Code nötig.

---

## 6. GUARD DISCOVERY SCHUTZ (Vanguards)

### Was sind Vanguards?
Vanguards pinnen die 2. und 3. Hop-Relays für Onion-Service-Circuits. Ohne Vanguards: Guard-Discovery in Minuten. Mit: Monate.

### Aktivierung:
```
# torrc
VanguardsEnabled 1  # Seit Tor 0.4.8+ / Arti 1.2.2
```

### Status: MACHBAR — eine Zeile in torrc. Braucht Tor >= 0.4.8.

---

## 7. CIRCUIT ROTATION STRATEGIE

### Automatische Rotation pro Task:
```python
import stem
from stem import Signal
from stem.control import Controller

async def bridge_tor_new_circuit():
    """Neuer Circuit = neue Exit-IP. Min 10s zwischen Rotationen."""
    with Controller.from_port(port=9051) as ctrl:
        ctrl.authenticate()
        ctrl.signal(Signal.NEWNYM)
        wait = ctrl.get_newnym_wait()
        if wait > 0:
            await asyncio.sleep(wait)
```

### Strategie:
- **Pro Task**: Neuer Circuit → neue IP → keine Korrelation zwischen Tasks
- **Pro Session**: Gleicher Circuit für zusammengehörige Requests (Login-Flow)
- **Parallel**: Mehrere SocksPort in torrc → isolierte Circuits pro Agent
```
# torrc
SocksPort 9050  # Agent 1
SocksPort 9052  # Agent 2
SocksPort 9054  # Agent 3
```

### Status: MACHBAR — stem + torrc Config.

---

## 8. DNS-LEAK-PREVENTION (Verifiziert)

### Schicht 1: SOCKS5h (Remote DNS)
```python
proxy = "socks5h://127.0.0.1:9050"  # Das 'h' = DNS über Proxy
```
SOCKS5 (ohne h) = DNS lokal = LEAK. SOCKS5h = DNS über Tor.

### Schicht 2: System-Level DNS Block
```bash
# iptables: Blockiere alle DNS-Anfragen die nicht durch Tor gehen
sudo iptables -A OUTPUT -p udp --dport 53 -j DROP
sudo iptables -A OUTPUT -p tcp --dport 53 -j DROP
# Erlaube nur Tor's eigenen DNS
sudo iptables -A OUTPUT -m owner --uid-owner debian-tor -j ACCEPT
```

### Schicht 3: Verifikation
```python
async def verify_no_dns_leak():
    """Prüft ob DNS durch Tor geht."""
    # Rufe DNS-Leak-Test auf
    resp = await httpx.AsyncClient(proxies={"all://": "socks5h://127.0.0.1:9050"}).get(
        "https://check.torproject.org/api/ip"
    )
    data = resp.json()
    assert data["IsTor"] == True, "NOT using Tor!"
    return data["IP"]
```

### Status: MACHBAR — socks5h + iptables + Verifikation.

---

## 9. BEHAVIORAL BIOMETRICS ABWEHR (Maus + Tastatur)

### Tastatur
- **Kloak** (Tier 1): Kernel-Level Jitter, 94% → 15-19%
- **Bridge bridge_desktop_type**: Bereits Gaussian-Delays (12ms Base)
- **Enhancement**: Variable WPM pro Session (40-80 WPM Random), Tippfehler-Injection

### Maus
- **Camoufox humanize=True**: Bezier-Kurven + Fitts's Law
- **Enhancement**: Session-spezifische Maus-Persönlichkeit (Speed-Profile randomisiert)
- **Scroll-Patterns**: Variable Scroll-Geschwindigkeit + Pausen

### Session-Isolation
- Jede Tor-Session = neues Verhaltensprofil (Typing-Speed, Maus-Speed, Scroll-Habit)
- NIEMALS gleiches Profil für Tor und Clearnet

### Status: TEILWEISE MACHBAR — Kloak braucht sudo, Rest ist Code-Änderung in bridge_mcp.py.

---

## 10. REALISTISCH VS THEORETISCH

| Feature | Realistisch (jetzt) | Aufwand | Impact |
|---------|---------------------|---------|--------|
| Tor Daemon + SOCKS5h | JA | 5min (apt install) | HOCH |
| Camoufox + resistFingerprinting | JA | 30min (Config) | HOCH |
| stem Circuit-Rotation | JA | 1h (pip + Code) | MITTEL |
| Vanguards | JA | 1 Zeile torrc | MITTEL |
| DNS-Leak-Verification | JA | 30min | HOCH |
| Tor Browser UA | JA | 5min (Config) | MITTEL |
| Traffic Padding (App-Level) | JA | 2h (Code) | MITTEL |
| Kloak Keystroke | BRAUCHT SUDO | 1h | HOCH |
| iptables DNS-Block | BRAUCHT SUDO | 15min | HOCH |
| Whonix VM | BRAUCHT KVM + 2GB RAM | 4h Setup | SEHR HOCH |
| Obfs4 Bridges | BRAUCHT Bridge-Relays | 2h | MITTEL (gegen ISP) |
| Per-Session Behavioral Profile | JA | 3h (Code) | MITTEL |

### PHASE 1 (Sofort, ohne sudo): Level 7
- Tor Daemon (falls schon installiert) + SOCKS5h
- Camoufox + resistFingerprinting + WebGL/WebRTC/Audio OFF
- stem Circuit-Rotation
- Tor Browser UA
- DNS-Leak-Verification

### PHASE 2 (Mit sudo, Leo einmalig): Level 8
- Kloak Installation
- iptables DNS-Block
- Vanguards in torrc
- Obfs4 evaluieren

### PHASE 3 (Maximaler Aufwand): Level 9+Ultra
- Whonix VM als Option für hochsensitive Tasks
- Traffic Padding Daemon
- Per-Session Behavioral Randomisierung
- Bridges für Obfs4

---

## FAZIT

**Level 9+Ultra = das Maximum was auf einem Linux-Desktop ohne dedizierte Hardware möglich ist.** Darüber hinaus bräuchte man: dedizierte Hardware (Tails auf USB), Air-Gapped Netzwerke, oder physischen Zugang zu öffentlichen WiFi-Netzen.

Unsere Architektur adressiert alle 5 Attack-Vektoren:
1. ✅ Network (Tor + Vanguards + Obfs4 + Traffic Padding)
2. ✅ Browser (Camoufox + resistFingerprinting + Tor UA)
3. ✅ TLS (Echtes Firefox TLS via Camoufox)
4. ✅ DNS (SOCKS5h + iptables + Verification)
5. ✅ Behavioral (Kloak + Humanize + Session-Isolation)

**Kein System ist 100% sicher gegen Nation-State.** Aber dieser Stack macht Deanonymisierung so teuer, dass es nur bei hochpriorisierten Targets ökonomisch ist.
