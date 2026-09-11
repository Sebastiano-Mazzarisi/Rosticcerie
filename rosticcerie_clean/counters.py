"""Salvataggio giornaliero dei contatori, prima dell'estrazione dei menu."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from .config import ROSTICCERIE

OUTPUT = Path(__file__).resolve().parents[1] / "output" / "rosticceria_ios"
BASE = "https://abacus.jasoncameron.dev/get/rosticcerie-fantasia/"


def read_counter(key):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(BASE + key, timeout=30) as response:
                value = json.load(response)["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or int(value) != value:
                raise ValueError("Contatore non valido")
            return int(value)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return 0
            if attempt == 4:
                raise
            delay = error.headers.get("Retry-After", "")
            time.sleep(int(delay) + 1 if delay.isdigit() else 15 * (attempt + 1))
        except (OSError, ValueError, KeyError):
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))


def snapshot_if_due(now=None):
    now = now or datetime.now(ZoneInfo("Europe/Rome"))
    # Recupera anche un avvio notturno ritardato, senza sovrascrivere il
    # salvataggio gia' completato nella stessa giornata.
    if now.hour != 0 or now.minute < 1:
        return False
    marker = OUTPUT / "Rosticcerie-contatori-data.txt"
    day = now.date().isoformat()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == day:
        return False
    rows = []
    for restaurant in ROSTICCERIE:
        name = restaurant.name
        normalized = "".join(c for c in unicodedata.normalize("NFD", name) if not "\u0300" <= c <= "\u036f")
        slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
        total = read_counter("menu-views-" + slug)
        time.sleep(0.35)
        offset = read_counter("menu-views-offset-" + slug)
        value = total if offset > total else total - offset
        rows.append(f"{day} {name}, {value}")
        time.sleep(0.35)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "Rosticcerie-contatori.txt"
    temporary = target.with_suffix(".tmp")
    temporary.write_text("\n".join(rows) + "\n", encoding="utf-8")
    temporary.replace(target)
    marker.write_text(day + "\n", encoding="utf-8")
    print(f"Contatori salvati: {target}")
    return True


if __name__ == "__main__":
    snapshot_if_due()
