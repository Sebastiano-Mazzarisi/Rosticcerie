# Nome.py: Rosticceria.py
# Data e ora ultima modifica: 03/09/2026 23:19
# Descrizione: Estrae e pubblica i menu delle rosticcerie Fantasia, Cibària, Bollenti piatti, Pane&Co, Impastamò, Le delizie di Michela e Santoro da Facebook e web.
# File di input: cookies.txt
# File di output: status.json, Rosticcerie.html, immagini jpg
# Parametri: --once, --show, --no-git

import io
import json
import os
import re
import subprocess
import sys
import time
import argparse
import datetime
import html
import unicodedata
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Manca Playwright. Installa con: pip install playwright")
    print("Poi esegui: playwright install chromium")
    sys.exit(1)


FACEBOOK_PAGES = [
    {
        "name": "Fantasia",
        "url": "https://www.facebook.com/RosticceriaFantasia",
        "output_image": "Rosticceria_Fantasia.jpg",
    },
    {
        "name": "Cibària",
        "url": "https://www.facebook.com/cibaria.asporto",
        "output_image": "Rosticceria_Cibaria.jpg",
    },
    {
        "name": "Impastamò",
        "url": "https://www.facebook.com/profile.php?id=61560452176728",
        "output_image": "Rosticceria_Impastamo.jpg",
    },
    {
        "name": "Le delizie di Michela",
        "url": "https://www.facebook.com/profile.php?id=100045208848338",
        "output_image": "Rosticceria_LeDelizieDiMichela.jpg",
    },
    {
        "name": "Santoro (Castellana)",
        "url": "https://www.facebook.com/santorogastronomia",
        "output_image": "Rosticceria_Santoro.jpg",
    },
]
TEXT_FACEBOOK_PAGES = [
    {
        "name": "Bollenti piatti",
        "display_name": "Bollenti piatti",
        "url": "https://www.facebook.com/BollentiPiatti",
        "required_terms": ["secondi piatti"],
    },
]
PANECO_PAGE = {
    "name": "Pane & Co",
    "url": "https://www.paneeco.it/menu",
}
SOURCE_URLS = {page["name"]: page["url"] for page in FACEBOOK_PAGES}
SOURCE_URLS.update({page["name"]: page["url"] for page in TEXT_FACEBOOK_PAGES})
SOURCE_URLS[PANECO_PAGE["name"]] = PANECO_PAGE["url"]
COOKIE_FILE = "cookies.txt"
PUBLISH_DIR = os.path.join("output", "rosticceria_ios")
RUN_START = datetime.time(7, 0)
RUN_END = datetime.time(12, 0)
RUN_INTERVAL_MINUTES = 1
ITALIAN_MONTHS = {
    "gennaio": 1,
    "gen": 1,
    "febbraio": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "aprile": 4,
    "apr": 4,
    "maggio": 5,
    "mag": 5,
    "giugno": 6,
    "giu": 6,
    "luglio": 7,
    "lug": 7,
    "agosto": 8,
    "ago": 8,
    "settembre": 9,
    "set": 9,
    "ottobre": 10,
    "ott": 10,
    "novembre": 11,
    "nov": 11,
    "dicembre": 12,
    "dic": 12,
}
# Facebook mostra le date assolute in inglese (es. "August 29 at 1:22 PM")
# quando si naviga senza un login valido ed il post e' troppo vecchio per un
# tempo relativo ("2 g", "3 h", ...): senza questa tabella quella data non
# veniva riconosciuta affatto e il chiamante ripiegava sulla data odierna,
# facendo sembrare "appena aggiornato" un post vecchio di settimane.
ENGLISH_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
# Cookie che compaiono solo dopo un login Facebook riuscito. Se mancano,
# stiamo navigando come visitatori anonimi e Facebook mostra molte meno
# informazioni (spesso senza data/ora del post).
FACEBOOK_LOGIN_COOKIE_NAMES = {"c_user", "xs"}


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def load_facebook_cookies(cookie_path: str) -> List[Dict]:
    if not os.path.exists(cookie_path):
        return []

    cookies = []
    with open(cookie_path, "r", encoding="utf-8") as cookie_file:
        for line in cookie_file:
            if not line.strip() or line.startswith("#"):
                continue

            parts = line.rstrip("\n").split("\t")
            if len(parts) != 7:
                continue

            domain, _include_subdomains, path, secure, expires, name, value = parts
            if "facebook.com" not in domain:
                continue

            try:
                expires_value = int(float(expires))
            except ValueError:
                expires_value = -1

            cookies.append(
                {
                    "domain": domain,
                    "path": path or "/",
                    "secure": secure.upper() == "TRUE",
                    "expires": expires_value,
                    "name": name,
                    "value": value,
                    "httpOnly": False,
                    "sameSite": "Lax",
                }
            )

    return cookies


def clean_post_text(text: str) -> str:
    lines = []
    blocked = {
        "Mi piace",
        "Commenta",
        "Condividi",
        "Invia",
        "Tutti",
        "Piu pertinenti",
        "Più pertinenti",
        "Like",
        "Comment",
        "Share",
        "Send",
        "All",
        "Most relevant",
        "Reply",
        "All reactions:",
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in blocked:
            continue
        
        lower_line = line.lower()
        if (
            lower_line.startswith("foto di ")
            or lower_line.startswith("rosticceria fantasia")
            or lower_line.startswith("cibaria")
            or lower_line.startswith("cibarìa")
            or lower_line.startswith("bollenti")
            or lower_line.startswith("impastamo")
            or lower_line.startswith("impastamò")
            or lower_line.startswith("le delizie di michela")
            or lower_line.startswith("santoro")
            or lower_line.startswith("all reactions")
        ):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


_INVISIBLE_CHARS_RE = re.compile(
    "[\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u2066\u2067\u2068\u2069\ufeff\u00a0]"
)


def clean_text_menu_post(text: str) -> str:
    cleaned_lines = []

    for raw_line in clean_post_text(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Facebook a volte inserisce caratteri invisibili (marcatori di
        # direzione del testo, spazi unificatori, ecc.) attorno a numeri o
        # icone dei contatori: li rimuoviamo prima di valutare la
        # lunghezza "visibile" della riga, altrimenti righe di un solo
        # carattere visibile sfuggirebbero al controllo sotto.
        line = _INVISIBLE_CHARS_RE.sub("", line).strip()
        if not line:
            continue
        if re.fullmatch(r"\d+\s*(?:h|min|m|g|d)", line, re.IGNORECASE):
            continue
        if re.fullmatch(r"[·.\-]+", line):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if re.fullmatch(r"facebook", line, re.IGNORECASE):
            continue
        if re.match(r"^(?:Commenta come|Comment as)\b", line, re.IGNORECASE):
            continue
        if len(line) <= 1:
            continue

        line = re.sub(r"\s*Vedi meno\s*$", "", line, flags=re.IGNORECASE).strip()
        line = re.sub(r"\s*See less\s*$", "", line, flags=re.IGNORECASE).strip()
        # "Altro"/"See more" (a seconda della lingua dell'interfaccia di
        # Facebook) indicano un post troncato: il testo che segue non e'
        # presente, quindi rimuoviamo solo l'etichetta finale.
        line = re.sub(
            r"\s*(?:…|\.\.\.)\s*(?:Altro(?:\.\.\.)?|See more)\s*$",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()
        if re.match(r"^men[uù]\s+di\b", line, re.IGNORECASE):
            continue
        if not line:
            continue
        cleaned_lines.append(line)

    # Rete di sicurezza: se restano comunque diverse righe consecutive di
    # 1-2 caratteri visibili (es. le cifre di un contatore Facebook
    # spezzettate riga per riga), le eliminiamo in blocco: nel testo di un
    # vero menu non compaiono mai sequenze cosi'.
    filtered_lines = []
    i = 0
    total = len(cleaned_lines)
    while i < total:
        j = i
        while j < total and len(cleaned_lines[j]) <= 2:
            j += 1
        if j - i >= 4:
            i = j
            continue
        filtered_lines.append(cleaned_lines[i])
        i += 1

    return "\n".join(filtered_lines).strip()


def has_see_more_marker(text: str) -> bool:
    return bool(re.search(r"(?:…|\.\.\.)\s*Altro|Mostra altro|See more", text or "", re.IGNORECASE))


def expand_facebook_see_more(post, page) -> None:
    selectors = [
        'button:has-text("Altro")',
        'button:has-text("Mostra altro")',
        'button:has-text("See more")',
        'div[role="button"]:has-text("Altro")',
        'div[role="button"]:has-text("Mostra altro")',
        'div[role="button"]:has-text("See more")',
        'span:has-text("Altro")',
        'span:has-text("Mostra altro")',
        'span:has-text("See more")',
        'a:has-text("Altro")',
        'a:has-text("Mostra altro")',
        'a:has-text("See more")',
    ]

    for _ in range(4):
        clicked = False
        try:
            post.scroll_into_view_if_needed(timeout=1500)
            page.wait_for_timeout(250)
        except Exception:
            pass
        try:
            before_text = post.inner_text(timeout=1000)
        except Exception:
            before_text = ""

        # Nella pagina Facebook attuale "Altro..." spesso e' uno span di testo
        # senza ruolo button: cerchiamolo direttamente nel post e facciamolo
        # attivare con un click forzato.
        more_pattern = re.compile(
            r"^(?:…|\.\.\.)?\s*(?:Altro|Mostra altro|See more)\s*\.*$",
            re.IGNORECASE,
        )
        for more_locator in (post.get_by_text(more_pattern), page.get_by_text(more_pattern)):
            if clicked:
                break
            try:
                candidates = more_locator.all()
            except Exception:
                candidates = []
            for element in candidates:
                try:
                    if not element.is_visible(timeout=700):
                        continue
                    element.scroll_into_view_if_needed(timeout=1200)
                    element.click(timeout=2500, force=True)
                    page.wait_for_timeout(1200)
                    try:
                        after_text = post.inner_text(timeout=1500)
                    except Exception:
                        after_text = ""
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                    # Alcune versioni di Facebook rispondono all'attivazione
                    # da tastiera ma non al click sullo span visualizzato.
                    element.press("Enter", timeout=1500)
                    page.wait_for_timeout(1200)
                    after_text = post.inner_text(timeout=1500)
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                except Exception:
                    continue

        if clicked:
            try:
                after_text = post.inner_text(timeout=1500)
            except Exception:
                after_text = ""
            if after_text and after_text != before_text and not has_see_more_marker(after_text):
                return

        for selector in selectors:
            try:
                for element in post.locator(selector).all():
                    label = element.inner_text(timeout=700).strip()
                    lower_label = label.lower()
                    if "altro" not in lower_label and "see more" not in lower_label:
                        continue
                    if not element.is_visible(timeout=700):
                        continue
                    element.click(timeout=2000, force=True)
                    page.wait_for_timeout(900)
                    clicked = True
                    break
            except Exception:
                pass
            if clicked:
                break
            try:
                candidates = more_locator.all()
            except Exception:
                candidates = []
            for element in candidates:
                try:
                    if not element.is_visible(timeout=700):
                        continue
                    element.scroll_into_view_if_needed(timeout=1200)
                    element.click(timeout=2500, force=True)
                    page.wait_for_timeout(1200)
                    try:
                        after_text = post.inner_text(timeout=1500)
                    except Exception:
                        after_text = ""
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                    # Alcune versioni di Facebook rispondono all'attivazione
                    # da tastiera ma non al click sullo span visualizzato.
                    element.press("Enter", timeout=1500)
                    page.wait_for_timeout(1200)
                    after_text = post.inner_text(timeout=1500)
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                except Exception:
                    text = ""
                if text:
                    candidates.append(text)
        except Exception:
            pass

    try:
        text = post.inner_text(timeout=3000)
        candidates.extend(line.strip() for line in text.splitlines()[:10] if line.strip())
    except Exception:
        pass

    seen = set()
    for value in candidates:
        compact = re.sub(r"\s+", " ", value).strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        if looks_like_facebook_time(compact):
            return compact

    return ""


def rome_now() -> datetime.datetime:
    return datetime.datetime.now(ZoneInfo("Europe/Rome"))


ITALIAN_WEEKDAYS = [
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
]
ITALIAN_MONTH_NAMES = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def italian_long_date(value: datetime.date) -> str:
    """Restituisce la data nel formato esteso italiano richiesto, ad
    esempio 'Venerdì 4 settembre' (giorno della settimana con iniziale
    maiuscola, mese minuscolo, senza anno)."""
    weekday = ITALIAN_WEEKDAYS[value.weekday()].capitalize()
    month = ITALIAN_MONTH_NAMES[value.month - 1]
    return f"{weekday} {value.day} {month}"


def format_menu_date(value: str) -> str:
    """Converte una data 'DD/MM/YYYY' (con eventuale testo/orario dopo,
    come prodotto da normalize_facebook_time/normalize_paneeco_date) nel
    formato esteso italiano. Restituisce stringa vuota se non riconosciuta,
    cosi' chi chiama puo' scegliere di non stampare nulla."""
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value or "")
    if not match:
        return ""
    try:
        day, month, year = (int(match.group(i)) for i in (1, 2, 3))
        return italian_long_date(datetime.date(year, month, day))
    except ValueError:
        return ""


def normalize_facebook_time(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    lower_value = value.lower()
    now = rome_now()

    match = re.search(r"\d{4}-\d{2}-\d{2}(?:[t ][0-9:.+-]+)?", lower_value)
    if match:
        raw_iso = match.group(0)
        try:
            published = datetime.datetime.fromisoformat(raw_iso.replace("z", "+00:00"))
            if published.tzinfo:
                published = published.astimezone(ZoneInfo("Europe/Rome"))
            return published.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass

    if lower_value.startswith(("oggi", "today")):
        match = re.search(r"(\d{1,2})[:.](\d{2})", lower_value)
        if match:
            published = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
            return published.strftime("%d/%m/%Y %H:%M")
        return now.strftime("%d/%m/%Y circa")

    # I confini di parola (\b) sono importanti: senza di essi una stringa
    # "casuale" (es. un URL o un ID interno di Facebook) puo' contenere per
    # coincidenza una cifra seguita da una lettera come "h"/"g"/"d"/"w" in
    # mezzo ad altri caratteri, venendo interpretata come un tempo relativo
    # e producendo una data completamente inventata.
    match = re.search(r"\b(\d{1,3})\s*(min|minuti|m)\b", lower_value)
    if match:
        minutes = int(match.group(1))
        return (now - datetime.timedelta(minutes=minutes)).strftime("%d/%m/%Y %H:%M circa")

    match = re.search(r"\b(\d{1,3})\s*(h|ore?|ora|hours?)\b", lower_value)
    if match:
        hours = int(match.group(1))
        return (now - datetime.timedelta(hours=hours)).strftime("%d/%m/%Y %H:%M circa")

    match = re.search(r"\b(\d{1,3})\s*(g|gg|giorno|giorni|d|days?)\b", lower_value)
    if match:
        days = int(match.group(1))
        return (now - datetime.timedelta(days=days)).strftime("%d/%m/%Y circa")

    match = re.search(r"\b(\d{1,3})\s*(sett|settiman[ae]|settimane|w|weeks?)\b", lower_value)
    if match:
        weeks = int(match.group(1))
        return (now - datetime.timedelta(weeks=weeks)).strftime("%d/%m/%Y circa")

    if lower_value.startswith(("ieri", "yesterday")):
        published = now - datetime.timedelta(days=1)
        match = re.search(r"(\d{1,2})[:.](\d{2})", lower_value)
        if match:
            published = published.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
        return published.strftime("%d/%m/%Y %H:%M")

    # Data assoluta in inglese (es. "August 29 at 1:22 PM", "Aug 29, 2025"):
    # vedi il commento sopra ENGLISH_MONTHS.
    english_month_pattern = "|".join(ENGLISH_MONTHS.keys())
    match = re.search(
        rf"\b({english_month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?"
        rf"(?:\s+at\s+(\d{{1,2}})[:.](\d{{2}})\s*(am|pm)?)?",
        lower_value,
    )
    if match:
        month = ENGLISH_MONTHS[match.group(1)]
        day = int(match.group(2))
        explicit_year = match.group(3)
        year = int(explicit_year) if explicit_year else now.year
        try:
            candidate = datetime.date(year, month, day)
            if not explicit_year and candidate > now.date():
                # Nessun anno esplicito e la data risulterebbe nel futuro:
                # il post e' quasi certamente dell'anno precedente.
                candidate = datetime.date(year - 1, month, day)
            if match.group(4) and match.group(5):
                hour = int(match.group(4))
                minute = match.group(5)
                meridiem = (match.group(6) or "").lower()
                if meridiem == "pm" and hour != 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0
                return f"{candidate.strftime('%d/%m/%Y')} {hour:02d}:{minute}"
            return candidate.strftime("%d/%m/%Y")
        except ValueError:
            pass

    inferred = infer_date_from_text(value)
    if inferred:
        return inferred

    # Nessun formato riconosciuto: meglio restituire una stringa vuota (che i
    # chiamanti trattano come "non trovata") piuttosto che l'intero testo in
    # ingresso invariato. In precedenza, quando "value" era l'intero testo di
    # un post (perche' non si era trovata nessuna etichetta di tempo), questo
    # ramo lo restituiva cosi' com'era: il chiamante lo scambiava per una data
    # valida gia' "normalizzata" e lo salvava in status.json al posto della
    # data, gonfiandolo inutilmente senza mai mostrare una vera data.
    return ""


def looks_like_facebook_time(value: str) -> bool:
    value = value.strip().lower()
    if not value:
        return False
    if value.startswith(("http://", "https://", "/")) and not re.search(
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b", value
    ):
        return False
    # Gli URL/permalink dei post Facebook (es. "/stories/.../?...&__cft__..."
    # oppure con "__tn__=") non sono mai una vera etichetta di tempo, anche se
    # contengono per caso cifre e lettere isolate: li escludiamo subito,
    # prima ancora di controllare le parole "relative" qui sotto.
    if any(marker in value for marker in ("=", "&", "__")):
        return False

    month_words = list(ITALIAN_MONTHS.keys()) + [
        "january",
        "jan",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "aug",
        "september",
        "sep",
        "sept",
        "october",
        "oct",
        "november",
        "december",
        "dec",
    ]
    # I confini di parola (\b) evitano che una cifra seguita per coincidenza
    # da una lettera isolata dentro una stringa piu' lunga (non un vero
    # "23h"/"1d" restituito da Facebook) venga scambiata per un tempo
    # relativo valido.
    relative_pattern = re.compile(
        r"\b\d{1,3}\s*(min|minuti|m|h|ore?|ora|hours?|gg|giorno|giorni|g|days?|d"
        r"|settiman[ae]|settimane|sett|weeks?|w)\b"
    )
    has_digit = any(char.isdigit() for char in value)

    return has_digit and (
        any(month in value for month in month_words)
        or bool(relative_pattern.search(value))
        or bool(re.search(r"\b\d{1,2}:\d{2}\b", value))
        or bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", value))
        or bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", value))
    )


def image_score(image) -> int:
    try:
        box = image.bounding_box(timeout=1000)
    except Exception:
        box = None

    if not box:
        return 0

    width = int(box.get("width", 0))
    height = int(box.get("height", 0))
    if width < 180 or height < 120:
        return 0

    src = image.get_attribute("src") or ""
    if not src.startswith("http"):
        return 0
    if "emoji.php" in src or "static.xx.fbcdn.net" in src:
        return 0

    return width * height


def find_first_post_image(
    page, skip_closure_notices: bool = False
) -> Optional[Dict[str, str]]:
    post_selectors = [
        'div[role="article"]',
        "div[aria-posinset]",
    ]

    for selector in post_selectors:
        posts = page.locator(selector).all()
        for post in posts[:20]:
            try:
                images = post.locator("img").all()
            except Exception:
                continue

            best_image = None
            best_score = 0
            for image in images:
                score = image_score(image)
                if score > best_score:
                    best_image = image
                    best_score = score

            if best_image and best_score:
                image_url = best_image.get_attribute("src")
                if image_url:
                    try:
                        image_alt = (best_image.get_attribute("alt") or "").strip()
                    except Exception:
                        image_alt = ""
                    post_text = best_text_from_post(post)
                    try:
                        full_post_text = clean_post_text(post.inner_text(timeout=3000))
                    except Exception:
                        full_post_text = post_text
                    if skip_closure_notices and looks_like_closure_notice(
                        f"{post_text} {full_post_text} {image_alt}"
                    ):
                        print(
                            "Impastamò: salto l'immagine dell'annuncio di riapertura "
                            "e cerco il post successivo con il menu."
                        )
                        continue
                    date_in_post_text = infer_date_from_text(post_text) or infer_date_from_text(full_post_text)
                    facebook_time = best_published_time_from_post(post)
                    normalized_facebook_time = normalize_facebook_time(facebook_time)
                    # Quando Facebook mostra una data esplicita nel post
                    # (es. "29 agosto alle 13:22"), e' piu' affidabile del
                    # primo indicatore temporale relativo trovato nel DOM.
                    published_at_raw = date_in_post_text or facebook_time
                    published_at = date_in_post_text or normalized_facebook_time or rome_now().strftime("%d/%m/%Y")
                    try:
                        photo_url = best_image.evaluate(
                            "image => { const link = image.closest('a[href]'); return link ? link.href : ''; }"
                        )
                    except Exception:
                        photo_url = ""
                    return {
                        "image_url": image_url,
                        "photo_url": photo_url,
                        "text": post_text,
                        "image_alt": image_alt,
                        "published_at": published_at,
                        "published_at_raw": published_at_raw,
                    }

    return None

        if clicked:
            try:
                after_text = post.inner_text(timeout=1500)
            except Exception:
                pass

            if prefer_active_closure:
                try:
                    closure_post = find_active_closure_post_via_photos(context, facebook_url)
                except Exception:
                    closure_post = None
                if closure_post:
                    return closure_post

            page.wait_for_timeout(5000)
            for _ in range(4):
                post = find_first_post_image(page, skip_closure_notices=skip_closure_notices)
                if post:
                    photo_url = post.get("photo_url", "")
                    if photo_url:
                        try:
                            photo_page = context.new_page()
                            photo_page.goto(photo_url, wait_until="domcontentloaded", timeout=60000)
                            photo_page.wait_for_timeout(4000)
                            larger_image_url = find_largest_visible_image_url(photo_page)
                            photo_page.close()
                            if larger_image_url:
                                post["image_url"] = larger_image_url
                        except Exception:
                            pass
                    return post
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(2000)

            raise RuntimeError(f"Non ho trovato nessuna immagine grande nella pagina Facebook: {facebook_url}")
        finally:
            browser.close()


def dump_debug_facebook(page, nome: str = "Bollenti piatti") -> None:
    """Stampa nei log del job una diagnostica testuale di cosa Playwright
    sta vedendo sulla pagina Facebook al momento del fallimento: URL finale,
    titolo, lunghezza dell'HTML, i primi caratteri del testo visibile, una
    classificazione euristica (login wall? checkpoint? cookie banner?
    contenuto non disponibile?) e i testi di bottoni/link visibili.

    Serve per capire la causa del blocco senza dover scaricare l'artefatto
    diagnostico (screenshot/HTML) dalla UI di GitHub Actions: tutto questo
    finisce direttamente nel log dello step, leggibile da chiunque abbia
    accesso al workflow.
    """
    print("\n" + "=" * 80)
    print(f"DIAGNOSTICA FACEBOOK — {nome}")
    print("=" * 80)

    try:
        print("URL finale:", page.url)
    except Exception as exc:
        print("URL non leggibile:", repr(exc))

    try:
        print("Titolo:", page.title())
    except Exception as exc:
        print("Titolo non leggibile:", repr(exc))

    try:
        html = page.content()
        print("Lunghezza HTML:", len(html))
    except Exception as exc:
        print("HTML non leggibile:", repr(exc))

    try:
        body_text = page.locator("body").inner_text(timeout=5000)
    except Exception as exc:
        body_text = ""
        print("Body non leggibile:", repr(exc))

    print("\n--- BODY, primi 6000 caratteri ---")
    print(body_text[:6000])

    low = body_text.lower()
    checks = {
        "login_wall": [
            "log in", "login", "accedi",
            "email or phone", "e-mail o numero di telefono",
        ],
        "checkpoint": [
            "checkpoint", "security check", "controllo di sicurezza",
            "confirm your identity", "conferma la tua identità",
        ],
        "contenuto_non_disponibile": [
            "content isn't available", "this content isn't available",
            "contenuto non disponibile", "questa pagina non è disponibile",
        ],
        "cookie": [
            "allow all cookies", "accept all", "consenti tutti i cookie",
        ],
    }

    print("\n--- CLASSIFICAZIONE ---")
    for tipo, parole in checks.items():
        trovato = any(p in low for p in parole)
        print(f"{tipo}: {trovato}")

    try:
        buttons = page.locator("button").all_inner_texts()
        print("\n--- BUTTON (primi 30) ---")
        print(buttons[:30])
    except Exception as exc:
        print("Button non leggibili:", repr(exc))

    try:
        links = page.locator("a").all_inner_texts()
        print("\n--- LINK (primi 30) ---")
        print(links[:30])
    except Exception as exc:
        print("Link non leggibili:", repr(exc))

    print("=" * 80 + "\n")
    .updated {{
      margin: 4px 0 0;
      color: #fff;
      font-size: 16px;
      cursor: pointer;
      user-select: none;
    }}
    .signature {{
      margin: 2px 0 0;
      color: #fff;
      font-size: 14px;
      cursor: pointer;
      user-select: none;
    }}
    /* Nome + telefono mostrati sopra all'immagine nel dettaglio */
    #phone-line {{
      display: none;
      text-align: center;
      padding: 10px 16px 0;
    }}
    #phone-line a {{
      color: #00c853;
      font-size: 20px;
      font-weight: bold;
      text-decoration: none;
    }}
    /* Griglia dei bottoni iniziali: distanziati di 10px tra loro e dai margini */
    main {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 10px;
      box-sizing: border-box;
    }}
    .card {{
      position: relative;
      appearance: none;
      -webkit-appearance: none;
      font: inherit;
      background: #e5e5e5; /* Giallo tenue per i menu aggiornati, grigio per gli altri */
      box-sizing: border-box;
      cursor: pointer;
      user-select: none;
    }}
    /* Nome + telefono mostrati sopra all'immagine nel dettaglio */
    #phone-line {{
      display: none;
      text-align: center;
      padding: 10px 16px 0;
    }}
    #phone-line a {{
      color: #00c853;
      font-size: 20px;
      font-weight: bold;
      text-decoration: none;
    }}
    /* Griglia dei bottoni iniziali: distanziati di 10px tra loro e dai margini */
    main {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 10px;
      box-sizing: border-box;
    }}
    .card {{
      position: relative;
      appearance: none;
      -webkit-appearance: none;
      font: inherit;
      background: #e5e5e5; /* Giallo tenue per i menu aggiornati, grigio per gli altri */
      box-sizing: border-box;
      cursor: pointer;
      min-height: 110px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 12px;
      border: 4px solid #555555; /* Giallo se aggiornata oggi, grigio scuro altrimenti */
      border-radius: 12px;
      /* Evita che una pressione prolungata (usata per riordinare le
         caselle) selezioni il testo o apra il menu contestuale del
         browser/telefono. "none" (non "manipulation") e' necessario:
         altrimenti il browser puo' interpretare il primo piccolo
         movimento del dito, durante l'attesa della pressione lunga,
         come l'inizio di uno scorrimento nativo della pagina, che poi
         "cattura" il gesto e blocca il trascinamento successivo. */
      touch-action: none;
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
    }}
    .card .card-name {{
      font-size: clamp(16px, 5vw, 26px);
      color: #111; /* Nomi neri */
      font-weight: bold;
    }}
    .card-counter {{
      display: none;
      position: absolute;
      bottom: 4px;
      right: 8px;
      font-size: 11px;
      font-weight: normal;
      color: #555;
    }}
    /* Riordino personalizzato delle caselle iniziali (stile iOS/Android):
       tenendo premuta una casella, tutte "tremano" leggermente e quella
       tenuta premuta lampeggia con la cornice; trascinandola sopra
       un'altra le due si scambiano di posto. L'ordine scelto viene
       salvato sul dispositivo (localStorage), non e' condiviso tra
       dispositivi diversi. */
    @keyframes cardJiggle {{
      0%, 100% {{ transform: rotate(-1deg); }}
      50% {{ transform: rotate(1deg); }}
    }}
    @keyframes cardBlink {{
      0%, 100% {{ box-shadow: 0 0 0 0 rgba(0,123,255,0); }}
      50% {{ box-shadow: 0 0 0 6px rgba(0,123,255,0.65); }}
    }}
    .card.jiggling {{
      animation: cardJiggle 0.24s ease-in-out infinite;
    }}
    .card.dragging {{
      animation: cardBlink 0.6s ease-in-out infinite;
      cursor: grabbing;
      z-index: 10;
    }}
    #reorder-actions {{
      display: none;
      position: absolute;
      top: 14px;
      right: 16px;
      gap: 8px;
    }}
    #reorder-actions button {{
      border: none;
      border-radius: 999px;
      padding: 8px 18px;
      font-size: 15px;
      font-weight: bold;
      cursor: pointer;
    }}
    #reorder-reset-btn {{
      background: #e9ecef;
      color: #333;
    }}
    #reorder-done-btn {{
      background: #007bff;
      color: #fff;
    }}
    .error {{
      color: #ffd0d0;
      font-size: 16px;
      text-align: center;
      padding: 20px;
    }}

    /* Layout per monitor normali/piccoli */
    @media (max-width: 1200px) {{
      main {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    /* Dettaglio a tutto schermo */
    #detail-view {{
      display: none;
      padding-bottom: 85px; /* Spazio per la fascia con le frecce */
    }}
    #detail-content {{
      padding: 12px;
      cursor: pointer; /* Toccare l'immagine (o il messaggio) torna all'elenco */
    }}
    #detail-content img {{
      width: 100%;
      height: auto;
      display: block;
      margin: 0 auto;
    }}

    /* Su schermi da PC la foto occupa circa un terzo della larghezza
       (equivalente a 3 colonne), invece di riempire tutto lo schermo. */
    @media (min-width: 900px) {{
      #detail-content img {{
        width: 33%;
      }}
    }}

    /* Fascia nera inferiore con le frecce di navigazione */
    #nav-bar {{
      display: none;
      background: #000;
      padding: 14px 24px;
      align-items: center;
      justify-content: space-between;
      position: fixed;
      bottom: 0;
      width: 100%;
      z-index: 100;
      border-top: 1px solid #333;
      box-sizing: border-box;
    }}
    #nav-bar button {{
      appearance: none;
      -webkit-appearance: none;
      background: none;
      border: none;
      color: #fff;
      font-size: 30px;
      line-height: 1;
      padding: 6px 24px;
      cursor: pointer;
    }}
    #nav-position {{
      color: #fff;
      font-size: 18px;
      font-weight: bold;
    }}
  </style>
  <script>
    const PANELS = {panels_json};
    let currentIndex = -1;

    const urlParams = new URLSearchParams(window.location.search);
    const isAdmin = urlParams.get('v') === '57';
    // Uso un'API globale gratuita per il contatore, un contatore separato per ogni rosticceria
    const ABACUS_BASE = 'https://abacus.jasoncameron.dev';
    const COUNTER_NAMESPACE = 'rosticcerie-fantasia';

    function slugify(s) {{
        return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    }}
    function counterKeyFor(name) {{ return 'menu-views-' + slugify(name); }}
    function offsetKeyFor(name) {{ return 'menu-views-offset-' + slugify(name); }}
    function counterGetUrlFor(name) {{ return ABACUS_BASE + '/get/' + COUNTER_NAMESPACE + '/' + counterKeyFor(name); }}
    function counterHitUrlFor(name) {{ return ABACUS_BASE + '/hit/' + COUNTER_NAMESPACE + '/' + counterKeyFor(name); }}
    function offsetGetUrlFor(name) {{ return ABACUS_BASE + '/get/' + COUNTER_NAMESPACE + '/' + offsetKeyFor(name); }}
    function offsetHitUrlFor(name) {{ return ABACUS_BASE + '/hit/' + COUNTER_NAMESPACE + '/' + offsetKeyFor(name); }}

    function fetchWithRetry(url, attempts) {{
        return fetch(url).catch(err => {{
            if (attempts > 1) {{
                return new Promise(resolve => setTimeout(resolve, 800)).then(() => fetchWithRetry(url, attempts - 1));
            }}
            throw err;
        }});
    }}

    function sleep(ms) {{
        return new Promise(resolve => setTimeout(resolve, ms));
    }}

    function parseRetryAfterSeconds(text) {{
        const match = /try again in\s*([\d.]+)\s*s/i.exec(text || '');
        return match ? Math.ceil(parseFloat(match[1])) : 10;
    }}

    // A differenza di fetchWithRetry, questa funzione controlla anche lo
    // stato HTTP e il contenuto della risposta: l'API gratuita di Abacus,
    // se interrogata troppo rapidamente (es. azzerando un contatore con
    // molte visualizzazioni), risponde con HTTP 429 e un corpo tipo
    // {{"error": "Too many requests..."}}. fetch() non considera questo un
    // errore di rete, quindi senza questo controllo il codice leggeva
    // "value" da una risposta di errore, lo interpretava come 0 e
    // azzerava il contatore solo sullo schermo, senza aver davvero
    // azzerato nulla sul server: al ricaricamento della pagina il valore
    // precedente ricompariva.
    async function fetchJsonWithRetry(url, attempts) {{
        for (let attempt = 1; attempt <= attempts; attempt++) {{
            let response;
            try {{
                response = await fetch(url);
            }} catch (err) {{
                if (attempt === attempts) {{
                    throw err;
                }}
                await sleep(1000);
                continue;
            }}

            if (response.status === 429) {{
                const body = await response.text();
                if (attempt === attempts) {{
                    throw new Error('Troppe richieste: ' + body);
                }}
                await sleep((parseRetryAfterSeconds(body) + 1) * 1000);
                continue;
            }}

            if (!response.ok) {{
                if (attempt === attempts) {{
                    throw new Error('Risposta HTTP ' + response.status);
                }}
                await sleep(800);
                continue;
            }}

            const data = await response.json();
            if (typeof data.value !== 'number') {{
                if (attempt === attempts) {{
                    throw new Error('Risposta senza "value": ' + JSON.stringify(data));
                }}
                await sleep(800);
                continue;
            }}
            return data;
        }}
        throw new Error('fetchJsonWithRetry: tentativi esauriti per ' + url);
    }}

    let totalClicksByPanel = [];
    let offsetClicksByPanel = [];

    async function loadCounter() {{
        if (!isAdmin) return;
        // Leggiamo i contatori uno alla volta (non tutti insieme) e con una
        // piccola pausa tra una richiesta e l'altra, per restare sotto il
        // limite di frequenza dell'API gratuita di Abacus.
        for (let i = 0; i < PANELS.length; i++) {{
            const p = PANELS[i];
            try {{
                const totalData = await fetchJsonWithRetry(counterGetUrlFor(p.name), 4);
                const offsetData = await fetchJsonWithRetry(offsetGetUrlFor(p.name), 4);
                totalClicksByPanel[i] = totalData.value;
                offsetClicksByPanel[i] = offsetData.value;
            }} catch (e) {{
                console.error('Impossibile leggere il contatore di ' + p.name, e);
            }}
            await sleep(150);
        }}
        updateAdminTitle();
        updateCardCounters();
    }}

    async function resetCounterGlobally() {{
        const mainTitle = document.getElementById('main-title');
        for (let i = 0; i < PANELS.length; i++) {{
            const p = PANELS[i];
            mainTitle.innerText = 'Azzeramento in corso... (' + (i + 1) + '/' + PANELS.length + ')';
            try {{
                const totalData = await fetchJsonWithRetry(counterGetUrlFor(p.name), 4);
                const target = totalData.value;
                const offsetData = await fetchJsonWithRetry(offsetGetUrlFor(p.name), 4);
                let current = offsetData.value;
                while (current < target) {{
                    // L'unico modo per "azzerare" un contatore di sola
                    // lettura/incremento come quello di Abacus e' portare
                    // l'offset allo stesso valore del totale: la pausa tra
                    // un incremento e l'altro evita di superare il limite
                    // di frequenza dell'API (che altrimenti interrompeva
                    // l'azzeramento quasi subito sui contatori con molte
                    // visualizzazioni).
                    await fetchJsonWithRetry(offsetHitUrlFor(p.name), 4);
                    current++;
                    await sleep(300);
                }}
                totalClicksByPanel[i] = target;
                offsetClicksByPanel[i] = current;
            }} catch (e) {{
                // Un errore su una rosticceria non deve bloccare
                // l'azzeramento delle altre: proseguiamo con la prossima
                // invece di interrompere tutto il ciclo.
                console.error('Azzeramento fallito per ' + p.name, e);
            }}
            updateAdminTitle();
            updateCardCounters();
            await sleep(200);
        }}
    }}

    function updateAdminTitle() {{
        let val = 0;
        for (let i = 0; i < PANELS.length; i++) {{
            val += Math.max(0, (totalClicksByPanel[i] || 0) - (offsetClicksByPanel[i] || 0));
        }}
        document.getElementById('main-title').innerText = `Rosticcerie (${{val.toLocaleString('it-IT')}})`;
    }}

    function updateCardCounters() {{
        if (!isAdmin) return;
        for (let i = 0; i < PANELS.length; i++) {{
            const el = document.getElementById('card-counter-' + i);
            if (!el) continue;
            const val = Math.max(0, (totalClicksByPanel[i] || 0) - (offsetClicksByPanel[i] || 0));
            el.innerText = val.toLocaleString('it-IT');
            el.style.display = 'block';
        }}
    }}

    // --- Riordino personalizzato delle caselle iniziali (tenere premuto
    // per "tremare" + trascinare per scambiare posto, come su iOS/Android).
    // L'ordine e' salvato in localStorage: e' quindi personale per ogni
    // dispositivo/browser, non condiviso tra dispositivi diversi ne'
    // pubblicato sul sito.
    const ORDER_STORAGE_KEY = 'rosticcerie-order-v1';
    let order = PANELS.map((_, i) => i);
    let reorderMode = false;
    let dragState = null;
    const LONG_PRESS_MS = 450;
    const MOVE_CANCEL_PX = 10;

    function loadSavedOrder() {{
        try {{
            const raw = localStorage.getItem(ORDER_STORAGE_KEY);
            if (!raw) return;
            const savedNames = JSON.parse(raw);
            if (!Array.isArray(savedNames)) return;
            const nameToIndex = new Map(PANELS.map((p, i) => [p.name, i]));
            const restored = [];
            const seen = new Set();
            savedNames.forEach(name => {{
                if (nameToIndex.has(name) && !seen.has(name)) {{
                    restored.push(nameToIndex.get(name));
                    seen.add(name);
                }}
            }});
            // Eventuali rosticcerie nuove non presenti nell'ordine salvato
            // vengono aggiunte in coda, nell'ordine con cui arrivano dal server.
            PANELS.forEach((p, i) => {{
                if (!seen.has(p.name)) {{
                    restored.push(i);
                    seen.add(p.name);
                }}
            }});
            if (restored.length === PANELS.length) {{
                order = restored;
            }}
        }} catch (e) {{
            console.error('Ordine personalizzato non leggibile, uso quello di default', e);
        }}
    }}

    function saveOrder() {{
        try {{
            localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify(order.map(i => PANELS[i].name)));
        }} catch (e) {{
            console.error("Impossibile salvare l'ordine personalizzato", e);
        }}
    }}

    function applyOrderToGrid() {{
        const grid = document.getElementById('grid-view');
        order.forEach(pid => {{
            const el = grid.querySelector('.card[data-pid="' + pid + '"]');
            if (el) grid.appendChild(el);
        }});
    }}

    function cardClicked(pid) {{
        // Mentre si sta riordinando (casella tenuta premuta/trascinata)
        // il tocco non deve aprire il dettaglio del menu.
        if (reorderMode) return;
        openDetail(order.indexOf(pid));
    }}

    function syncOrderFromDom() {{
        const grid = document.getElementById('grid-view');
        order = Array.from(grid.querySelectorAll('.card')).map(c => parseInt(c.dataset.pid, 10));
    }}

    function showReorderActions() {{
        document.getElementById('reorder-actions').style.display = 'flex';
    }}

    function exitReorderMode() {{
        reorderMode = false;
        document.getElementById('grid-view').querySelectorAll('.card').forEach(c => {{
            c.classList.remove('jiggling', 'dragging');
        }});
        document.getElementById('reorder-actions').style.display = 'none';
        saveOrder();
    }}

    const DEFAULT_ORDER_NAMES = [
        'Fantasia', 'Cibària', 'Pane & Co', 'Impastamò',
        'Bollenti piatti', 'Le delizie di Michela', 'Santoro (Castellana)',
    ];

    function resetOrderToDefault() {{
        const nameToIndex = new Map(PANELS.map((p, i) => [p.name, i]));
        const restored = [];
        const seen = new Set();
        DEFAULT_ORDER_NAMES.forEach(name => {{
            if (nameToIndex.has(name) && !seen.has(name)) {{
                restored.push(nameToIndex.get(name));
                seen.add(name);
            }}
        }});
        // Eventuali rosticcerie non presenti nell'elenco di default (es.
        // aggiunte in futuro) vengono messe in coda, cosi' il pulsante
        // Reset non le fa sparire.
        PANELS.forEach((p, i) => {{
            if (!seen.has(p.name)) {{
                restored.push(i);
                seen.add(p.name);
            }}
        }});
        order = restored;
        applyOrderToGrid();
        saveOrder();
    }}

    function startDrag(el, e) {{
        reorderMode = true;
        // Punto in cui l'utente ha "afferrato" la casella, relativo al suo
        // angolo in alto a sinistra (prima di applicare qualunque
        // transform): serve per calcolare ad ogni spostamento la nuova
        // posizione senza accumulare l'offset dalla pressione iniziale.
        const startRect = el.getBoundingClientRect();
        dragState = {{
            el,
            grabOffsetX: e.clientX - startRect.left,
            grabOffsetY: e.clientY - startRect.top,
        }};
        el.classList.add('dragging');
        el.style.touchAction = 'none';
        document.getElementById('grid-view').querySelectorAll('.card').forEach(c => {{
            if (c !== el) c.classList.add('jiggling');
        }});
        showReorderActions();
        if (navigator.vibrate) {{
            try {{ navigator.vibrate(15); }} catch (err) {{}}
        }}
    }}

    function updateDrag(e) {{
        if (!dragState) return;
        e.preventDefault();

        const grid = document.getElementById('grid-view');
        const cards = Array.from(grid.querySelectorAll('.card'));
        let target = null;
        for (const c of cards) {{
            if (c === dragState.el) continue;
            const r = c.getBoundingClientRect();
            if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {{
                target = c;
                break;
            }}
        }}
        if (target) {{
            // Decidiamo se inserire il trascinato prima o dopo il bersaglio
            // guardando la posizione del PUNTATORE rispetto al centro del
            // bersaglio (non il rettangolo dell'elemento trascinato, che a
            // causa del transform non riflette piu' la sua posizione nel
            // flusso della griglia).
            const targetRect = target.getBoundingClientRect();
            const centerX = targetRect.left + targetRect.width / 2;
            const centerY = targetRect.top + targetRect.height / 2;
            const before = (e.clientY < centerY - 2) ||
                (Math.abs(e.clientY - centerY) <= 2 && e.clientX < centerX);
            if (before) {{
                grid.insertBefore(dragState.el, target);
            }} else {{
                grid.insertBefore(dragState.el, target.nextSibling);
            }}
            syncOrderFromDom();
        }}

        // Ricalcoliamo SEMPRE la posizione statica (senza transform) della
        // casella trascinata, per poi spostarla di conseguenza dal
        // puntatore: se invece si accumula lo scostamento dalla pressione
        // iniziale (come in precedenza), dopo un primo scambio la casella
        // si ritrova in una cella diversa da quella di partenza e il
        // trascinamento "salta" lontano dal dito/puntatore.
        dragState.el.style.transform = '';
        const staticRect = dragState.el.getBoundingClientRect();
        const dx = e.clientX - dragState.grabOffsetX - staticRect.left;
        const dy = e.clientY - dragState.grabOffsetY - staticRect.top;
        dragState.el.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(1.06)';
    }}

    function endDrag() {{
        if (!dragState) return;
        dragState.el.classList.remove('dragging');
        dragState.el.style.transform = '';
        dragState.el.style.touchAction = '';
        dragState.el.classList.add('jiggling');
        dragState = null;
        syncOrderFromDom();
        saveOrder();
    }}

    // Stato della "pressione" in corso (prima che diventi un trascinamento
    // vero e proprio). E' condiviso (non per-casella) perche' puo' esserci
    // al piu' una pressione/trascinamento attivo alla volta.
    let pressTimer = null;
    let pressStartX = 0;
    let pressStartY = 0;
    let pressMoved = false;

    // Ascoltiamo pointermove/pointerup sulla finestra (non sulla singola
    // casella): una volta avviato il trascinamento, la casella viene
    // spostata nel DOM (insertBefore) per farle cambiare posizione nella
    // griglia, e questo interrompe la pointer capture sull'elemento —
    // senza un listener globale, gli eventi successivi al primo scambio
    // andrebbero persi e il trascinamento si bloccherebbe dopo il primo
    // spostamento.
    function onWindowPointerMove(e) {{
        if (dragState) {{
            updateDrag(e);
            return;
        }}
        const dx = e.clientX - pressStartX;
        const dy = e.clientY - pressStartY;
        if (Math.hypot(dx, dy) > MOVE_CANCEL_PX) {{
            pressMoved = true;
            clearTimeout(pressTimer);
        }}
    }}

    function onWindowPointerUp() {{
        clearTimeout(pressTimer);
        if (dragState) {{
            endDrag();
        }}
        window.removeEventListener('pointermove', onWindowPointerMove);
        window.removeEventListener('pointerup', onWindowPointerUp);
        window.removeEventListener('pointercancel', onWindowPointerUp);
    }}

    function attachDragHandlers() {{
        const grid = document.getElementById('grid-view');
        grid.querySelectorAll('.card').forEach(el => {{
            el.addEventListener('contextmenu', (e) => e.preventDefault());

            el.addEventListener('pointerdown', (e) => {{
                if (e.pointerType === 'mouse' && e.button !== 0) return;
                pressStartX = e.clientX;
                pressStartY = e.clientY;
                pressMoved = false;
                clearTimeout(pressTimer);
                pressTimer = setTimeout(() => {{
                    if (!pressMoved) {{
                        startDrag(el, e);
                    }}
                }}, LONG_PRESS_MS);
                window.addEventListener('pointermove', onWindowPointerMove);
                window.addEventListener('pointerup', onWindowPointerUp);
                window.addEventListener('pointercancel', onWindowPointerUp);
            }});
        }});
    }}

    function moveCardByKeyboard(el, key) {{
        const grid = document.getElementById('grid-view');
        const cards = Array.from(grid.querySelectorAll('.card'));
        const idx = cards.indexOf(el);
        if (idx === -1) return;

        // Il numero di colonne cambia con la larghezza dello schermo
        // (2 su telefono, 4 su schermi larghi): lo leggiamo dal CSS
        // effettivamente applicato invece di darlo per scontato, cosi'
        // "su"/"giu'" spostano sempre alla riga giusta.
        const columns = getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length || 1;

        let targetIdx = null;
        if (key === 'ArrowLeft') targetIdx = idx - 1;
        else if (key === 'ArrowRight') targetIdx = idx + 1;
        else if (key === 'ArrowUp') targetIdx = idx - columns;
        else if (key === 'ArrowDown') targetIdx = idx + columns;
        if (targetIdx === null || targetIdx < 0 || targetIdx >= cards.length) return;

        const a = el;
        const b = cards[targetIdx];
        const aNext = a.nextSibling;
        const bNext = b.nextSibling;
        if (aNext === b) {{
            grid.insertBefore(b, a);
        }} else if (bNext === a) {{
            grid.insertBefore(a, b);
        }} else {{
            grid.insertBefore(a, bNext);
            grid.insertBefore(b, aNext);
        }}

        syncOrderFromDom();
        reorderMode = true;
        showReorderActions();
        el.focus();
    }}

    function handleGlobalKeydown(e) {{
        const inDetail = document.getElementById('grid-view').style.display === 'none';
        if (inDetail) {{
            if (e.key === 'ArrowRight') {{
                e.preventDefault();
                showNext();
            }} else if (e.key === 'ArrowLeft') {{
                e.preventDefault();
                showPrev();
            }} else if (e.key === 'Escape') {{
                e.preventDefault();
                closeDetail();
            }}
            // Freccia su/giu': non le intercettiamo, cosi' restano libere
            // di far scorrere la pagina/l'immagine come richiesto.
            return;
        }}

        if (e.key === 'Escape') {{
            if (dragState || reorderMode) {{
                e.preventDefault();
                if (dragState) {{ endDrag(); }}
                exitReorderMode();
            }}
            return;
        }}

        if (e.key.indexOf('Arrow') === 0) {{
            const focused = document.activeElement;
            if (focused && focused.classList && focused.classList.contains('card')) {{
                e.preventDefault();
                moveCardByKeyboard(focused, e.key);
            }}
        }}
    }}

    function initReorder() {{
        document.querySelectorAll('.card[data-pid]').forEach(card => {{
            const panel = PANELS[Number(card.dataset.pid)];
            if (!panel) return;
            card.style.borderColor = panel.updated ? '#ffd641' : '#555555';
            card.style.backgroundColor = panel.updated ? '#fff7de' : '#e5e5e5';
            card.querySelector('.card-name').style.color = panel.updated ? '#111' : '#555555';
        }});
        loadSavedOrder();
        applyOrderToGrid();
        document.addEventListener('keydown', handleGlobalKeydown);
        attachDragHandlers();
    }}

    function renderDetail(i) {{
        const n = order.length;
        currentIndex = ((i % n) + n) % n;
        const p = PANELS[order[currentIndex]];

        document.getElementById('main-title').innerText = p.name;
        document.getElementById('main-updated').style.display = 'none';
        document.getElementById('main-signature').style.display = 'none';
        document.getElementById('nav-position').innerText = (currentIndex + 1) + '/' + n;

        const phoneLine = document.getElementById('phone-line');
        if (p.phone_tel) {{
            phoneLine.innerHTML = '<a href="tel:' + p.phone_tel + '" onclick="event.stopPropagation()">' + p.phone_display + '</a>';
            phoneLine.style.display = 'block';
        }} else {{
            phoneLine.innerHTML = '';
            phoneLine.style.display = 'none';
        }}

        const content = document.getElementById('detail-content');
        if (p.image) {{
            content.innerHTML = '<img src="' + p.image + '" alt="' + p.name + '">';
        }} else {{
            content.innerHTML = '<p class="error">' + (p.error || 'Menu non disponibile.') + '</p>';
        }}
    }}

    function openDetail(i) {{
        document.getElementById('grid-view').style.display = 'none';

        renderDetail(i);
        document.getElementById('detail-view').style.display = 'block';
        document.getElementById('nav-bar').style.display = 'flex';
        window.scrollTo(0, 0);

        if (!isAdmin) {{
            const p = PANELS[order[currentIndex]];
            fetchWithRetry(counterHitUrlFor(p.name), 3).catch(e => {{}});
        }}
    }}

    function showPrev() {{ renderDetail(currentIndex - 1); }}
    function showNext() {{ renderDetail(currentIndex + 1); }}

    function closeDetail() {{
        document.getElementById('detail-view').style.display = 'none';
        document.getElementById('phone-line').style.display = 'none';
        document.getElementById('nav-bar').style.display = 'none';
        document.getElementById('grid-view').style.display = 'grid';
        document.getElementById('main-updated').style.display = '';
        document.getElementById('main-signature').style.display = '';

        const mainTitle = document.getElementById('main-title');
        if (isAdmin) {{
            updateAdminTitle();
        }} else {{
            mainTitle.innerText = 'Rosticcerie';
        }}

        window.scrollTo(0, 0);
    }}

    async function forceFreshReload() {{
        // Svuota le cache gestite dalla pagina e apre un URL sempre nuovo.
        try {{
            if ('caches' in window) {{
                const cacheNames = await caches.keys();
                await Promise.all(cacheNames.map(name => caches.delete(name)));
            }}
        }} catch (e) {{
            console.warn('Cache non svuotabile', e);
        }}

        const freshUrl = new URL(window.location.href);
        freshUrl.searchParams.set('refresh', Date.now().toString());
        window.location.replace(freshUrl.toString());
    }}

    function attachRefreshHandlers() {{
        ['main-updated', 'main-signature'].forEach(id => {{
            const element = document.getElementById(id);
            if (!element) return;
            element.setAttribute('role', 'button');
            element.setAttribute('tabindex', '0');
            element.setAttribute('title', 'Aggiorna i dati');
            element.addEventListener('click', forceFreshReload);
            element.addEventListener('keydown', (event) => {{
                if (event.key === 'Enter' || event.key === ' ') {{
                    event.preventDefault();
                    forceFreshReload();
                }}
            }});
        }});
    }}

    function handleTitleClick() {{
        const inDetail = document.getElementById('grid-view').style.display === 'none';
        if (inDetail) {{
            const p = PANELS[order[currentIndex]];
            if (p && p.url) {{
                window.open(p.url, '_blank', 'noopener');
            }}
            return;
        }}
        if (isAdmin) {{
            if (confirm("Vuoi davvero azzerare il contatore? (Verra' azzerato per tutti i dispositivi)")) {{
                resetCounterGlobally();
            }}
        }} catch (e) {{
            console.warn('Cache non svuotabile', e);
        }}

        const freshUrl = new URL(window.location.href);
        freshUrl.searchParams.set('refresh', Date.now().toString());
        window.location.replace(freshUrl.toString());
    }}

    window.onload = loadCounter;
    document.addEventListener('DOMContentLoaded', () => {{
        initReorder();
        attachRefreshHandlers();
    }});
  </script>
</head>
<body>
  <header id="main-header">
    <h1 id="main-title" onclick="handleTitleClick()">Rosticcerie</h1>
    <div id="reorder-actions">
      <button type="button" id="reorder-reset-btn" onclick="resetOrderToDefault()">Reset</button>
      <button type="button" id="reorder-done-btn" onclick="exitReorderMode()">Fine</button>
    </div>
    <div id="phone-line"></div>
    <p id="main-updated" class="updated" onclick="forceFreshReload()">{html.escape(today_label)}</p>
    <p id="main-signature" class="signature" onclick="forceFreshReload()">by Mazzarisi</p>
  </header>

  <main id="grid-view">
    {"".join(cards)}
  </main>

  <div id="detail-view">
    <div id="detail-content" onclick="closeDetail()"></div>
  </div>

  <div id="nav-bar">
    <button type="button" onclick="showPrev()" aria-label="Rosticceria precedente">&#8592;</button>
    <span id="nav-position"></span>
    <button type="button" onclick="showNext()" aria-label="Rosticceria successiva">&#8594;</button>
  </div>
</body>
</html>
"""
    index_path = os.path.join(output_dir, "Rosticcerie.html")
    with open(index_path, "w", encoding="utf-8") as index_file:
        index_file.write(index_html)

    # "index.html" e' la pagina che iOS/i browser aprono per default quando si
    # salva l'URL della cartella (es. icona sulla schermata Home): la teniamo
    # identica a Rosticcerie.html per evitare che resti una versione vecchia.
    root_index_path = os.path.join(output_dir, "index.html")
    with open(root_index_path, "w", encoding="utf-8") as root_index_file:
        root_index_file.write(index_html)


def git_publish_if_available(output_dir: str) -> None:
    repo_dir = find_git_repository(output_dir)
    if not repo_dir:
        print("Cartella pubblicata localmente. GitHub non configurato in questa cartella.")
        return

    rel_output = os.path.relpath(output_dir, repo_dir)
    commands = [
        ["git", "add", rel_output],
        ["git", "commit", "-m", "Aggiorna foto rosticcerie"],
        ["git", "push"],
    ]

    for command in commands:
        result = subprocess.run(command, cwd=repo_dir, capture_output=True, text=True)
        if command[1] == "commit" and result.returncode != 0 and "nothing to commit" in result.stdout.lower():
            print("GitHub: nessuna modifica nuova da pubblicare.")
            return
        if result.returncode != 0:
            print(f"GitHub: comando non riuscito: {' '.join(command)}")
            print((result.stderr or result.stdout).strip())
            return

    print("GitHub: pubblicazione completata.")
