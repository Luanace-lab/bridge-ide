"""Creator Setup — Dependency checking, credential validation, OAuth guides.

Provides setup status for the Creator Platform. Used by Buddy and
the /creator/setup/* endpoints to help users configure their system.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any


CREDENTIALS_DIR = os.path.join(
    os.environ.get("HOME", "/tmp"),
    ".config", "bridge", "social_credentials",
)


# ---------------------------------------------------------------------------
# Dependency Check
# ---------------------------------------------------------------------------


def check_dependencies() -> dict[str, Any]:
    """Check all Creator Platform dependencies."""
    deps: dict[str, Any] = {}

    # Binary dependencies
    for name, env_var, fallback in [
        ("ffmpeg", "FFMPEG_BIN", "ffmpeg"),
        ("ffprobe", "FFPROBE_BIN", "ffprobe"),
        ("yt-dlp", "YT_DLP_BIN", "yt-dlp"),
        ("flite", None, "flite"),
    ]:
        path = os.environ.get(env_var, "") if env_var else ""
        if not path:
            path = shutil.which(fallback) or ""
        version = ""
        if path:
            try:
                flag = "--version" if name != "flite" else "-v"
                r = subprocess.run([path, flag], capture_output=True, text=True, timeout=5)
                version = r.stdout.strip().split("\n")[0][:80] if r.stdout else r.stderr.strip().split("\n")[0][:80]
            except Exception:
                version = "installed"
        deps[name] = {
            "installed": bool(path),
            "path": path,
            "version": version,
            "required": name in ("ffmpeg", "ffprobe", "yt-dlp"),
        }

    # Python library dependencies
    for lib_name, import_name, required in [
        ("faster-whisper", "faster_whisper", True),
        ("httpx", "httpx", True),
        ("google-api-python-client", "googleapiclient", False),
        ("google-auth-oauthlib", "google_auth_oauthlib", False),
        ("tweepy", "tweepy", False),
        ("python-tiktok", "tiktok", False),
        ("fish-audio-sdk", "fish_audio_sdk", False),
        ("google-genai", "google.genai", False),
        ("chromadb", "chromadb", False),
    ]:
        installed = False
        version = ""
        try:
            mod = __import__(import_name)
            installed = True
            version = getattr(mod, "__version__", "installed")
        except ImportError:
            pass
        deps[lib_name] = {
            "installed": installed,
            "version": version,
            "required": required,
            "install_cmd": f"pip install {lib_name}",
        }

    return deps


# ---------------------------------------------------------------------------
# Credential Check
# ---------------------------------------------------------------------------

PLATFORMS = ["youtube", "tiktok", "instagram", "facebook", "twitter", "linkedin", "fish_audio"]

REQUIRED_FIELDS = {
    "youtube": ["client_id", "client_secret"],
    "tiktok": ["access_token"],
    "instagram": ["access_token", "ig_user_id"],
    "facebook": ["page_access_token", "page_id"],
    "twitter": ["api_key", "api_secret", "access_token", "access_token_secret"],
    "linkedin": ["access_token", "person_urn"],
    "fish_audio": ["api_key"],
}


def check_credentials() -> dict[str, Any]:
    """Check credential status for all social platforms."""
    results: dict[str, Any] = {}

    for platform in PLATFORMS:
        cred_path = os.path.join(CREDENTIALS_DIR, f"{platform}.json")
        if not os.path.isfile(cred_path):
            results[platform] = {
                "configured": False,
                "path": cred_path,
                "missing_fields": REQUIRED_FIELDS.get(platform, []),
            }
            continue

        try:
            with open(cred_path) as f:
                creds = json.load(f)
        except (json.JSONDecodeError, OSError):
            results[platform] = {
                "configured": False,
                "path": cred_path,
                "error": "Invalid JSON in credentials file",
            }
            continue

        required = REQUIRED_FIELDS.get(platform, [])
        missing = [f for f in required if not creds.get(f)]
        expires_at = creds.get("expires_at", "")
        token_warning = ""

        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_left = (exp_dt - now).days
                if days_left < 0:
                    token_warning = "EXPIRED"
                elif days_left < 7:
                    token_warning = f"Expires in {days_left} days"
            except (ValueError, TypeError):
                pass

        results[platform] = {
            "configured": len(missing) == 0,
            "path": cred_path,
            "missing_fields": missing,
            "token_warning": token_warning,
        }

    return results


# ---------------------------------------------------------------------------
# Combined Status
# ---------------------------------------------------------------------------


def check_all() -> dict[str, Any]:
    """Full setup status check."""
    deps = check_dependencies()
    creds = check_credentials()

    all_required_deps = all(
        d["installed"] for d in deps.values() if d.get("required")
    )
    any_social_configured = any(
        c["configured"] for c in creds.values()
    )
    fish_ready = bool(creds.get("fish_audio", {}).get("configured")) and bool(
        deps.get("fish-audio-sdk", {}).get("installed")
    )
    search_ready = bool(
        deps.get("google-genai", {}).get("installed")
        and deps.get("chromadb", {}).get("installed")
        and _has_google_api_key()
    )
    vision_ready = _has_anthropic_api_key()
    feature_readiness = {
        "core_creator": all_required_deps,
        "social_publishing": any_social_configured,
        "voiceover": fish_ready,
        "semantic_search": search_ready,
        "vision_analysis": vision_ready,
    }
    available_features = [
        name for name, enabled in feature_readiness.items() if enabled
    ]
    limitations: list[str] = []
    if all_required_deps and not any_social_configured:
        limitations.append(
            "Social publishing is not configured yet; publishing to external social platforms will fail closed."
        )
    if all_required_deps and not fish_ready:
        limitations.append(
            "Voiceover and voice cloning are unavailable until Fish Audio credentials are configured."
        )
    if all_required_deps and not search_ready:
        limitations.append(
            "Semantic creator search is unavailable until Google API key and search dependencies are configured."
        )
    if all_required_deps and not vision_ready:
        limitations.append(
            "Vision analysis is unavailable until an ANTHROPIC_API_KEY is configured."
        )
    token_warnings = {
        p: c["token_warning"]
        for p, c in creds.items()
        if c.get("token_warning")
    }
    if not all_required_deps:
        operation_mode = "blocked"
    elif len(available_features) == len(feature_readiness):
        operation_mode = "full"
    elif len(available_features) > 1:
        operation_mode = "extended"
    else:
        operation_mode = "core_only"

    return {
        "ready": all_required_deps,
        "core_ready": all_required_deps,
        "fully_configured": all(feature_readiness.values()),
        "operation_mode": operation_mode,
        "dependencies": deps,
        "social_credentials": creds,
        "all_required_deps_ok": all_required_deps,
        "any_social_configured": any_social_configured,
        "publishing_ready": any_social_configured,
        "voice_ready": fish_ready,
        "search_ready": search_ready,
        "vision_ready": vision_ready,
        "feature_readiness": feature_readiness,
        "available_features": available_features,
        "limitations": limitations,
        "token_warnings": token_warnings,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _has_google_api_key() -> bool:
    if os.environ.get("GOOGLE_API_KEY", "").strip():
        return True
    for path in [
        os.path.join(os.environ.get("HOME", "/tmp"), ".config", "bridge", "google_api_key"),
        os.path.join(
            os.environ.get("HOME", "/tmp"),
            ".config",
            "bridge",
            "social_credentials",
            "google.json",
        ),
    ]:
        if os.path.isfile(path):
            return True
    return False


def _has_anthropic_api_key() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return True
    path = os.path.join(
        os.environ.get("HOME", "/tmp"), ".config", "bridge", "anthropic_api_key"
    )
    return os.path.isfile(path)


# ---------------------------------------------------------------------------
# OAuth Setup Guides
# ---------------------------------------------------------------------------


_OAUTH_GUIDES = {
    "youtube": """# YouTube — Setup-Anleitung

1. Oeffne https://console.cloud.google.com/
2. Erstelle ein neues Projekt (oder waehle ein bestehendes)
3. Aktiviere die "YouTube Data API v3" unter APIs & Services
4. Gehe zu "Credentials" → "Create Credentials" → "OAuth Client ID"
5. Waehle "Desktop App" als Anwendungstyp
6. Lade die `client_secrets.json` herunter
7. Kopiere die Werte in:

```json
~/.config/bridge/social_credentials/youtube.json
{
  "client_id": "DEIN_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "DEIN_CLIENT_SECRET",
  "refresh_token": "",
  "access_token": ""
}
```

8. Beim ersten Aufruf oeffnet sich ein Browser fuer die OAuth-Zustimmung
9. Nach Zustimmung wird der refresh_token automatisch gespeichert

**Hinweis:** Im Testing-Mode (< 100 User) ist keine Google-Verifikation noetig.
**Kosten:** Kostenlos. 6 Videos/Tag mit Default-Quota.
""",

    "tiktok": """# TikTok — Setup-Anleitung

1. Oeffne https://developers.tiktok.com/
2. Erstelle eine Developer App
3. Beantrage Zugriff auf die "Content Posting API" (5-10 Werktage)
4. Konfiguriere OAuth 2.0: Redirect URI auf localhost
5. Fuehre den OAuth PKCE Flow durch:
   - Oeffne die Authorization URL im Browser
   - Erlaube den Zugriff
   - Kopiere den Authorization Code
6. Tausche den Code gegen einen Access Token ein
7. Speichere in:

```json
~/.config/bridge/social_credentials/tiktok.json
{
  "access_token": "DEIN_ACCESS_TOKEN",
  "refresh_token": "DEIN_REFRESH_TOKEN",
  "expires_at": "2027-03-15T00:00:00Z"
}
```

**Hinweis:** Unauditierte Apps posten nur mit privater Sichtbarkeit.
**Kosten:** Kostenlos.
""",

    "instagram": """# Instagram — Setup-Anleitung

1. Oeffne https://developers.facebook.com/
2. Erstelle eine neue App (Typ: Business)
3. Fuege das Produkt "Instagram Graph API" hinzu
4. Beantrage den Scope `instagram_content_publish` (App Review, 1-4 Wochen)
5. Verbinde dein Instagram Business/Creator-Konto mit einer Facebook Page
6. Generiere einen Page Access Token mit den Scopes:
   - `instagram_content_publish`
   - `instagram_basic`
   - `pages_show_list`
7. Ermittle deine Instagram User ID (IG User ID)
8. Speichere in:

```json
~/.config/bridge/social_credentials/instagram.json
{
  "access_token": "DEIN_PAGE_ACCESS_TOKEN",
  "ig_user_id": "DEINE_IG_USER_ID",
  "expires_at": "2027-03-15T00:00:00Z"
}
```

**Hinweis:** Instagram erfordert einen Business- oder Creator-Account.
**Hinweis:** Videos muessen ueber eine oeffentliche URL erreichbar sein (kein direkter Upload).
**Kosten:** Kostenlos.
""",

    "facebook": """# Facebook Pages — Setup-Anleitung

1. Oeffne https://developers.facebook.com/
2. Erstelle eine App (oder nutze die gleiche wie fuer Instagram)
3. Beantrage den Scope `publish_video` (App Review)
4. Generiere einen Page Access Token fuer deine Facebook Page
5. Ermittle die Page ID
6. Speichere in:

```json
~/.config/bridge/social_credentials/facebook.json
{
  "page_access_token": "DEIN_PAGE_ACCESS_TOKEN",
  "page_id": "DEINE_PAGE_ID"
}
```

**Kosten:** Kostenlos.
""",

    "twitter": """# X/Twitter — Setup-Anleitung

1. Oeffne https://developer.x.com/
2. Erstelle einen Developer Account
3. Erstelle eine App in einem Project
4. Aktiviere OAuth 2.0 mit PKCE
5. Generiere API Keys + Access Tokens
6. Speichere in:

```json
~/.config/bridge/social_credentials/twitter.json
{
  "api_key": "DEIN_API_KEY",
  "api_secret": "DEIN_API_SECRET",
  "access_token": "DEIN_ACCESS_TOKEN",
  "access_token_secret": "DEIN_ACCESS_TOKEN_SECRET",
  "bearer_token": "DEIN_BEARER_TOKEN"
}
```

**Hinweis:** Free Tier erlaubt nur 1 Tweet/Tag und max 2 Min Video.
**Kosten:** Free (stark limitiert) oder Basic $200/Mo.
""",

    "fish_audio": """# Fish Audio — Setup-Anleitung

1. Oeffne https://fish.audio/
2. Erstelle einen Account
3. Gehe zu https://fish.audio/app/api-keys/
4. Erstelle einen neuen API Key
5. Speichere in:

```json
~/.config/bridge/social_credentials/fish_audio.json
{
  "api_key": "DEIN_FISH_AUDIO_API_KEY"
}
```

6. Optional: Voice klonen unter https://fish.audio/voice-clone/
   - 1-3 Minuten sauberes Audio hochladen
   - Voice-ID wird automatisch zurueckgegeben

**Open Source:** Fish Speech S2 kann auch lokal betrieben werden (GPU erforderlich).
Repo: github.com/fishaudio/fish-speech (26K+ Stars, MIT-Lizenz)

**Kosten:** Free Tier ~7 Min/Monat. Plus $5.50/Mo (200 Min). Pro $37.50/Mo (27h).
""",

    "linkedin": """# LinkedIn — Setup-Anleitung

1. Oeffne https://developer.linkedin.com/
2. Erstelle eine App (erfordert registrierte Organisation)
3. Beantrage Zugriff auf "Community Management API"
4. Konfiguriere OAuth 2.0 mit Redirect URI
5. Fuehre den OAuth Flow durch
6. Ermittle deine Person URN (urn:li:person:{id})
7. Speichere in:

```json
~/.config/bridge/social_credentials/linkedin.json
{
  "access_token": "DEIN_ACCESS_TOKEN",
  "person_urn": "urn:li:person:DEINE_ID",
  "expires_at": "2027-03-15T00:00:00Z"
}
```

**Hinweis:** Nur fuer Organisationen (Unternehmen), nicht fuer Privatpersonen.
**Kosten:** Kostenlos.
""",
}


def get_oauth_guide(platform: str) -> str:
    """Get OAuth setup guide for a platform."""
    guide = _OAUTH_GUIDES.get(platform)
    if guide is None:
        return f"Keine Anleitung fuer Plattform: {platform}. Verfuegbar: {', '.join(sorted(_OAUTH_GUIDES.keys()))}"
    return guide
