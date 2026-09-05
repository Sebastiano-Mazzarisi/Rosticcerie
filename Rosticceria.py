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
        "display_name": "Bollenti Piatti",
        "url": "https://www.facebook.com/BollentiPiatti",
        "required_terms": ["secondi piatti"],
    },
]
PANECO_PAGE = {
    "name": "Pane&Co",
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

    for _ in range(3):
        clicked = False
        try:
            before_text = post.inner_text(timeout=1000)
        except Exception:
            before_text = ""

        for selector in selectors:
            try:
                for element in post.locator(selector).all():
                    label = element.inner_text(timeout=700).strip()
                    lower_label = label.lower()
                    if "altro" not in lower_label and "see more" not in lower_label:
                        continue
                    if not element.is_visible(timeout=700):
                        continue
                    element.click(timeout=1500, force=True)
                    page.wait_for_timeout(900)
                    clicked = True
                    break
            except Exception:
                pass
            if clicked:
                break

        if not clicked:
            try:
                clicked = bool(
                    post.evaluate(
                        """post => {
                            const candidates = Array.from(post.querySelectorAll('div[role="button"], a, span, div'));
                            const matching = candidates
                                .map((candidate) => ({
                                    candidate,
                                    label: (candidate.innerText || candidate.textContent || '').trim()
                                }))
                                .filter((item) => /altro|mostra altro|see more/i.test(item.label))
                                .sort((a, b) => a.label.length - b.label.length);

                            for (const { candidate, label } of matching) {
                                if (!/altro|mostra altro|see more/i.test(label)) {
                                    continue;
                                }
                                let clickable = candidate.closest('[role="button"], a') || candidate;
                                for (let depth = 0; clickable && depth < 5; depth += 1) {
                                    try {
                                        clickable.click();
                                        return true;
                                    } catch (error) {
                                        clickable = clickable.parentElement;
                                    }
                                }
                            }
                            return false;
                        }"""
                    )
                )
                if clicked:
                    page.wait_for_timeout(900)
            except Exception:
                clicked = False

        if not clicked:
            return
        try:
            after_text = post.inner_text(timeout=1000)
        except Exception:
            after_text = ""
        if after_text and after_text != before_text and "Altro" not in after_text:
            return


def menu_date_line_from_text(text: str) -> str:
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not re.search(r"\bmenu\b|\bmenù\b", line, re.IGNORECASE):
            continue
        if infer_date_from_text(line):
            return line

    return ""


def best_text_from_post(post) -> str:
    try:
        full_text = clean_post_text(post.inner_text(timeout=3000))
        menu_date_line = menu_date_line_from_text(full_text)
        if menu_date_line:
            return menu_date_line
    except Exception:
        full_text = ""

    message_selectors = [
        'div[data-ad-preview="message"] span[dir="auto"]',
        'div[data-ad-preview="message"] div[dir="auto"]',
        'div[data-ad-comet-preview="message"] span[dir="auto"]',
        'div[data-ad-comet-preview="message"] div[dir="auto"]',
    ]

    for selector in message_selectors:
        try:
            text_parts = []
            for element in post.locator(selector).all():
                if element.is_visible(timeout=1000):
                    text_parts.append(element.inner_text(timeout=3000))
            text = clean_post_text("\n".join(text_parts))
            if text:
                menu_date_line = menu_date_line_from_text(text)
                if menu_date_line:
                    return menu_date_line
                return text
        except Exception:
            pass

    try:
        text_parts = []
        seen = set()
        for element in post.locator('div[dir="auto"], span[dir="auto"]').all():
            if not element.is_visible(timeout=500):
                continue
            text = element.inner_text(timeout=1000).strip()
            if text and text not in seen:
                seen.add(text)
                text_parts.append(text)
        text = clean_post_text("\n".join(text_parts))
        if text:
            menu_date_line = menu_date_line_from_text(text)
            if menu_date_line:
                return menu_date_line
            return text
    except Exception:
        pass

    return full_text


def best_published_time_from_post(post) -> str:
    selectors = [
        "time",
        "abbr",
        'a[aria-label]',
        'span[aria-label]',
        'a[href*="/posts/"]',
        'a[href*="story_fbid"]',
        'a[role="link"]',
        'span',
    ]

    candidates = []
    for selector in selectors:
        try:
            for element in post.locator(selector).all():
                # Nota: "href" e' escluso di proposito. I link ai permalink dei
                # post Facebook (es. /stories/.../?...__cft__[0]=...) sono
                # stringhe alfanumeriche lunghe che possono contenere per caso
                # sequenze tipo "23h" o lettere isolate come "h"/"g"/"d", e
                # venivano scambiate per un'etichetta di tempo relativa
                # (es. "23 ore fa"), producendo date completamente sbagliate.
                for attribute in ("title", "aria-label", "datetime"):
                    value = element.get_attribute(attribute)
                    if value:
                        candidates.append(value.strip())

                try:
                    text = element.inner_text(timeout=1000).strip()
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

    inferred = infer_date_from_text(value)
    if inferred:
        return inferred

    return value


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
        or bool(re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", value))
        or bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", value))
        or bool(re.search(r"\b\d{1,2}:\d{2}\b", value))
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


def find_first_post_image(page) -> Optional[Dict[str, str]]:
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
                    date_in_post_text = infer_date_from_text(post_text) or infer_date_from_text(full_post_text)
                    facebook_time = best_published_time_from_post(post)
                    normalized_facebook_time = normalize_facebook_time(facebook_time)
                    published_at_raw = facebook_time or date_in_post_text
                    published_at = normalized_facebook_time or date_in_post_text or rome_now().strftime("%d/%m/%Y")
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


def find_first_text_menu_post(page, required_terms: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
    post_selectors = [
        'div[role="article"]',
        "div[aria-posinset]",
    ]

    fallback_post = None
    truncated_fallback_post = None
    for selector in post_selectors:
        posts = page.locator(selector).all()
        for post in posts[:20]:
            expand_facebook_see_more(post, page)

            try:
                raw_text = post.inner_text(timeout=3000)
                truncated = has_see_more_marker(raw_text)
                full_text = clean_text_menu_post(raw_text)
            except Exception:
                continue

            post_text = full_text
            if not post_text:
                continue

            published_at = infer_date_from_text(post_text) or infer_date_from_text(raw_text)
            published_at_raw = published_at or best_published_time_from_post(post) or raw_text
            normalized_published_at = published_at or normalize_facebook_time(published_at_raw) or normalize_facebook_time(raw_text)
            print(
                "DEBUG data menu: published_at=" + repr(published_at)
                + " published_at_raw=" + repr(published_at_raw[:80])
                + " normalized_published_at=" + repr(normalized_published_at)
            )
            candidate = {
                "text": post_text,
                "published_at": normalized_published_at,
                "published_at_raw": published_at_raw,
            }

            if truncated:
                # Non siamo riusciti a espandere "Altro" (tipico senza un
                # login valido): meglio un menu incompleto che nessun menu,
                # ma solo come ultima riserva se non troviamo di meglio.
                if truncated_fallback_post is None and len(post_text) > 20:
                    truncated_fallback_post = candidate
                continue

            lower_text = post_text.lower()
            has_required_terms = all(term.lower() in lower_text for term in (required_terms or []))
            if has_required_terms and ("menu" in lower_text or "menù" in lower_text) and normalized_published_at:
                return candidate

            if fallback_post is None and len(post_text) > 20:
                fallback_post = candidate

        if fallback_post:
            return fallback_post

    return fallback_post or truncated_fallback_post


def find_largest_visible_image_url(page) -> str:
    best_url = ""
    best_score = 0

    for image in page.locator("img").all():
        score = image_score(image)
        if score > best_score:
            src = image.get_attribute("src") or ""
            if src.startswith("http"):
                best_url = src
                best_score = score

    return best_url


def cookies_look_authenticated(cookies: List[Dict]) -> bool:
    names = {cookie.get("name", "") for cookie in cookies}
    return bool(names & FACEBOOK_LOGIN_COOKIE_NAMES)


def extract_first_facebook_image(facebook_url: str, prefer_active_closure: bool = False) -> Dict[str, str]:
    cookie_path = os.path.join(script_dir(), COOKIE_FILE)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1366, "height": 2400},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )

            cookies = load_facebook_cookies(cookie_path)
            if cookies:
                context.add_cookies(cookies)
            if not cookies_look_authenticated(cookies):
                print(
                    f"ATTENZIONE: {cookie_path} non contiene un login Facebook valido "
                    "(mancano i cookie 'c_user'/'xs'). Verrà usata una sessione anonima."
                )

            page = context.new_page()
            page.goto(facebook_url, wait_until="domcontentloaded", timeout=60000)

            try:
                page.get_by_role("button", name="Consenti tutti i cookie").click(timeout=3000)
            except PlaywrightTimeoutError:
                pass
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
                post = find_first_post_image(page)
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


def extract_first_facebook_text_menu(page_config: Dict[str, str]) -> Dict[str, str]:
    cookie_path = os.path.join(script_dir(), COOKIE_FILE)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1366, "height": 2400},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )

            cookies = load_facebook_cookies(cookie_path)
            if cookies:
                context.add_cookies(cookies)
            if not cookies_look_authenticated(cookies):
                print(
                    f"ATTENZIONE: {cookie_path} non contiene un login Facebook valido."
                )

            page = context.new_page()
            response = page.goto(page_config["url"], wait_until="domcontentloaded", timeout=60000)
            print("HTTP status:", response.status if response else "nessuna response")
            print("URL response:", response.url if response else "nessuna response")
            print("User-Agent:", page.evaluate("navigator.userAgent"))

            try:
                consent_pattern = re.compile(
                    r"(Consenti tutti i cookie|Allow all cookies|Accept all|Allow all)",
                    re.IGNORECASE,
                )
                page.get_by_role("button", name=consent_pattern).click(timeout=3000)
            except PlaywrightTimeoutError:
                pass
            except Exception:
                pass

            page.wait_for_timeout(5000)
            for _ in range(4):
                post = find_first_text_menu_post(page, page_config.get("required_terms"))
                if post:
                    text = post.get("text", "")
                    image_bytes = render_text_menu_image(
                        page_config.get("display_name", page_config["name"]),
                        text,
                        post.get("published_at", ""),
                    )
                    return {
                        "name": page_config["name"],
                        "image_bytes": image_bytes,
                        "text": text,
                        "published_at": post.get("published_at", ""),
                        "published_at_raw": post.get("published_at_raw", ""),
                    }
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(2000)

            # Diagnostica: stampa nei log un'analisi testuale della pagina
            # (vedi dump_debug_facebook) e salva anche uno screenshot/HTML
            # completo come artefatto, utile per un'ispezione visiva se il
            # log testuale non bastasse a capire il problema.
            dump_debug_facebook(page, page_config.get("display_name", page_config["name"]))
            try:
                debug_name = safe_file_name(page_config["name"])
                page.screenshot(path=os.path.join(script_dir(), f"error_{debug_name}.png"), full_page=True)
                with open(os.path.join(script_dir(), f"error_{debug_name}.html"), "w", encoding="utf-8") as debug_file:
                    debug_file.write(page.content())
                print(f"Diagnostica salvata: error_{debug_name}.png e error_{debug_name}.html")
            except Exception as debug_exc:
                print(f"Errore durante il salvataggio della diagnostica: {debug_exc}")

            raise RuntimeError(f"Non ho trovato nessun post testuale del menu nella pagina Facebook: {page_config['url']}")
        finally:
            browser.close()


def extract_paneeco_menu() -> Dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": 1366, "height": 2200},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )
            page.goto(PANECO_PAGE["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)

            data = page.evaluate(
                """() => {
                    const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                    const date = normalize(document.querySelector('.menu-header__title')?.textContent);
                    const categories = Array.from(document.querySelectorAll('.menu-category')).map((section) => {
                        const title = normalize(section.querySelector('.menu-category__title')?.textContent);
                        const description = normalize(section.querySelector('.menu-category__description')?.textContent);
                        const items = Array.from(section.querySelectorAll('.menu-item')).map((item) => ({
                            name: normalize(item.querySelector('.menu-item__name')?.textContent),
                            price: normalize(item.querySelector('.menu-item__price')?.textContent),
                            description: normalize(item.querySelector('.menu-item__description')?.textContent)
                        })).filter((item) => item.name);
                        return { title, description, items };
                    }).filter((category) => category.title);
                    return { date, categories };
                }"""
            )
        finally:
            browser.close()

    wanted_titles = {
        "primi piatti del giorno",
        "secondi piatti del giorno",
    }
    categories = [
        category
        for category in data.get("categories", [])
        if category.get("title", "").strip().lower() in wanted_titles
    ]

    if not categories:
        raise RuntimeError("Non ho trovato Primi del giorno e Secondi del giorno su Pane&Co.")

    published_at = normalize_paneeco_date(data.get("date", ""))
    menu_text = paneeco_text(data.get("date", ""), categories)
    image_bytes = render_paneeco_image(format_menu_date(published_at), categories)
    # Aggiunge sotto l'immagine la stessa fascia bianca con la data usata per
    # tutte le altre rosticcerie, cosi' anche Pane&Co la mostra "sotto la
    # foto" e non solo nell'intestazione della card.
    image_bytes = add_date_footer(image_bytes, published_at)

    return {
        "name": PANECO_PAGE["name"],
        "image_bytes": image_bytes,
        "text": menu_text,
        "published_at": published_at,
        "published_at_raw": data.get("date", ""),
    }


def normalize_paneeco_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    match = re.search(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)", value, re.IGNORECASE)
    if not match:
        return value

    month = ITALIAN_MONTHS.get(match.group(2).lower())
    if not month:
        return value

    year = rome_now().year
    return f"{int(match.group(1)):02d}/{month:02d}/{year}"


def paneeco_text(date_label: str, categories: List[Dict]) -> str:
    lines = []
    if date_label:
        lines.append(f"Menu {date_label}")
        lines.append("")

    for category in categories:
        lines.append(category["title"].upper())
        for item in category.get("items", []):
            price = f" - {item['price']}" if item.get("price") else ""
            lines.append(f"- {item['name']}{price}")
            if item.get("description"):
                lines.append(f"  {item['description']}")
        lines.append("")

    return "\n".join(lines).strip()


def load_font(size: int, bold: bool = False):
    candidates = []
    if os.name == "nt":
        candidates.extend(
            [
                os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arialbd.ttf" if bold else "arial.ttf"),
                os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "segoeuib.ttf" if bold else "segoeui.ttf"),
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )

    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)

    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> List[str]:
    words = text.split()
    if not words:
        return []

    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_text_menu_image(title: str, text: str, published_at: str = "") -> bytes:
    width = 1080
    margin = 58
    cream = (255, 252, 243)
    paper = (255, 255, 255)
    ink = (18, 18, 18)
    muted = (90, 90, 90)
    line_color = (226, 226, 226)

    title_font = load_font(52, bold=True)
    date_font = load_font(30)
    body_font = load_font(31)
    section_font = load_font(31, bold=True)

    clean_text = clean_post_text(text)
    body_lines = []
    probe = Image.new("RGB", (width, 200), cream)
    draw = ImageDraw.Draw(probe)
    text_width = width - (margin * 2) - 48

    for raw_line in clean_text.splitlines():
        line = raw_line.strip()
        if not line:
            body_lines.append({"text": "", "section": False})
            continue
        is_section = line.upper() in {"PRIMI PIATTI", "SECONDI PIATTI"}
        wrapped = wrap_text(draw, line, section_font if is_section else body_font, text_width)
        for wrapped_line in wrapped:
            body_lines.append({"text": wrapped_line, "section": is_section})

    if not body_lines:
        body_lines = [{"text": "Menu non disponibile", "section": False}]

    line_height = 43
    section_height = 54
    content_height = sum(section_height if line["section"] else line_height if line["text"] else 24 for line in body_lines)
    height = margin + 66 + 34 + content_height + margin + 70
    image = Image.new("RGB", (width, max(height, 900)), cream)
    draw = ImageDraw.Draw(image)

    y = margin
    draw.text((margin, y), title, fill=ink, font=title_font)
    y += 64

    display_date = format_menu_date(published_at or infer_date_from_text(clean_text))
    if display_date:
        draw.text((margin + 10, y), display_date, fill=muted, font=date_font)
        y += 52

    card_top = y
    card_bottom = y + content_height + 76
    draw.rounded_rectangle((margin, card_top, width - margin, card_bottom), radius=14, fill=paper, outline=line_color, width=2)
    y += 22

    for line_data in body_lines:
        line = line_data["text"]
        if not line:
            y += 24
            continue
        if line_data["section"]:
            section_bottom = y + 45
            draw.rounded_rectangle((margin + 18, y - 4, width - margin - 18, section_bottom), radius=12, fill=(255, 214, 65))
            draw.text((margin + 36, y + 6), line, fill=ink, font=section_font)
            y += section_height
            continue
        draw.text((margin + 24, y), line, fill=ink, font=body_font)
        y += line_height

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def render_paneeco_image(date_label: str, categories: List[Dict]) -> bytes:
    width = 1080
    margin = 54
    yellow = (255, 214, 65)
    cream = (255, 252, 243)
    ink = (16, 16, 16)
    muted = (92, 92, 92)
    border = (229, 229, 229)

    title_font = load_font(48, bold=True)
    date_font = load_font(30)
    section_font = load_font(30, bold=True)
    item_font = load_font(28, bold=True)
    desc_font = load_font(23)
    price_font = load_font(27, bold=True)

    probe = Image.new("RGB", (width, 200), cream)
    draw = ImageDraw.Draw(probe)

    row_data = []
    height = margin
    height += 66
    if date_label:
        height += 45
    height += 28

    for category in categories:
        section_height = 74
        if category.get("description"):
            section_height += 34
        height += section_height
        for item in category.get("items", []):
            item_lines = wrap_text(draw, item["name"], item_font, width - (margin * 2) - 170)
            desc_lines = wrap_text(draw, item.get("description", ""), desc_font, width - (margin * 2) - 30)
            row_height = 38 * max(1, len(item_lines)) + 28 * len(desc_lines) + 30
            row_data.append((item, item_lines, desc_lines, row_height))
            height += row_height
        height += 28

    image = Image.new("RGB", (width, height + margin), cream)
    draw = ImageDraw.Draw(image)

    y = margin
    draw.text((margin, y), "Pane&Co", fill=ink, font=title_font)
    y += 64
    if date_label:
        draw.text((margin, y), date_label, fill=muted, font=date_font)
        y += 48
    y += 12

    row_index = 0
    for category in categories:
        section_top = y
        section_height = 74 + (34 if category.get("description") else 0)
        draw.rounded_rectangle((margin, section_top, width - margin, section_top + section_height), radius=18, fill=yellow)
        draw.text((margin + 28, section_top + 20), category["title"].upper(), fill=ink, font=section_font)
        if category.get("description"):
            draw.text((margin + 28, section_top + 57), category["description"], fill=ink, font=desc_font)
        y += section_height

        for item in category.get("items", []):
            item, item_lines, desc_lines, row_height = row_data[row_index]
            row_index += 1
            draw.rectangle((margin, y, width - margin, y + row_height), fill=(255, 255, 255))
            draw.line((margin, y, width - margin, y), fill=border, width=2)

            text_y = y + 18
            for line in item_lines:
                draw.text((margin + 28, text_y), line, fill=ink, font=item_font)
                text_y += 38

            if item.get("price"):
                price_bbox = draw.textbbox((0, 0), item["price"], font=price_font)
                draw.text((width - margin - 28 - (price_bbox[2] - price_bbox[0]), y + 20), item["price"], fill=ink, font=price_font)

            for line in desc_lines:
                draw.text((margin + 28, text_y), line, fill=muted, font=desc_font)
                text_y += 28

            y += row_height

        y += 28

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def download_image(image_url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.content


def crop_fantasia_chalkboard(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    if width < 100 or height < 100:
        return image_bytes

    x_start = int(width * 0.08)
    x_end = int(width * 0.92)
    step = max(1, (x_end - x_start) // 180)
    dark_rows = []

    for y in range(height):
        total = 0
        dark = 0
        for x in range(x_start, x_end, step):
            r, g, b = image.getpixel((x, y))
            if r < 105 and g < 105 and b < 105:
                dark += 1
            total += 1
        if total and dark / total >= 0.55:
            dark_rows.append(y)

    if not dark_rows:
        return image_bytes

    top = max(0, min(dark_rows) - 45)
    bottom = min(height, max(dark_rows) + 36)
    if bottom - top < height * 0.45 or bottom - top > height * 0.95:
        return image_bytes

    output = io.BytesIO()
    image.crop((0, top, width, bottom)).save(output, format="JPEG", quality=92)
    return output.getvalue()


def add_date_footer(image_bytes: bytes, published_at: str) -> bytes:
    """Aggiunge sotto la foto una fascia bianca con la data del menu,
    allungando l'immagine invece di sovrapporsi al contenuto: utile quando
    la lavagna fotografata non riporta la data. La scritta viene
    dimensionata in proporzione alla larghezza della foto (circa il 70%
    della larghezza), cosi' resta leggibile sia sulle foto piccole sia su
    quelle molto grandi (es. l'avviso ferie di Michela)."""
    date_text = format_menu_date(published_at)
    if not date_text:
        return image_bytes

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    # Calcoliamo il font in modo che il testo della data occupi circa il
    # 70% della larghezza della foto, invece di dipendere solo
    # dall'altezza: su una foto molto grande (es. l'avviso ferie di
    # Michela) la scritta risultava troppo piccola rispetto al disegno.
    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)
    target_text_width = width * 0.70
    probe_size = 100
    probe_font = _load_bold_font(probe_size)
    probe_bbox = probe_draw.textbbox((0, 0), date_text, font=probe_font)
    probe_width = probe_bbox[2] - probe_bbox[0]
    if probe_width > 0:
        font_size = max(24, int(probe_size * target_text_width / probe_width))
    else:
        font_size = max(24, height // 14)
    font = _load_bold_font(font_size)
    bar_height = max(48, int(font_size / 0.45))

    # Stesso giallo usato nelle card di Pane&Co (255, 214, 65), cosi' la
    # fascia con la data ha lo stesso stile in tutte le rosticcerie.
    canvas = Image.new("RGB", (width, height + bar_height), (255, 214, 65))
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    # Cornice grigia attorno alla fascia gialla, per staccarla dalla foto.
    draw.rectangle(
        (0, height, width - 1, height + bar_height - 1),
        outline=(120, 120, 120),
        width=3,
    )
    bbox = draw.textbbox((0, 0), date_text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) / 2 - bbox[0]
    y = height + (bar_height - text_h) / 2 - bbox[1]
    draw.text((x, y), date_text, fill=(16, 16, 16), font=font)
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92)
    return output.getvalue()


def add_white_border(image_bytes: bytes, border: int = 10) -> bytes:
    """Aggiunge un bordo bianco attorno alla foto del menu."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    canvas = Image.new("RGB", (width + border * 2, height + border * 2), (255, 255, 255))
    canvas.paste(image, (border, border))
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92)
    return output.getvalue()


def _widest_dark_column_run(image: Image.Image) -> Optional[Tuple[int, int]]:
    """Individua il blocco contiguo di colonne scure piu' ampio nell'immagine
    (tipicamente la lavagna). Restituisce (inizio, fine) oppure None se non
    trova nulla di sufficientemente scuro."""
    width, height = image.size
    y_start = int(height * 0.1)
    y_end = int(height * 0.9)
    step = max(1, (y_end - y_start) // 300)

    is_dark_col = []
    for x in range(width):
        dark_pixels = 0
        total_pixels = 0
        for y in range(y_start, y_end, step):
            r, g, b = image.getpixel((x, y))
            if (r + g + b) / 3 < 130:
                dark_pixels += 1
            total_pixels += 1
        is_dark_col.append(total_pixels > 0 and (dark_pixels / total_pixels) >= 0.45)

    # Riempie piccoli buchi (rumore) tra colonne scure per unire un blocco continuo
    max_gap = max(5, width // 100)
    filled = list(is_dark_col)
    x = 0
    while x < width:
        if not filled[x]:
            gap_start = x
            while x < width and not filled[x]:
                x += 1
            gap_len = x - gap_start
            if gap_start > 0 and x < width and gap_len <= max_gap:
                for gx in range(gap_start, x):
                    filled[gx] = True
        else:
            x += 1

    # Individua il blocco contiguo di colonne scure più lungo: è la lavagna.
    # (Ignora così macchie scure isolate altrove nella foto, come finestre o ombre,
    # che in precedenza allargavano il ritaglio ben oltre i bordi reali della lavagna.)
    best_start = None
    best_end = None
    best_len = 0
    run_start = None
    for x in range(width):
        if filled[x]:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None and x - run_start > best_len:
                best_len = x - run_start
                best_start, best_end = run_start, x
            run_start = None
    if run_start is not None and width - run_start > best_len:
        best_start, best_end = run_start, width
        best_len = width - run_start

    if best_start is None:
        return None
    return best_start, best_end


CLOSURE_NOTICE_PATTERN = re.compile(
    r"\bchius[oi]\b|\bchiusura\b|\briapr\w*\b|\bferie\b|\bresteremo\s+chius\w*\b"
    r"|\bsaremo\s+chius\w*\b",
    re.IGNORECASE,
)


def looks_like_closure_notice(text: str) -> bool:
    """Riconosce un post/cartello che avvisa di una chiusura per ferie o
    simili (es. "chiusi da venerdì a lunedì", "riapriamo martedì"), cosi'
    da poter evitare di trattarlo come una normale lavagna del menu del
    giorno."""
    return bool(CLOSURE_NOTICE_PATTERN.search(text or ""))


def clean_facebook_alt_text(alt: str) -> str:
    """Ripulisce il testo alternativo generato automaticamente da Facebook
    per un'immagine, estraendo la frase citata quando presente (es.
    "L'immagine può contenere: testo che dice 'AVVISIAMO...'") e scartando
    le descrizioni generiche prive di informazioni utili."""
    alt = (alt or "").strip()
    if not alt:
        return ""
    match = re.search(
        r"(?:testo che dice|text that says|raffigurante il seguente testo)"
        r"\s*[:\s]*[\"'“](.+?)[\"'”]",
        alt,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    if re.search(
        r"nessuna descrizione|may be an image|image may contain|no photo description",
        alt,
        re.IGNORECASE,
    ):
        return ""
    return alt


def parse_closure_date_range(text: str, reference_date: datetime.date):
    """Cerca nel testo un intervallo del tipo "da venerdi' 4 (settembre) a
    lunedi' 7 settembre" e restituisce (data_inizio, data_fine), usando
    l'anno della data di riferimento. Restituisce None se non trova un
    intervallo valido o riconoscibile."""
    if not text:
        return None
    lower = text.lower()
    month_pattern = "|".join(ITALIAN_MONTHS.keys())
    match = re.search(
        rf"da\s+(?:\w+\s+)?(\d{{1,2}})(?:\s+({month_pattern}))?\s+a\s+"
        rf"(?:\w+\s+)?(\d{{1,2}})\s+({month_pattern})",
        lower,
    )
    if not match:
        return None

    start_day = int(match.group(1))
    start_month_name = match.group(2)
    end_day = int(match.group(3))
    end_month_name = match.group(4)
    end_month = ITALIAN_MONTHS.get(end_month_name)
    start_month = ITALIAN_MONTHS.get(start_month_name) if start_month_name else end_month
    if not start_month or not end_month:
        return None

    year = reference_date.year
    try:
        start_date = datetime.date(year, start_month, start_day)
        end_date = datetime.date(year, end_month, end_day)
    except ValueError:
        return None
    if end_date < start_date:
        # L'intervallo attraversa il cambio di anno (es. dicembre -> gennaio).
        end_date = datetime.date(year + 1, end_month, end_day)
    return start_date, end_date


def build_photos_tab_url(facebook_url: str) -> str:
    """Costruisce l'URL della scheda "Foto" di una pagina Facebook."""
    if "sk=photos" in facebook_url:
        return facebook_url
    separator = "&" if "?" in facebook_url else "?"
    return f"{facebook_url}{separator}sk=photos"


def find_active_closure_post_via_photos(context, facebook_url: str):
    """Scandisce la scheda "Foto" della pagina (consultabile anche senza
    login, a differenza del feed principale) alla ricerca di un avviso di
    chiusura per ferie ancora valido oggi, anche se nel frattempo e' stato
    pubblicato un post piu' recente (es. il menu del giorno di un giorno
    prima dell'inizio della chiusura). Si basa sul testo alternativo che
    Facebook genera automaticamente per ogni foto, che include spesso il
    testo scritto su un cartello fotografato. Restituisce None se non trova
    nulla di pertinente, cosi' che il chiamante possa proseguire con
    l'estrazione normale."""
    today = rome_now().date()
    try:
        photos_page = context.new_page()
    except Exception:
        return None

    try:
        photos_page.goto(build_photos_tab_url(facebook_url), wait_until="domcontentloaded", timeout=60000)
        photos_page.wait_for_timeout(3500)
        try:
            photos_page.get_by_role("button", name="Consenti tutti i cookie").click(timeout=3000)
        except Exception:
            pass

        try:
            anchors = photos_page.locator('a[href*="/photo"]').all()
        except Exception:
            anchors = []

        for anchor in anchors[:15]:
            try:
                image = anchor.locator("img").first
                alt_text = (image.get_attribute("alt") or "").strip()
            except Exception:
                continue
            if not alt_text or not looks_like_closure_notice(alt_text):
                continue
            date_range = parse_closure_date_range(alt_text, today)
            if not date_range or not (date_range[0] <= today <= date_range[1]):
                continue

            try:
                href = anchor.get_attribute("href") or ""
            except Exception:
                href = ""
            try:
                image_url = image.get_attribute("src") or ""
            except Exception:
                image_url = ""

            published_at = ""
            published_at_raw = ""

            if href:
                # Nota importante: NON apriamo la foto con una navigazione a
                # se stante (context.new_page().goto(href)) verso l'URL
                # /photo.php. In ambiente headless/anonimo (GitHub Actions)
                # una richiesta "a freddo" di quel tipo viene rediretta da
                # Facebook alla pagina di login, mentre la stessa richiesta
                # fatta da un browser interattivo normale funziona senza
                # problemi: e' un blocco anti-bot legato al modo in cui la
                # pagina viene raggiunta, non al contenuto in se'. Simuliamo
                # invece il comportamento di un utente reale: clicchiamo la
                # foto direttamente nella griglia "Foto" gia' caricata, cosi'
                # Facebook la apre nel proprio visualizzatore integrato
                # (aggiornamento lato client della stessa pagina, senza un
                # nuovo caricamento completo) e non scatta il redirect al
                # login.
                try:
                    url_before_click = photos_page.url
                    anchor.click(timeout=5000)
                    photos_page.wait_for_timeout(2500)
                    print("DEBUG Michela: url prima del click=" + repr(url_before_click))
                    print("DEBUG Michela: url dopo il click=" + repr(photos_page.url))

                    try:
                        og_image_url = (
                            photos_page.locator('meta[property="og:image"]')
                            .first.get_attribute("content", timeout=2000)
                            or ""
                        )
                    except Exception:
                        og_image_url = ""
                    print("DEBUG Michela: og_image_url=" + repr(og_image_url))
                    if og_image_url:
                        image_url = og_image_url
                    else:
                        for debug_attempt in range(6):
                            larger_image_url = find_largest_visible_image_url(photos_page)
                            print(
                                "DEBUG Michela: tentativo " + str(debug_attempt)
                                + " larger_image_url=" + repr(larger_image_url)
                            )
                            if larger_image_url:
                                image_url = larger_image_url
                                break
                            photos_page.wait_for_timeout(1000)

                    print("DEBUG Michela: image_url finale scelto=" + repr(image_url))

                    # Data di pubblicazione reale dell'avviso (non la data
                    # odierna): cerchiamo un'etichetta di tempo nel
                    # visualizzatore appena aperto, come gia' si fa per i
                    # post di testo normali.
                    raw_time = ""
                    for _ in range(4):
                        try:
                            raw_time = best_published_time_from_post(photos_page.locator("body"))
                        except Exception:
                            raw_time = ""
                        if raw_time:
                            break
                        photos_page.wait_for_timeout(800)
                    print("DEBUG Michela: raw_time=" + repr(raw_time))
                    if raw_time:
                        published_at_raw = raw_time
                        published_at = normalize_facebook_time(raw_time)

                    # Richiudiamo il visualizzatore prima di eventualmente
                    # proseguire con le altre foto della griglia.
                    try:
                        photos_page.keyboard.press("Escape")
                        photos_page.wait_for_timeout(500)
                    except Exception:
                        pass
                except Exception as click_exc:
                    print("DEBUG Michela: eccezione nel blocco click: " + repr(click_exc))

            if not image_url:
                continue

            if not published_at:
                # Ultima risorsa, solo se non troviamo alcuna data reale.
                published_at = rome_now().strftime("%d/%m/%Y circa")

            caption = clean_facebook_alt_text(alt_text) or alt_text
            return {
                "image_url": image_url,
                "photo_url": href,
                "text": caption,
                "image_alt": alt_text,
                "published_at": published_at,
                "published_at_raw": published_at_raw,
            }
    except Exception:
        pass
    finally:
        try:
            photos_page.close()
        except Exception:
            pass

    return None


def crop_michela_chalkboard(image_bytes: bytes) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    if width < 100 or height < 100:
        return image_bytes

    bounds = _widest_dark_column_run(image)
    if bounds is None:
        return image_bytes
    best_start, best_end = bounds
    best_len = best_end - best_start
    if best_len < max(width * 0.15, 150) or best_len >= width * 0.85:
        # Se il blocco scuro rilevato e' troppo stretto per essere una vera
        # lavagna leggibile (o copre gia' quasi tutta la foto), meglio
        # tenere la foto intera piuttosto che un ritaglio inutile o illeggibile.
        return image_bytes

    margin = 25
    left = max(0, best_start - margin)
    right = min(width, best_end + margin)
    cropped = image.crop((left, 0, right, height))

    # Rifinitura: sul ritaglio appena ottenuto puo' restare ancora del muro o
    # un infisso scuro vicino alla lavagna (es. una porta), che il primo
    # passaggio include per via del margine. Rilancia la stessa rilevazione
    # su questo ritaglio piu' piccolo: se individua un blocco scuro
    # chiaramente piu' stretto e ben centrato, restringe ulteriormente,
    # eliminando i bordi inutili rimasti ai lati.
    cropped_width = cropped.size[0]
    refine_bounds = _widest_dark_column_run(cropped)
    if refine_bounds is not None:
        r_start, r_end = refine_bounds
        r_len = r_end - r_start
        if max(cropped_width * 0.15, 150) <= r_len < cropped_width * 0.85:
            r_left = max(0, r_start - margin)
            r_right = min(cropped_width, r_end + margin)
            cropped = cropped.crop((r_left, 0, r_right, height))

    output = io.BytesIO()
    cropped.save(output, format="JPEG", quality=92)
    trimmed_bytes = output.getvalue()

    # Applica poi lo stesso ritaglio verticale usato per Fantasia.
    return crop_fantasia_chalkboard(trimmed_bytes)


def save_image(image_bytes: bytes, filename: str) -> str:
    image_path = os.path.join(script_dir(), filename)
    with open(image_path, "wb") as image_file:
        image_file.write(image_bytes)
    return image_path


def publish_dir() -> str:
    path = os.path.join(script_dir(), PUBLISH_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def safe_file_name(name: str) -> str:
    replacements = {
        "ì": "i",
        "Ì": "I",
        "à": "a",
        "è": "e",
        "é": "e",
        "ò": "o",
        "ù": "u",
    }
    for source, target in replacements.items():
        name = name.replace(source, target)
    return "".join(char if char.isalnum() else "_" for char in name).strip("_")


def parse_status_date(value: str) -> Optional[datetime.date]:
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value or "")
    if not match:
        return None

    try:
        return datetime.date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def infer_date_from_text(text: str) -> str:
    text = text or ""

    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if match:
        year = int(match.group(3))
        if year < 100:
            year += 2000

        try:
            return datetime.date(year, int(match.group(2)), int(match.group(1))).strftime("%d/%m/%Y")
        except ValueError:
            pass

    # Fallback
    month_pattern = "|".join(ITALIAN_MONTHS.keys())
    match = re.search(
        rf"(\d{{1,2}})\s+({month_pattern})(?:\s+(\d{{4}}))?",
        text,
        re.IGNORECASE,
    )
    if match:
        day = int(match.group(1))
        month = ITALIAN_MONTHS.get(match.group(2).lower())
        year = int(match.group(3)) if match.group(3) else rome_now().year
        if month:
            try:
                return datetime.date(year, month, day).strftime("%d/%m/%Y")
            except ValueError:
                return ""

    return ""


def panel_published_at(panel: Dict) -> str:
    return panel.get("published_at") or infer_date_from_text(panel.get("text", ""))


def existing_publish_panel_if_today(name: str, require_today: bool = True) -> Optional[Dict]:
    output_dir = publish_dir()
    status_path = os.path.join(output_dir, "status.json")
    if not os.path.exists(status_path):
        return None

    try:
        with open(status_path, "r", encoding="utf-8") as status_file:
            status = json.load(status_file)
    except Exception:
        return None

    for page_status in status.get("pages", []):
        if page_status.get("name") != name:
            continue
        published_at = page_status.get("published_at", "") or infer_date_from_text(page_status.get("text", ""))
        if require_today and parse_status_date(published_at) != rome_now().date():
            return None

        image_name = page_status.get("image") or f"{safe_file_name(name)}.jpg"
        image_path = os.path.join(output_dir, image_name)
        if not os.path.exists(image_path):
            return None

        text_name = page_status.get("publish_text") or f"{safe_file_name(name)}.txt"
        text_path = os.path.join(output_dir, text_name)
        text = page_status.get("text", "")
        if os.path.exists(text_path):
            try:
                with open(text_path, "r", encoding="utf-8") as text_file:
                    text = text_file.read()
            except Exception:
                pass

        if not text.strip():
            # Voce salvata senza testo valido: non riproporla all'infinito.
            return None

        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()

        return {
            "name": name,
            "image_bytes": image_bytes,
            "text": text,
            "published_at": published_at,
            "published_at_raw": page_status.get("published_at_raw", ""),
            "publish_image": image_name,
            "publish_text": text_name,
            "reused": True,
        }

    return None


def save_publish_files(panels: List[Dict]) -> str:
    output_dir = publish_dir()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")

    for panel in panels:
        if "error" in panel:
            continue

        base_name = safe_file_name(panel["name"])
        latest_name = f"{base_name}.jpg"
        archive_name = f"{base_name}_{timestamp}.jpg"
        panel["publish_image"] = panel.get("publish_image") or latest_name
        panel["publish_text"] = panel.get("publish_text") or f"{base_name}.txt"

        if panel.get("reused"):
            continue

        for filename in (latest_name, archive_name):
            path = os.path.join(output_dir, filename)
            with open(path, "wb") as image_file:
                image_file.write(panel["image_bytes"])

        text_path = os.path.join(output_dir, f"{base_name}.txt")
        with open(text_path, "w", encoding="utf-8") as text_file:
            text_file.write(panel.get("text", ""))

        panel["publish_image"] = latest_name
        panel["publish_text"] = f"{base_name}.txt"

    write_publish_index(panels, output_dir)
    write_publish_status(panels, output_dir)
    return output_dir


def write_publish_status(panels: List[Dict], output_dir: str) -> None:
    status = {
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pages": [
            {
                "name": panel["name"],
                "image": panel.get("publish_image"),
                "text": panel.get("text", ""),
                "published_at": panel_published_at(panel),
                "published_at_raw": panel.get("published_at_raw", ""),
                "error": panel.get("error"),
            }
            for panel in panels
        ],
    }
    status_path = os.path.join(output_dir, "status.json")
    with open(status_path, "w", encoding="utf-8") as status_file:
        json.dump(status, status_file, ensure_ascii=False, indent=2)


def _load_bold_font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def add_phone_overlay(image_bytes: bytes, phone_number: str) -> bytes:
    """Disegna il numero di telefono direttamente sull'immagine (fascia in
    basso, verde brillante) cosi' l'informazione resta dentro l'immagine
    invece che come testo HTML separato."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    width, height = image.size
    bar_height = max(56, height // 10)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle([0, height - bar_height, width, height], fill=(0, 0, 0, 190))
    font = _load_bold_font(int(bar_height * 0.5))
    bbox = draw.textbbox((0, 0), phone_number, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) / 2 - bbox[0]
    y = height - bar_height + (bar_height - text_h) / 2 - bbox[1]
    draw.text((x, y), phone_number, fill=(0, 200, 83, 255), font=font)
    combined = Image.alpha_composite(image, overlay).convert("RGB")
    output = io.BytesIO()
    combined.save(output, format="JPEG", quality=90)
    return output.getvalue()


def write_publish_index(panels: List[Dict], output_dir: str) -> None:
    today_label = italian_long_date(rome_now().date())
    phone_numbers = {
        "Fantasia": "080-405.41.39",
        "Cibària": "080-645.07.99",
        "Impastamò": "392-536.15.36",
        "Le delizie di Michela": "080-521.22.33",
        "Santoro (Castellana)": "080-859.83.13",
        "Pane&Co": "080-405.49.00",
        "Bollenti piatti": "334-318.58.44",
    }
    today = rome_now().date()
    panels_data = []

    for panel in panels:
        name = panel["name"]
        phone_number = phone_numbers.get(name, "")
        phone_tel = re.sub(r"[^0-9+]", "", phone_number) if phone_number else ""
        error = panel.get("error")

        image_url = ""
        is_updated = False
        if error:
            error = str(error)
        else:
            image_name = panel.get("publish_image", "")
            if image_name:
                image_url = f"{html.escape(image_name)}?v={int(time.time())}"
            published_at = panel_published_at(panel)
            is_updated = parse_status_date(published_at) == today

        panels_data.append({
            "name": name,
            "phone_display": phone_number,
            "phone_tel": phone_tel,
            "image": image_url,
            "error": error or "",
            "updated": is_updated,
            "url": SOURCE_URLS.get(name, ""),
        })

    panels_json = json.dumps(panels_data, ensure_ascii=False)

    cards = []
    for i, p in enumerate(panels_data):
        title = html.escape(p["name"])
        border_color = "#00c853" if p["updated"] else "#ffd641"
        bg_color = "#e3f8ea" if p["updated"] else "#fff7de"
        cards.append(f"""
        <button type="button" class="card" style="border-color:{border_color};background-color:{bg_color}" onclick="openDetail({i})">
            <span class="card-name">{title}</span>
            <span class="card-counter" id="card-counter-{i}"></span>
        </button>
        """)

    site_url = "https://sebastiano-mazzarisi.github.io/Rosticcerie/output/rosticceria_ios/"

    index_html = f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-title" content="Rosticcerie">
  <meta name="apple-mobile-web-app-status-bar-style" content="black">
  <link rel="apple-touch-icon" href="apple-touch-icon.png">
  <meta property="og:title" content="Rosticcerie">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{site_url}Rosticcerie.html">
  <meta property="og:image" content="{site_url}apple-touch-icon.png">
  <title>Rosticcerie</title>
  <style>
    body {{
      margin: 0;
      background: #111;
      color: #fff;
      font-family: Arial, sans-serif;
    }}
    /* Fascia nera superiore */
    header {{
      background: #000;
      padding: 18px 16px;
      border-bottom: 1px solid #333;
      position: sticky;
      top: 0;
      z-index: 100;
      text-align: center;
    }}
    h1#main-title {{
      margin: 0;
      font-size: 32px;
      color: #007bff; /* Azzurro */
      cursor: pointer;
    }}
    .updated {{
      margin: 4px 0 0;
      color: #ccc;
      font-size: 14px;
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
      background: #fff7de; /* Sostituito inline per riga: verde/giallo tenue */
      box-sizing: border-box;
      cursor: pointer;
      min-height: 110px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 12px;
      border: 4px solid #ffd641; /* Verde intenso se aggiornata oggi, giallo intenso altrimenti */
      border-radius: 12px;
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

    function renderDetail(i) {{
        const n = PANELS.length;
        currentIndex = ((i % n) + n) % n;
        const p = PANELS[currentIndex];

        document.getElementById('main-title').innerText = p.name;
        document.getElementById('main-updated').style.display = 'none';

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
            const p = PANELS[currentIndex];
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

        const mainTitle = document.getElementById('main-title');
        if (isAdmin) {{
            updateAdminTitle();
        }} else {{
            mainTitle.innerText = 'Rosticcerie';
        }}

        window.scrollTo(0, 0);
    }}

    function handleTitleClick() {{
        const inDetail = document.getElementById('grid-view').style.display === 'none';
        if (inDetail) {{
            const p = PANELS[currentIndex];
            if (p && p.url) {{
                window.open(p.url, '_blank', 'noopener');
            }}
            return;
        }}
        if (isAdmin) {{
            if (confirm("Vuoi davvero azzerare il contatore? (Verra' azzerato per tutti i dispositivi)")) {{
                resetCounterGlobally();
            }}
        }}
    }}

    window.onload = loadCounter;
  </script>
</head>
<body>
  <header id="main-header">
    <h1 id="main-title" onclick="handleTitleClick()">Rosticcerie</h1>
    <div id="phone-line"></div>
    <p id="main-updated" class="updated">{html.escape(today_label)}</p>
  </header>

  <main id="grid-view">
    {"".join(cards)}
  </main>

  <div id="detail-view">
    <div id="detail-content" onclick="closeDetail()"></div>
  </div>

  <div id="nav-bar">
    <button type="button" onclick="showPrev()" aria-label="Rosticceria precedente">&#8592;</button>
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


def find_git_repository(path: str) -> Optional[str]:
    current = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def fit_image(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return fitted


def draw_panel(canvas, image_tk, panel: Dict, left: int, top: int, width: int, height: int):
    canvas.create_rectangle(left, top, left + width, top + height, fill="black", outline="#333333")

    if "error" in panel:
        canvas.create_text(
            left + 28,
            top + 28,
            anchor="nw",
            text=f"{panel['name']}\n{panel['error']}",
            fill="white",
            font=("Arial", 24, "bold"),
            width=max(260, width - 56),
        )
        return None

    image = Image.open(io.BytesIO(panel["image_bytes"]))
    image = fit_image(image, width, height)
    photo = image_tk.PhotoImage(image)

    x = left + (width - image.width) // 2
    y = top + (height - image.height) // 2
    canvas.create_image(x, y, anchor="nw", image=photo)

    title = panel["name"]
    text = panel.get("text", "")
    overlay = title if not text else f"{title}\n{text}"
    text_width = min(680, max(260, width - 56))
    text_id = canvas.create_text(
        left + 28,
        top + 24,
        anchor="nw",
        text=overlay,
        fill="white",
        font=("Arial", 21, "bold"),
        width=text_width,
    )
    bbox = canvas.bbox(text_id)
    if bbox:
        padding = 14
        background = canvas.create_rectangle(
            bbox[0] - padding,
            bbox[1] - padding,
            bbox[2] + padding,
            bbox[3] + padding,
            fill="black",
            outline="white",
        )
        canvas.tag_lower(background, text_id)

    return photo


def show_fullscreen(panels: List[Dict]) -> None:
    from PIL import ImageTk
    from tkinter import Canvas, Tk

    root = Tk()
    root.title("Rosticcerie")
    root.configure(bg="black")
    root.attributes("-fullscreen", True)
    root.focus_force()

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    canvas = Canvas(root, width=screen_width, height=screen_height, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    panel_count = max(1, len(panels))
    panel_width = screen_width // panel_count
    photos = []
    for index, panel in enumerate(panels):
        left = index * panel_width
        width = screen_width - left if index == panel_count - 1 else panel_width
        photos.append(draw_panel(canvas, ImageTk, panel, left, 0, width, screen_height))
        if index:
            canvas.create_line(left, 0, left, screen_height, fill="white", width=2)
    canvas.photos = photos

    def close(_event=None):
        root.destroy()

    root.bind("<Key>", close)
    root.bind("<Button-1>", close)
    root.bind("<Escape>", close)
    root.after(300, root.focus_force)
    root.mainloop()


def extract_pages() -> List[Dict]:
    panels = []

    for facebook_page in FACEBOOK_PAGES:
        name = facebook_page["name"]
        existing_panel = existing_publish_panel_if_today(name)
        if existing_panel:
            print(f"{name}: foto di oggi già presente, salto la verifica.")
            panels.append(existing_panel)
            continue

        print(f"Cerco la prima immagine su Facebook: {name}...")
        try:
            post = extract_first_facebook_image(
                facebook_page["url"],
                prefer_active_closure=(name == "Le delizie di Michela"),
            )
            image_bytes = download_image(post["image_url"])
            
            if name == "Fantasia":
                image_bytes = crop_fantasia_chalkboard(image_bytes)
            elif name == "Le delizie di Michela":
                closure_signal = f"{post.get('text', '')} {post.get('image_alt', '')}"
                if looks_like_closure_notice(closure_signal):
                    print(
                        f"{name}: rilevato avviso di chiusura/ferie, mantengo la foto "
                        "intera (niente ritaglio lavagna)."
                    )
                    if not clean_post_text(post.get("text", "")):
                        alt_text = clean_facebook_alt_text(post.get("image_alt", ""))
                        if alt_text:
                            post["text"] = alt_text
                else:
                    image_bytes = crop_michela_chalkboard(image_bytes)
            elif name == "Santoro (Castellana)":
                image_bytes = add_white_border(image_bytes, border=10)

            image_bytes = add_date_footer(image_bytes, post.get("published_at", ""))

            image_path = save_image(image_bytes, facebook_page["output_image"])
            print(f"{name}: immagine salvata in {image_path}")
            if not post.get("published_at_raw"):
                print(
                    f"{name}: non ho trovato la data/ora del post su Facebook "
                    "(published_at_raw vuoto). Uso come riserva la data eventualmente "
                    "scritta nel testo del post."
                )
            panels.append(
                {
                    "name": name,
                    "image_bytes": image_bytes,
                    "text": post.get("text", ""),
                    "published_at": post.get("published_at", ""),
                    "published_at_raw": post.get("published_at_raw", ""),
                }
            )
        except Exception as exc:
            existing_panel = existing_publish_panel_if_today(name, require_today=False)
            if existing_panel:
                print(f"{name}: Facebook non leggibile ora, tengo l'ultima foto salvata.")
                panels.append(existing_panel)
            else:
                panels.append({"name": name, "error": str(exc)})

    existing_panel = existing_publish_panel_if_today(PANECO_PAGE["name"])
    if existing_panel:
        print("Pane&Co: menu di oggi già presente, salto la verifica.")
        panels.append(existing_panel)
    else:
        print("Creo il menu Pane&Co con primi e secondi del giorno...")
        try:
            panel = extract_paneeco_menu()
            image_path = save_image(panel["image_bytes"], "Rosticceria_Pane_Co.jpg")
            print(f"Pane&Co: immagine salvata in {image_path}")
            panels.append(panel)
        except Exception as exc:
            panels.append({"name": PANECO_PAGE["name"], "error": str(exc)})

    for text_page in TEXT_FACEBOOK_PAGES:
        name = text_page["name"]
        print(f"Cerco il menu testuale su Facebook: {name}...")
        try:
            panel = extract_first_facebook_text_menu(text_page)
            image_path = save_image(panel["image_bytes"], f"Rosticceria_{safe_file_name(name)}.jpg")
            print(f"{name}: immagine generata in {image_path}")
            panels.append(panel)
        except Exception as exc:
            existing_panel = existing_publish_panel_if_today(name, require_today=False)
            if existing_panel:
                print(f"{name}: menu completo non leggibile ora, tengo l'ultimo menu salvato.")
                panels.append(existing_panel)
            else:
                panels.append({"name": name, "error": str(exc)})

    return panels


def run_once(show: bool = False, publish_to_git: bool = True) -> None:
    panels = extract_pages()
    output_dir = publish_dir()
    if panels and all(panel.get("reused") for panel in panels):
        output_dir = save_publish_files(panels)
        print(f"File per iOS riallineati in: {output_dir}")
        print("Tutte le rosticcerie hanno già il menu di oggi: nessuna verifica necessaria.")
        if show:
            show_fullscreen(panels)
        return

    output_dir = save_publish_files(panels)
    print(f"File per iOS aggiornati in: {output_dir}")

    if publish_to_git:
        git_publish_if_available(output_dir)

    if show:
        show_fullscreen(panels)


def inside_run_window(moment: datetime.datetime) -> bool:
    return RUN_START <= moment.time() <= RUN_END


def next_run_time(now: datetime.datetime) -> datetime.datetime:
    today_start = datetime.datetime.combine(now.date(), RUN_START)
    today_end = datetime.datetime.combine(now.date(), RUN_END)
    interval = datetime.timedelta(minutes=RUN_INTERVAL_MINUTES)

    if now < today_start:
        return today_start
    if now > today_end:
        return today_start + datetime.timedelta(days=1)

    next_time = today_start
    while next_time < now:
        next_time += interval

    if next_time <= today_end:
        return next_time
    return today_start + datetime.timedelta(days=1)


def monitor_loop(show: bool = False, publish_to_git: bool = True) -> None:
    print("Monitor attivo: estrazione ogni minuto tra le 09:00 e le 12:00.")

    while True:
        now = datetime.datetime.now()
        scheduled = next_run_time(now)
        seconds = max(0, int((scheduled - now).total_seconds()))
        print(f"Prossima estrazione: {scheduled.strftime('%d/%m/%Y %H:%M')}")

        while seconds > 0:
            time.sleep(min(seconds, 60))
            now = datetime.datetime.now()
            seconds = max(0, int((scheduled - now).total_seconds()))

        if inside_run_window(datetime.datetime.now()):
            run_once(show=show, publish_to_git=publish_to_git)


def main() -> None:
    parser = argparse.ArgumentParser(description="Estrae e pubblica Fantasia, Cibària, Bollenti piatti, Pane&Co, Impastamò, Le delizie di Michela e Santoro.")
    parser.add_argument("--once", action="store_true", help="Esegue una sola estrazione e poi termina.")
    parser.add_argument("--show", action="store_true", help="Mostra anche le due foto a pieno schermo.")
    parser.add_argument("--no-git", action="store_true", help="Non prova a pubblicare con GitHub/git.")
    args = parser.parse_args()

    if args.once:
        run_once(show=args.show, publish_to_git=not args.no_git)
    else:
        monitor_loop(show=args.show, publish_to_git=not args.no_git)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Errore: {exc}")
        sys.exit(1)
