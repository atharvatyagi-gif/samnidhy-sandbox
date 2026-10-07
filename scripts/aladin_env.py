"""
Keys and settings for the ALADIN scripts, in one place.

* load_env(): reads a local `.env` (gitignored) into the process environment, without overriding anything already set. Values are never
  printed or logged anywhere.
* startup_table(): a short table of which settings are present and what each script does without them. Every key is optional:
  every feature degrades gracefully when its key is missing.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# name -> (what it is for, what happens without it)
SETTINGS = {
    "GROQ_API_KEY": ("earnings-call transcript tone (cloud model)", "Gemini if its key exists, else a local FinBERT split at the Q&A marker"),
    "GEMINI_API_KEY": ("earnings-call transcript tone (cloud model)", "Groq if its key exists, else the local FinBERT split"),
    "GROQ_MODEL": ("overrides the default Groq model name", "the default in data/config/aladin_config.json"),
    "GEMINI_MODEL": ("overrides the default Gemini model name", "the default in data/config/aladin_config.json"),
    "REDDIT_CLIENT_ID": ("Reddit through its official API", "the subreddit RSS is tried instead (often rate-limited), else retail sentiment is not measured"),
    "REDDIT_CLIENT_SECRET": ("Reddit through its official API", "same as above"),
    "REDDIT_USER_AGENT": ("the User-Agent sent to Reddit", "a descriptive default"),
    "HF_TOKEN": ("avoids Hugging Face download rate limits for FinBERT", "anonymous download (slower, may be limited)"),
    "ALADIN_GIT_PUSH": ("set to 1 to let the loops commit and push their outputs", "nothing is ever pushed (the default)"),
    "ALADIN_WS_PORT": ("port of the local tick feed", "8787"),
    "ANGEL_API_KEY": ("Angel One live ticks (needs a demat account)", "the free NSE web feed (about 300 stocks, refreshed by NSE every 1-3 minutes)"),
    "ANGEL_CLIENT_CODE": ("Angel One live ticks", "same as above"),
    "ANGEL_MPIN": ("Angel One live ticks", "same as above"),
    "ANGEL_TOTP_SECRET": ("Angel One live ticks", "same as above"),
    "ALADIN_SOURCE": ("auto, angel or nse-web: which live source the local daemon uses", "auto: Angel One when its four settings exist, else the free NSE feed"),
    "LLM_PROVIDER": ("groq, gemini or auto: which free model reads the filings", "auto"),
    "GROQ_API_KEY_1": ("a second Groq key: its own daily allowance for the graph builder", "only the first key's quota"),
    "GEMINI_API_KEY_1": ("a second Gemini key: its own daily allowance", "only the first key's quota"),
    "GEOCODE_CONTACT": ("an email in the geocoder's User-Agent (OpenStreetMap asks for one)", "a generic description"),
    "OPENSKY_CLIENT_ID": ("OpenSky OAuth2 login for a bigger flight quota (4,000 credits a day)", "anonymous access (400 credits a day)"),
    "OPENSKY_CLIENT_SECRET": ("pairs with OPENSKY_CLIENT_ID", "anonymous access"),
    "AISSTREAM_API_KEY": ("free AISstream key for ship positions", "the vessel layer stays off and says why"),
    "AISHUB_USERNAME": ("AISHub membership (members who share an AIS feed only; one request a minute)", "not used"),
    "VESSELAPI_KEY": ("VesselAPI plan (paid; that source is switched off until its terms are verified)", "not used"),
    "TELEMETRY_INTERVAL_S": ("the refresh rate asked of the flight and vessel telemetry (default 30); the credit budgeter may make it slower", "30 asked, whatever the quota allows is achieved"),
}


def parse_env(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v:
            out[k] = v
    return out


def load_env(path=None, environ=None):
    """Load KEY=VALUE pairs from `.env` into the environment (existing variables win). Returns the names that were loaded, never the values."""
    environ = os.environ if environ is None else environ
    p = Path(path) if path else ROOT / ".env"
    try:
        pairs = parse_env(p.read_text(encoding="utf-8"))
    except OSError:
        return []
    loaded = []
    for k, v in pairs.items():
        if k not in environ:
            environ[k] = v
            loaded.append(k)
    return loaded


def startup_table(environ=None):
    """Plain-text table: setting | present? | what it does / what happens without it. Shows only whether a value exists, never the value."""
    environ = os.environ if environ is None else environ
    rows = [("setting", "present", "used for / without it")]
    for name, (use, without) in SETTINGS.items():
        have = bool(environ.get(name))
        rows.append((name, "yes" if have else "no", use if have else f"{use}; without it: {without}"))
    w0, w1 = max(len(r[0]) for r in rows), max(len(r[1]) for r in rows)
    return "\n".join(f"  {a.ljust(w0)}  {b.ljust(w1)}  {c}" for a, b, c in rows)


def announce(script, environ=None):
    """Called at the start of each ALADIN script: load .env, then print the table once."""
    load_env(environ=environ)
    print(f"{script}: settings (every one is optional)")
    print(startup_table(environ))
