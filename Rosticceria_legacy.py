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
import urllib.parse
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
MIDNIGHT_REFRESH = datetime.time(0, 1)
MIDNIGHT_REFRESH_GRACE_MINUTES = 15
RUN_START = datetime.time(6, 0)
RUN_END = datetime.time(12, 0)
RUN_INTERVAL_MINUTES = 15
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

        # Facebook puo' rendere "Altro..." come semplice testo, senza ruolo
        # button: in quel caso individuiamo direttamente l'elemento visibile
        # e proviamo anche l'attivazione da tastiera.
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
                    after_text = post.inner_text(timeout=1500)
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                    element.press("Enter", timeout=1500)
                    page.wait_for_timeout(1200)
                    after_text = post.inner_text(timeout=1500)
                    if after_text and not has_see_more_marker(after_text):
                        clicked = True
                        break
                except Exception:
                    continue

        if clicked:
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
            # Il pulsante "Altro" potrebbe non essere ancora comparso (pagina
            # ancora in caricamento): a differenza di prima, non rinunciamo
            # subito al primo tentativo a vuoto, ma aspettiamo un attimo e
            # riproviamo, fino a esaurire i tentativi previsti dal ciclo.
            page.wait_for_timeout(700)
            continue
        try:
            after_text = post.inner_text(timeout=1000)
        except Exception:
            after_text = ""
        if after_text and after_text != before_text and "Altro" not in after_text:
            return

    # Ultima rete di sicurezza, indipendentemente dal fatto che uno dei
    # tentativi di click sopra sia riuscito o no: alcuni post mostrano il
    # testo completo gia' presente nella pagina, solo tagliato via CSS
    # (line-clamp/altezza massima) invece che davvero assente dal DOM finche'
    # non si clicca. In quel caso forziamo la visibilita' del testo intero e
    # rimuoviamo l'eventuale etichetta "Altro"/"See more" residua, cosi' il
    # testo completo (ora leggibile) non venga comunque scartato come
    # troncato da has_see_more_marker.
    try:
        post.evaluate(
            """post => {
                post.querySelectorAll('*').forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style && style.webkitLineClamp && style.webkitLineClamp !== 'none') {
                        el.style.setProperty('-webkit-line-clamp', 'unset', 'important');
                        el.style.setProperty('display', 'block', 'important');
                        el.style.setProperty('max-height', 'none', 'important');
                        el.style.setProperty('overflow', 'visible', 'important');
                    }
                });
                post.querySelectorAll('div[role="button"], a, span').forEach(el => {
                    const label = (el.innerText || el.textContent || '').trim();
                    if (/^(?:\\u2026|\\.\\.\\.)?\\s*(altro\\.?|mostra altro|see more)$/i.test(label)) {
                        el.remove();
                    }
                });
            }"""
        )
    except Exception:
        pass


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

    def time_priority(value):
        return 0 if re.search(r"\d{1,2}:\d{2}", value) else 1
    candidates.sort(key=time_priority)
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


def prefer_publication_time(menu_date: str, publication: str) -> str:
    """Keep a source time only when its date matches the menu date."""
    if not menu_date:
        return publication
    if parse_status_date(menu_date) == parse_status_date(publication) and re.search(r"\b\d{1,2}:\d{2}\b", publication or ""):
        return publication
    return menu_date


def format_card_reference(value: str, is_updated: bool) -> str:
    """Formato breve: ora per i menu di oggi, data per quelli precedenti.

    NOTA: oltre che per il testo mostrato, questa funzione viene usata
    altrove (pipeline.py) come "c'e' gia' un riferimento orario valido per
    oggi?" per decidere se saltare un nuovo controllo della fonte: per
    questo, quando is_updated=True, resta intenzionalmente vuota se non
    troviamo un orario preciso (es. Pane & Co, che sul sito riporta solo la
    data, senza ora) invece di ripiegare sulla data. Per il "confetto"
    visivo in home, che invece deve comunque comparire anche senza un
    orario preciso, vedi format_card_badge qui sotto."""
    if is_updated:
        match = re.search(r"(?:^|\s)(\d{1,2}):(\d{2})(?:\s|$)", value or "")
        return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""

    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value or "")
    if not match:
        return ""
    try:
        day, month, year = (int(match.group(i)) for i in (1, 2, 3))
        date_value = datetime.date(year, month, day)
        months = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
        return f"{date_value.day} {months[date_value.month - 1]}"
    except ValueError:
        return ""


def format_card_badge(value: str, is_updated: bool) -> str:
    """Testo del "confetto" verde mostrato sulla casella in home.

    Come format_card_reference, ma quando il menu e' di oggi (is_updated)
    senza pero' un orario preciso disponibile (es. Pane & Co, che sul sito
    riporta solo la data "10 Settembre", mai un'ora), mostriamo comunque la
    data invece di nascondere del tutto il confetto: prima restava vuoto e
    il confetto verde non compariva mai per queste rosticcerie."""
    reference = format_card_reference(value, is_updated)
    if reference or not is_updated:
        return reference

    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value or "")
    if not match:
        return ""
    try:
        day, month, year = (int(match.group(i)) for i in (1, 2, 3))
        date_value = datetime.date(year, month, day)
        months = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
        return f"{date_value.day} {months[date_value.month - 1]}"
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


def find_first_post_image(
    page,
    skip_closure_notices: bool = False,
    skip_first_today_post: bool = False,
    prefer_facebook_date: bool = False,
) -> Optional[Dict[str, str]]:
    post_selectors = [
        'div[role="article"]',
        "div[aria-posinset]",
    ]
    candidates = []
    post_index = 0
    skipped_first_today_post = False

    for selector in post_selectors:
        posts = page.locator(selector).all()
        for post in posts[:20]:
            current_post_index = post_index
            post_index += 1
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

            # Facebook sometimes leaves the lazy-loaded image without a
            # usable bounding box in headless mode. Keep a direct fallback
            # so a later menu post is not discarded after an announcement.
            if best_image is None:
                for image in images:
                    try:
                        src = image.get_attribute("src") or ""
                    except Exception:
                        src = ""
                    if src.startswith("http") and "emoji.php" not in src:
                        best_image = image
                        best_score = 1
                        break

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
                    combined_text = f"{post_text} {full_post_text} {image_alt}"
                    # Impastamò pubblica gli avvisi con una descrizione testuale,
                    # mentre il menu del giorno e' normalmente una foto senza testo.
                    textual_post = bool(clean_post_text(post_text or full_post_text))
                    if (
                        skip_closure_notices
                        and textual_post
                        and looks_like_closure_notice(combined_text)
                        and not looks_like_real_menu(combined_text)
                    ):
                        if skip_first_today_post and not skipped_first_today_post:
                            skipped_first_today_post = True
                        print(
                            "Impastamò: salto l'immagine dell'annuncio di riapertura "
                            "e cerco il post successivo con il menu."
                        )
                        continue
                    date_in_post_text = infer_date_from_text(post_text) or infer_date_from_text(full_post_text)
                    facebook_time = best_published_time_from_post(post)
                    normalized_facebook_time = normalize_facebook_time(facebook_time)
                    if prefer_facebook_date and normalized_facebook_time:
                        published_at_raw = facebook_time
                        published_at = normalized_facebook_time
                    else:
                        # Quando Facebook mostra una data esplicita nel post
                        # (es. "29 agosto alle 13:22"), e' piu' affidabile del
                        # primo indicatore temporale relativo trovato nel DOM.
                        published_at_raw = date_in_post_text or facebook_time
                        published_at = prefer_publication_time(date_in_post_text, normalized_facebook_time) or rome_now().strftime("%d/%m/%Y")
                    if (
                        skip_first_today_post
                        and not skipped_first_today_post
                        and parse_status_date(published_at) == rome_now().date()
                    ):
                        skipped_first_today_post = True
                        print(
                            "Impastamò: salto per prova il primo post di oggi "
                            "e cerco quello successivo."
                        )
                        continue
                    try:
                        photo_url = best_image.evaluate(
                            "image => { const link = image.closest('a[href]'); return link ? link.href : ''; }"
                        )
                    except Exception:
                        photo_url = ""
                    candidate = {
                        "image_url": image_url,
                        "photo_url": photo_url,
                        "text": post_text,
                        "image_alt": image_alt,
                        "published_at": published_at,
                        "published_at_raw": published_at_raw,
                    }
                    if not skip_closure_notices:
                        return candidate

                    score = min(best_score / 10000, 100)
                    if looks_like_real_menu(combined_text):
                        score += 1000
                    if looks_like_closure_notice(combined_text):
                        score -= 200
                    score -= current_post_index * 5
                    candidate["score"] = score
                    candidate["post_index"] = current_post_index
                    candidates.append(candidate)
                    print(
                        "Impastamò: candidato post "
                        f"{current_post_index} punteggio {score:.1f} "
                        f"testo: {clean_post_text(combined_text)[:80]}"
                    )

    if candidates:
        candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
        best_candidate = candidates[0]
        print(
            "Impastamò: scelgo il post "
            f"{best_candidate.get('post_index')} con punteggio "
            f"{best_candidate.get('score', 0):.1f}."
        )
        return {
            key: value
            for key, value in best_candidate.items()
            if key not in {"score", "post_index"}
        }

    return None


WEEKDAY_INDEX_BY_NAME = {
    "lunedi": 0,
    "martedi": 1,
    "mercoledi": 2,
    "giovedi": 3,
    "venerdi": 4,
    "sabato": 5,
    "domenica": 6,
}


def infer_weekday_date_from_text(text: str) -> str:
    """Cerca un riferimento tipo 'MENU DI SABATO'/'MENU DI VENERDI' nel testo
    e restituisce la data (DD/MM/YYYY) dell'ultima occorrenza di quel giorno
    della settimana (oggi compreso). Utile per i "menu del giorno" (es.
    Bollenti piatti) che non riportano mai una data esplicita ne' un orario
    di pubblicazione leggibile, solo il nome del giorno."""
    # Rimuoviamo tutti gli accenti (non solo quelli di "menu"/"venerdi"),
    # cosi' "MENU'"/"MENÙ" e le varianti dei giorni con o senza accento
    # vengono tutte riconosciute allo stesso modo.
    unaccented = "".join(
        char
        for char in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(char)
    )
    match = re.search(
        r"\bmenu\s+di\s+(lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica)\b",
        unaccented,
    )
    if not match:
        return ""

    target_weekday = WEEKDAY_INDEX_BY_NAME.get(match.group(1))
    if target_weekday is None:
        return ""

    today = rome_now().date()
    for days_back in range(7):
        candidate_date = today - datetime.timedelta(days=days_back)
        if candidate_date.weekday() == target_weekday:
            return candidate_date.strftime("%d/%m/%Y")

    return ""


def find_first_text_menu_post(page, required_terms: Optional[List[str]] = None) -> Optional[Dict[str, str]]:
    post_selectors = [
        'div[role="article"]',
        "div[aria-posinset]",
    ]

    fallback_post = None
    fallback_post_has_terms = False
    truncated_fallback_post = None
    truncated_fallback_has_terms = False
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
            published_at_raw = best_published_time_from_post(post) or published_at or raw_text
            normalized_published_at = (
                prefer_publication_time(published_at, normalize_facebook_time(published_at_raw))
                or normalize_facebook_time(published_at_raw)
                or normalize_facebook_time(raw_text)
                # I "menu del giorno" (es. Bollenti piatti) non riportano mai
                # un orario di pubblicazione leggibile ne' una data esplicita,
                # solo il nome del giorno (es. "MENU DI SABATO"): in
                # quel caso risaliamo alla data dell'ultima occorrenza di
                # quel giorno della settimana (oggi compreso). Cerchiamo
                # questo riferimento nel testo GREZZO (raw_text) e non in
                # quello ripulito (post_text): clean_text_menu_post scarta
                # apposta le righe "Menu di <giorno>" in quanto ridondanti
                # per la visualizzazione, ma cosi' facendo le rendeva anche
                # invisibili a questa deduzione della data, che quindi non
                # trovava mai nulla.
                or infer_weekday_date_from_text(raw_text)
            )
            candidate = {
                "text": post_text,
                "published_at": normalized_published_at,
                "published_at_raw": published_at_raw,
            }
            lower_text = post_text.lower()
            has_required_terms = all(term.lower() in lower_text for term in (required_terms or []))

            if truncated:
                # Non siamo riusciti a espandere "Altro" (tipico senza un
                # login valido): meglio un menu incompleto che nessun menu,
                # ma solo come ultima riserva se non troviamo di meglio. Tra
                # piu' candidati troncati (es. altri post scorrendo la
                # pagina), preferiamo comunque quello che contiene i termini
                # richiesti (es. "secondi piatti"), invece di fermarci al
                # primo trovato anche se si interrompe prima nel testo e
                # mostra quindi solo i primi piatti.
                # Se il chiamante richiede sezioni precise (come "secondi
                # piatti" per Bollenti piatti), un post troncato che non le
                # contiene non e' un candidato valido: continuare la ricerca
                # evita di pubblicare soltanto l'inizio del menu.
                if required_terms and not has_required_terms:
                    continue
                if len(post_text) > 20 and (
                    truncated_fallback_post is None
                    or (has_required_terms and not truncated_fallback_has_terms)
                ):
                    truncated_fallback_post = candidate
                    truncated_fallback_has_terms = has_required_terms
                continue

            if has_required_terms and ("menu" in lower_text or "menù" in lower_text) and normalized_published_at:
                return candidate

            if len(post_text) > 20 and (
                fallback_post is None or (has_required_terms and not fallback_post_has_terms)
            ):
                fallback_post = candidate
                fallback_post_has_terms = has_required_terms

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


def facebook_original_image_url(image_url: str) -> str:
    """Rimuove dai percorsi CDN Facebook le directory di crop/resize.

    Facebook serve spesso miniature con segmenti come /p720x720/,
    /s960x960/ o /c0.15.200.200/. Togliendoli si arriva, quando la CDN lo
    consente, al file caricato senza tagli della griglia Foto.
    """
    if not image_url:
        return ""

    try:
        parsed = urllib.parse.urlsplit(image_url)
        path = re.sub(r"/[ps]\d+x\d+/", "/", parsed.path)
        path = re.sub(r"/c\d+(?:\.\d+){3}/", "/", path)
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
        )
    except Exception:
        return image_url


def facebook_photo_download_url(photo_href: str) -> str:
    if not photo_href:
        return ""
    try:
        parsed = urllib.parse.urlsplit(photo_href)
        query = urllib.parse.parse_qs(parsed.query)
        fbid_values = query.get("fbid") or query.get("photo_id")
        if not fbid_values:
            match = re.search(r"/photos/(?:[^/]+/)?(\d+)", parsed.path)
            fbid_values = [match.group(1)] if match else []
        if not fbid_values:
            return ""
        return "https://www.facebook.com/photo/download/?" + urllib.parse.urlencode(
            {"fbid": fbid_values[0]}
        )
    except Exception:
        return ""


def facebook_image_url_variants(image_url: str) -> List[str]:
    """Restituisce varianti CDN evitando, quando possibile, il crop quadrato
    usato dalle miniature Facebook."""
    if not image_url:
        return []

    variants: List[str] = []

    def add(url: str) -> None:
        if url and url.startswith("http") and url not in variants:
            variants.append(url)

    add(facebook_original_image_url(image_url))

    try:
        parsed = urllib.parse.urlsplit(image_url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

        no_crop_query = [
            (key, value)
            for key, value in query
            if key not in {"stp", "cstp", "ctp"}
        ]
        add(
            facebook_original_image_url(
                urllib.parse.urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        urllib.parse.urlencode(no_crop_query),
                        parsed.fragment,
                    )
                )
            )
        )

        no_stp_query = [
            (key, "s960x960" if key == "ctp" else value)
            for key, value in query
            if key not in {"stp", "cstp"}
        ]
        add(
            facebook_original_image_url(
                urllib.parse.urlunsplit(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        urllib.parse.urlencode(no_stp_query),
                        parsed.fragment,
                    )
                )
            )
        )
    except Exception:
        pass

    add(facebook_original_image_url(re.sub(r"(?:ctp=|s)\d+x\d+", "s960x960", image_url)))
    add(image_url)
    return variants


def select_best_facebook_image_variant(image_urls: List[str]) -> Tuple[str, Tuple[int, int]]:
    selected_image_url = ""
    selected_dimensions = (0, 0)
    selected_variant_score = (-1.0, 0)
    tried: List[str] = []

    for image_url in image_urls:
        for variant_url in facebook_image_url_variants(image_url):
            if variant_url in tried:
                continue
            tried.append(variant_url)
            try:
                image_bytes = download_image(variant_url)
                width, height = Image.open(io.BytesIO(image_bytes)).size
                if min(width, height) < 380:
                    continue
                aspect_ratio = height / width if width else 0
                vertical_menu_score = min(aspect_ratio, 1.6)
                variant_score = (vertical_menu_score, width * height)
                if variant_score > selected_variant_score:
                    selected_image_url = variant_url
                    selected_dimensions = (width, height)
                    selected_variant_score = variant_score
            except Exception:
                continue

    return selected_image_url, selected_dimensions


def cookies_look_authenticated(cookies: List[Dict]) -> bool:
    names = {cookie.get("name", "") for cookie in cookies}
    return bool(names & FACEBOOK_LOGIN_COOKIE_NAMES)


def find_first_menu_photo_via_photos(context, facebook_url: str) -> Optional[Dict[str, str]]:
    """Cerca una foto-menu nella griglia Foto quando il menu e' pubblicato
    come immagine senza testo nel feed."""
    photos_page = context.new_page()
    try:
        photos_page.goto(
            build_photos_tab_url(facebook_url),
            wait_until="domcontentloaded",
            timeout=60000,
        )
        for cookie_label in ("Consenti tutti i cookie", "Allow all cookies"):
            try:
                photos_page.get_by_role("button", name=cookie_label).click(timeout=3000)
                break
            except Exception:
                pass
        photos_page.wait_for_timeout(4000)
        photos_page.keyboard.press("Escape")
        photos_page.wait_for_timeout(1000)

        # Facebook espone la griglia come immagini lazy-loaded. Usiamo
        # currentSrc e l'alt OCR, come nella diagnostica prova.py.
        candidates = []
        seen = set()
        for image in photos_page.locator("img").all():
            try:
                data = image.evaluate(
                    """image => ({
                        src: image.currentSrc || image.src || '',
                        alt: image.alt || '',
                        width: image.naturalWidth || image.width || 0,
                        height: image.naturalHeight || image.height || 0,
                        href: image.closest('a[href]') ? image.closest('a[href]').href : ''
                    })"""
                )
            except Exception:
                continue
            image_url = data.get("src", "")
            if not image_url.startswith("http") or "emoji.php" in image_url:
                continue
            if "scontent" not in image_url and "fbcdn" not in image_url:
                continue
            if data.get("width", 0) < 100 or data.get("height", 0) < 100:
                continue
            if image_url in seen:
                continue
            seen.add(image_url)
            data["is_photo_link"] = "/photo" in data.get("href", "")
            candidates.append(data)

        # I link /photo mantengono l'ordine delle immagini recenti.
        candidates.sort(key=lambda item: not item["is_photo_link"])
        menu_candidates = []
        for candidate in candidates[:80]:
            image_url = candidate.get("src", "")
            image_alt = (candidate.get("alt", "") or "").strip()
            clean_alt = clean_facebook_alt_text(image_alt) or image_alt
            score = menu_photo_score(clean_alt)
            if score < 0:
                print(
                    "Scarto foto avviso dalla griglia Foto: "
                    f"{clean_post_text(clean_alt)[:90]}"
                )
                continue
            if score <= 0:
                continue

            photo_href = candidate.get("href", "")

            image_urls_to_try = []
            download_url = facebook_photo_download_url(photo_href)
            if download_url:
                image_urls_to_try.append(download_url)
            if photo_href:
                try:
                    photo_page = context.new_page()
                    photo_page.goto(photo_href, wait_until="domcontentloaded", timeout=60000)
                    photo_page.wait_for_timeout(2500)
                    visible_url = find_largest_visible_image_url(photo_page)
                    photo_page.close()
                    if visible_url:
                        image_urls_to_try.append(visible_url)
                except Exception:
                    try:
                        photo_page.close()
                    except Exception:
                        pass
            image_urls_to_try.extend(facebook_image_url_variants(image_url))

            selected_image_url, selected_dimensions = select_best_facebook_image_variant(
                image_urls_to_try
            )
            if not selected_image_url:
                continue
            print(
                "Variante immagine menu scelta dalla griglia Foto: "
                f"{selected_dimensions[0]}x{selected_dimensions[1]}"
            )

            menu_candidates.append(
                {
                    "image_url": selected_image_url,
                    "photo_url": photo_href,
                    "text": clean_alt,
                    "image_alt": image_alt,
                    "published_at": rome_now().strftime("%d/%m/%Y"),
                    "published_at_raw": "foto menu trovata nella griglia Foto",
                    "score": score,
                }
            )
            print(
                "Candidato menu Foto punteggio "
                f"{score}: {clean_post_text(clean_alt)[:90]}"
            )
            if score >= 1000:
                print(
                    "Scelgo subito il primo menu forte dalla griglia Foto."
                )
                return {
                    "image_url": selected_image_url,
                    "photo_url": photo_href,
                    "text": clean_alt,
                    "image_alt": image_alt,
                    "published_at": rome_now().strftime("%d/%m/%Y"),
                    "published_at_raw": "foto menu trovata nella griglia Foto",
                }

        if menu_candidates:
            menu_candidates.sort(key=lambda item: item["score"], reverse=True)
            selected = menu_candidates[0]
            print(
                "Scelgo la foto menu dalla griglia Foto con punteggio "
                f"{selected['score']}."
            )
            return {
                key: value
                for key, value in selected.items()
                if key != "score"
            }
    except Exception:
        return None
    finally:
        try:
            photos_page.close()
        except Exception:
            pass
    return None


def extract_first_facebook_image(
    facebook_url: str,
    prefer_active_closure: bool = False,
    skip_closure_notices: bool = False,
    skip_first_today_post: bool = False,
    photo_grid_first: bool = False,
    prefer_facebook_date: bool = False,
) -> Dict[str, str]:
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

            if photo_grid_first:
                menu_photo = find_first_menu_photo_via_photos(context, facebook_url)
                if menu_photo:
                    print("Menu trovato nella griglia Foto di Facebook.")
                    return menu_photo
                raise RuntimeError(
                    "Menu non trovato nella griglia Foto: trovati solo avvisi o foto non riconosciute."
                )

            page.wait_for_timeout(5000)
            try:
                page.screenshot(path="debug_facebook_feed.png", full_page=True)
            except Exception:
                pass
            for _ in range(4):
                post = find_first_post_image(
                    page,
                    skip_closure_notices=skip_closure_notices,
                    skip_first_today_post=skip_first_today_post,
                    prefer_facebook_date=prefer_facebook_date,
                )
                if post:
                    photo_url = post.get("photo_url", "")
                    image_urls_to_try = [post.get("image_url", "")]
                    download_url = facebook_photo_download_url(photo_url)
                    if download_url:
                        image_urls_to_try.append(download_url)
                    if photo_url:
                        try:
                            photo_page = context.new_page()
                            photo_page.goto(photo_url, wait_until="domcontentloaded", timeout=60000)
                            photo_page.wait_for_timeout(4000)
                            larger_image_url = find_largest_visible_image_url(photo_page)
                            photo_page.close()
                            if larger_image_url:
                                image_urls_to_try.append(larger_image_url)
                        except Exception:
                            pass
                    selected_image_url, selected_dimensions = select_best_facebook_image_variant(
                        image_urls_to_try
                    )
                    if selected_image_url:
                        post["image_url"] = selected_image_url
                        print(
                            "Variante immagine post scelta: "
                            f"{selected_dimensions[0]}x{selected_dimensions[1]}"
                        )
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
                    # Aggiunge sotto l'immagine la stessa fascia bianca con la
                    # data usata per tutte le altre rosticcerie (vedi
                    # extract_pages/extract_paneeco_menu), cosi' anche i menu
                    # testuali come "Bollenti piatti" la mostrano "sotto la
                    # foto" e non solo (se presente) nell'intestazione.
                    image_bytes = add_date_footer(image_bytes, post.get("published_at", ""))
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
                    const published = document.querySelector('meta[property="article:published_time"]')?.content
                        || document.querySelector('[itemprop="datePublished"]')?.getAttribute('datetime')
                        || document.querySelector('.menu-header time[datetime]')?.getAttribute('datetime') || '';
                    return { date, categories, published };
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

    published_at = prefer_publication_time(normalize_paneeco_date(data.get("date", "")), normalize_facebook_time(data.get("published", "")))
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
    draw.text((margin, y), "Pane & Co", fill=ink, font=title_font)
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


def _requests_cookies_for_url(image_url: str) -> Dict[str, str]:
    if "facebook.com" not in image_url:
        return {}
    cookie_path = os.path.join(script_dir(), "cookies.txt")
    cookies = {}
    for cookie in load_facebook_cookies(cookie_path):
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value:
            cookies[name] = value
    return cookies


def download_image(image_url: str) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(
        image_url,
        headers=headers,
        cookies=_requests_cookies_for_url(image_url),
        timeout=30,
    )
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
        font_size = max(18, int(probe_size * target_text_width / probe_width))
    else:
        font_size = max(18, height // 14)
    font = _load_bold_font(font_size)
    while font_size > 12:
        bbox = probe_draw.textbbox((0, 0), date_text, font=font)
        if bbox[2] - bbox[0] <= width - 12:
            break
        font_size -= 1
        font = _load_bold_font(font_size)
    bar_height = max(42, min(86, int(font_size / 0.45)))

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


def _widest_dark_column_run(
    image: Image.Image,
    dark_threshold: int = 130,
    min_dark_ratio: float = 0.45,
) -> Optional[Tuple[int, int]]:
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
            if (r + g + b) / 3 < dark_threshold:
                dark_pixels += 1
            total_pixels += 1
        is_dark_col.append(total_pixels > 0 and (dark_pixels / total_pixels) >= min_dark_ratio)

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
    r"|\bsaremo\s+chius\w*\b|\bsiamo\s+tornat[io]\b"
    r"|\bnuovamente\s+apert[io]\b|\bdi\s+nuovo\s+apert[io]\b"
    r"|\babbiamo\s+ricaricat\w*\s+le\s+energie\b"
    r"|\bsiamo\s+pront[ioe]\b|\bti\s+aspettiamo\b",
    re.IGNORECASE,
)

MENU_NOTICE_PATTERN = re.compile(
    r"\bmen[uù]\b|\bmenu\b|\bprimi\b|\bsecondi\b|\bcontorni\b|\bantipasti\b|\bpiatti\b",
    re.IGNORECASE,
)

REAL_MENU_PATTERN = re.compile(
    r"\bmen[uù]\s+(?:del\s+giorno|di)\b"
    r"|\bprimi\s+piatti\b|\bsecondi\s+piatti\b|\bcontorni\b|\bantipasti\b",
    re.IGNORECASE,
)


def looks_like_closure_notice(text: str) -> bool:
    """Riconosce un post/cartello che avvisa di una chiusura per ferie o
    simili (es. "chiusi da venerdì a lunedì", "riapriamo martedì"), cosi'
    da poter evitare di trattarlo come una normale lavagna del menu del
    giorno."""
    return bool(CLOSURE_NOTICE_PATTERN.search(text or ""))


def looks_like_menu_notice(text: str) -> bool:
    return bool(MENU_NOTICE_PATTERN.search(text or ""))


def looks_like_real_menu(text: str) -> bool:
    """Distingue un menu effettivo da un annuncio che cita genericamente i menu."""
    return bool(REAL_MENU_PATTERN.search(text or ""))


def menu_photo_score(text: str) -> int:
    """Assegna un punteggio a una foto candidata: positivo per menu veri,
    negativo per avvisi di chiusura/riapertura."""
    value = (text or "").lower()
    if not value:
        return 0

    if looks_like_closure_notice(value) and not looks_like_real_menu(value):
        return -1000

    score = 0
    if looks_like_real_menu(value):
        score += 1000
    if re.search(r"\bmen[uù]\b|\bmenu\b", value, re.IGNORECASE):
        score += 200
    for term in ("antipasti", "primi", "secondi", "contorni"):
        if term in value:
            score += 120
    if re.search(r"\b\d{1,2}\s*/\s*\d{1,2}\b", value):
        score += 80
    return score


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
                    clicked = False
                    for _ in range(2):
                        try:
                            anchor.click(timeout=5000)
                            clicked = True
                            break
                        except Exception:
                            photos_page.wait_for_timeout(500)
                    if not clicked:
                        # Non siamo riusciti ad aprire il visualizzatore: teniamo
                        # l'URL della miniatura gia' raccolto (verra' comunque
                        # scartato piu' sotto se troppo piccolo) invece di
                        # rinunciare subito a questa foto.
                        raise RuntimeError("click sulla foto non riuscito")
                    photos_page.wait_for_timeout(2500)

                    try:
                        og_image_url = (
                            photos_page.locator('meta[property="og:image"]')
                            .first.get_attribute("content", timeout=2000)
                            or ""
                        )
                    except Exception:
                        og_image_url = ""
                    if og_image_url:
                        image_url = og_image_url
                    else:
                        for _ in range(6):
                            larger_image_url = find_largest_visible_image_url(photos_page)
                            if larger_image_url:
                                image_url = larger_image_url
                                break
                            photos_page.wait_for_timeout(1000)

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
                except Exception:
                    pass

            if not image_url:
                continue

            # Sicurezza: nonostante il tentativo sopra di aprire la foto in
            # grande, a volte resta comunque l'URL di una piccola miniatura
            # (es. l'anteprima nella griglia "Foto"), che una volta
            # scaricata risulta visibilmente ritagliata ai lati (il testo
            # del cartello viene tagliato a meta' parola). Scartiamo quindi
            # le immagini troppo piccole per essere la foto intera e
            # proviamo con la prossima nella griglia, invece di pubblicare
            # un avviso illeggibile.
            try:
                probe_bytes = download_image(image_url)
                probe_image = Image.open(io.BytesIO(probe_bytes))
                if min(probe_image.size) < 380:
                    print(
                        "Le delizie di Michela: immagine avviso troppo piccola "
                        f"({probe_image.size[0]}x{probe_image.size[1]}), probabile "
                        "miniatura ritagliata: la scarto e provo la prossima foto."
                    )
                    continue
            except Exception:
                pass

            if not published_at:
                # Ultima risorsa, se non troviamo la data reale di
                # pubblicazione dell'avviso: usiamo il giorno prima
                # dell'inizio della chiusura (l'ultimo giorno di apertura)
                # invece della data odierna. Con la chiusura gia' in corso,
                # mostrare "oggi" nella fascia sotto la foto farebbe
                # sembrare quella la data del menu, quando in realta' il
                # locale e' chiuso da giorni.
                if date_range:
                    fallback_date = date_range[0] - datetime.timedelta(days=1)
                    published_at = fallback_date.strftime("%d/%m/%Y circa")
                else:
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

    bounds = _widest_dark_column_run(image, dark_threshold=100, min_dark_ratio=0.25)
    if bounds is None:
        return image_bytes
    best_start, best_end = bounds
    best_len = best_end - best_start
    if best_len < max(width * 0.15, 150) or best_len >= width * 0.85:
        # Se il blocco scuro rilevato e' troppo stretto per essere una vera
        # lavagna leggibile (o copre gia' quasi tutta la foto), meglio
        # tenere la foto intera piuttosto che un ritaglio inutile o illeggibile.
        return image_bytes

    # Michela pubblica spesso lavagnette alte e strette: anche pochi pixel di
    # parete laterale rubano spazio utile al testo. Usiamo quindi un margine
    # molto piccolo, a differenza del ritaglio piu' permissivo usato altrove.
    margin = max(3, min(8, width // 90))
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
    refine_bounds = _widest_dark_column_run(cropped, dark_threshold=100, min_dark_ratio=0.25)
    if refine_bounds is not None:
        r_start, r_end = refine_bounds
        r_len = r_end - r_start
        if max(cropped_width * 0.15, 120) <= r_len < cropped_width * 0.95:
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
    candidates = []
    if os.name == "nt":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        candidates.extend(
            [
                os.path.join(windir, "Fonts", "arialbd.ttf"),
                os.path.join(windir, "Fonts", "segoeuib.ttf"),
            ]
        )
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ])
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
        "Pane & Co": "080-405.49.00",
        "Bollenti piatti": "334-318.58.44",
    }
    logo_files = {
        "Fantasia": "Logo-Fantasia.jpg",
        "Cibària": "Logo-Cibaria.jpg",
        "Impastamò": "Logo-Impastamo.jpg",
        "Le delizie di Michela": "Logo-Michela.jpg",
        "Santoro (Castellana)": "Logo-Santoro.jpg",
        "Pane & Co": "Logo-pane.jpg",
        "Bollenti piatti": "Logo-Bollent.jpg",
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
        updated_label = today_label
        published_at = ""
        if error:
            error = str(error)
        else:
            image_name = panel.get("publish_image", "")
            if image_name:
                image_url = f"{html.escape(image_name)}?v={int(time.time())}"
            published_at = panel_published_at(panel)
            is_updated = parse_status_date(published_at) == today
            updated_label = format_menu_date(published_at) or today_label

        panels_data.append({
            "name": name,
            "card_label": name,
            "detail_title": name,
            "logo": f"../../{html.escape(logo_files[name])}?v={int(time.time())}" if name in logo_files else "",
            "phone_display": phone_number,
            "phone_tel": phone_tel,
            "image": image_url,
            "error": error or "",
            "updated": is_updated,
            "updated_label": updated_label,
            "card_reference": format_card_badge(published_at, is_updated),
            "menu_date": parse_status_date(published_at).isoformat() if parse_status_date(published_at) else "",
            "url": SOURCE_URLS.get(name, ""),
            "counter_enabled": True,
        })

    panels_data.append({
        "name": "Suggerimenti",
        "card_label": "Suggerimenti",
        "detail_title": "Suggerimenti",
        "phone_display": "",
        "phone_tel": "",
        "image": f"Rosticcerie-Home.jpg?v={int(time.time())}",
        "error": "",
        "updated": True,
        "updated_label": today_label,
        "url": "",
        "counter_enabled": True,
        "card_border": "#49a95c",
        "card_bg": "#eaf7ea",
        "card_name_color": "#111",
    })

    panels_json = json.dumps(panels_data, ensure_ascii=False)

    cards = []
    for i, p in enumerate(panels_data):
        title = html.escape(p.get("card_label", p["name"])).replace("\n", "<br>")
        border_color = p.get("card_border") or ("#ffd641" if p["updated"] else "#555555")
        bg_color = p.get("card_bg") or ("#fff7de" if p["updated"] else "#ffffff")
        name_color = p.get("card_name_color") or ("#111" if p["updated"] else "#777777")
        counter_html = (
            f'<span class="card-counter" id="card-counter-{i}"></span>'
            if p.get("counter_enabled", True)
            else ""
        )
        reference_html = (
            f'<span class="card-reference">{html.escape(p.get("card_reference", ""))}</span>'
            if p.get("card_reference")
            else ""
        )
        suggestion_image = '<img class="suggestions-image" src="../../Magica.jpg" alt="" aria-hidden="true">' if p["name"] == "Suggerimenti" else ""
        cards.append(f"""
        <button type="button" class="card" data-pid="{i}" style="border-color:{border_color};background-color:{bg_color}" onclick="cardClicked({i})">
            {suggestion_image}
            <span class="card-name" style="color:{name_color}">{title}</span>
            {reference_html}
            {counter_html}
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
      color: #00c853; /* Verde brillante */
      cursor: pointer;
    }}
    .updated {{
      margin: 4px 0 0;
      color: #fff;
      font-size: 16px;
      cursor: pointer;
    }}
    .signature {{
      margin: 2px 0 0;
      color: #fff;
      font-size: 14px;
      cursor: pointer;
    }}

    #identity-block {{ display: flex; align-items: center; justify-content: center; gap: 16px; width: fit-content; max-width: 100%; margin: 0 auto; }}
    #identity-logo {{ display: none; width: 88px; height: 88px; object-fit: contain; border-radius: 6px; flex-shrink: 0; }}
    #identity-block.has-logo #main-title {{ color: #fff; }}
    #identity-text {{ min-width: 0; }}
    #identity-block.has-logo #identity-text {{ text-align: left; }}
    #identity-block.has-logo #phone-line {{ text-align: left; padding: 8px 0 0; }}
    @media (max-width: 480px) {{
      #identity-block {{ gap: 12px; }}
      #identity-logo {{ width: 72px; height: 72px; }}
      #identity-block.has-logo #main-title {{ font-size: 25px; }}
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
      background: #ffffff; /* Giallo tenue per i menu aggiornati, bianco per gli altri */
      box-sizing: border-box;
      cursor: pointer;
      min-height: 110px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 32px 10px 12px;
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
      line-height: 1.1;
      width: 100%;
      overflow-wrap: anywhere;
    }}
    .card-counter {{
      display: none;
      position: absolute;
      top: 6px;
      right: 10px;
      font-size: 16px;
      font-weight: normal;
      color: #000;
    }}
    .card-reference {{
      position: absolute;
      top: 6px;
      left: 10px;
      font-size: 14px;
      font-weight: normal;
      color: #000;
    }}
    .card.is-updated .card-reference {{
      color: #fff;
      background: #00863b;
      border-radius: 999px;
      padding: 2px 8px;
      line-height: 18px;
    }}
    .suggestions-image {{ width: 100px; height: auto; max-width: 100%; display: block; margin: 0 auto 8px; }}
    .card.is-suggestions {{
      padding: 12px 10px;
      justify-content: center;
      align-items: center;
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
      padding: 0;
      cursor: pointer; /* Toccare l'immagine (o il messaggio) torna all'elenco */
    }}
    #detail-content img {{
      width: 100vw;
      max-width: 100vw;
      max-height: none;
      height: auto;
      display: block;
      margin: 0 auto;
    }}
    #detail-content img.michela-menu {{
      border: 4px solid #ffd641;
      box-sizing: border-box;
    }}
    .share-panel {{
      width: min(100%, 520px);
      margin: 0 auto 16px;
      text-align: center;
    }}
    .share-button {{
      appearance: none;
      -webkit-appearance: none;
      border: 2px solid #49a95c;
      border-radius: 8px;
      background: #eaf7ea;
      color: #111;
      padding: 12px 22px;
      font: inherit;
      font-size: 20px;
      font-weight: bold;
      cursor: pointer;
    }}
    .share-button .share-symbol {{
      font-size: 24px;
      margin-right: 8px;
    }}
    .share-help {{
      margin: 10px 12px 0;
      color: #111;
      font-size: 16px;
    }}

    /* La foto occupa tutta la larghezza su mobile e un terzo su PC. */
    @media (min-width: 900px) {{
      #detail-content img {{
        width: 33.333vw;
        max-width: 33.333vw;
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
    // La chiave di azzeramento (offset) di "Pane & Co" e' rimasta quasi
    // allineata al totale (offset molto vicino al totale reale) per via di
    // prove fatte in passato direttamente sulla chiave in produzione: dato
    // che l'API del contatore permette solo di FAR CRESCERE l'offset (mai
    // di farlo scendere), non e' possibile "correggerlo" con un nuovo
    // azzeramento. Usiamo quindi per questa sola rosticceria una chiave di
    // azzeramento diversa e mai usata prima (che l'API legge come 0), cosi'
    // il numero mostrato torna a riflettere il totale reale delle
    // aperture invece di restare bloccato vicino a zero.
    const OFFSET_KEY_OVERRIDES = {{ 'Pane & Co': 'pane-co-r2' }};
    function offsetKeyFor(name) {{ return 'menu-views-offset-' + (OFFSET_KEY_OVERRIDES[name] || slugify(name)); }}
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

    function currentItalianDateLabel() {{
        const now = new Date();
        const weekdays = ['Domenica', 'Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato'];
        const months = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'];
        return weekdays[now.getDay()] + ' ' + now.getDate() + ' ' + months[now.getMonth()];
    }}

    function refreshMenuDates(now = new Date()) {{
        const parts = new Intl.DateTimeFormat('en-GB', {{timeZone: 'Europe/Rome', year: 'numeric', month: '2-digit', day: '2-digit'}}).formatToParts(now);
        const datePart = type => parts.find(p => p.type === type).value;
        const today = datePart('year') + '-' + datePart('month') + '-' + datePart('day');
        document.querySelectorAll('.card[data-pid]').forEach(card => {{
            const panel = PANELS[Number(card.dataset.pid)];
            if (!panel || panel.card_border) return;
            panel.updated = Boolean(panel.menu_date && panel.menu_date === today && !panel.error);
            card.classList.toggle('is-updated', panel.updated && Boolean((panel.card_reference || '').trim()));
            card.style.borderColor = panel.updated ? '#ffd641' : '#555555';
            card.style.backgroundColor = panel.updated ? '#fff7de' : '#ffffff';
            card.querySelector('.card-name').style.color = panel.updated ? '#111' : '#777777';
            const reference = card.querySelector('.card-reference');
            if (reference && panel.menu_date) {{
                // Se il menu e' di oggi ma non abbiamo un orario preciso (es.
                // Pane & Co, che sul sito riporta solo la data), mostriamo
                // comunque la data invece di svuotare il confetto verde:
                // prima questo ricalcolo lato client (che gira ogni secondo
                // per tenere la pagina aggiornata senza ricaricarla)
                // sovrascriveva con '' il testo gia' corretto generato dal
                // programma, facendo sparire il confetto poco dopo il
                // caricamento della pagina.
                const dateLabel = new Intl.DateTimeFormat('it-IT', {{timeZone: 'Europe/Rome', day: 'numeric', month: 'short'}}).format(new Date(panel.menu_date + 'T12:00:00Z'));
                const hasTime = /^([01]?[0-9]|2[0-3]):[0-5][0-9]$/.test(panel.card_reference || '');
                reference.innerText = (panel.updated && hasTime) ? panel.card_reference : dateLabel;
            }}
        }});
    }}
    document.addEventListener('DOMContentLoaded', refreshMenuDatesOnEvent);
    function refreshMenuDatesOnEvent() {{ refreshMenuDates(); }}
    window.addEventListener('focus', refreshMenuDatesOnEvent);
    document.addEventListener('visibilitychange', refreshMenuDatesOnEvent);
    setInterval(refreshMenuDatesOnEvent, 1000);

    function refreshReferenceDate() {{
        const el = document.getElementById('main-updated');
        if (el) el.innerText = currentItalianDateLabel();
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
    async function fetchJsonWithRetry(url, attempts, missingIsZero = false) {{
        for (let attempt = 1; attempt <= attempts; attempt++) {{
            let response;
            try {{
                response = await fetch(url, {{cache:'no-store'}});
            }} catch (err) {{
                if (attempt === attempts) {{
                    throw err;
                }}
                await sleep(1000);
                continue;
            }}

            if (response.status === 404 && missingIsZero) return {{value:0}};
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

    function visibleCounter(i) {{
        const total = totalClicksByPanel[i];
        const offset = offsetClicksByPanel[i];
        if (!Number.isFinite(total) || !Number.isFinite(offset)) return null;
        // An impossible reset baseline must not hide real recorded openings.
        return offset > total ? total : total - offset;
    }}
    let counterLoadRunning = false;
    let counterHitQueue = Promise.resolve();
    function recordCurrentView() {{
        if (isAdmin) return;
        const panel = PANELS[order[currentIndex]];
        if (!panel || panel.counter_enabled === false) return;
        counterHitQueue = counterHitQueue.then(async () => {{
            for (let attempt = 0; attempt < 4; attempt++) {{
                // Do not repeat an ambiguous network failure: it may have counted.
                const response = await fetch(counterHitUrlFor(panel.name), {{cache:'no-store', keepalive:true}});
                if (response.status === 429 && attempt < 3) {{
                    await sleep((parseRetryAfterSeconds(await response.text()) + 1) * 1000);
                    continue;
                }}
                if (!response.ok) throw new Error('Registrazione HTTP ' + response.status);
                const data = await response.json();
                if (!Number.isFinite(data.value)) throw new Error('Registrazione non confermata');
                return;
            }}
        }}).catch(error => console.error('Apertura non confermata: ' + panel.name, error));
    }}

    async function loadCounter() {{
        if (!isAdmin || counterLoadRunning) return;
        counterLoadRunning = true;
        updateCardCounters();
        // Leggiamo i contatori uno alla volta (non tutti insieme) e con una
        // piccola pausa tra una richiesta e l'altra, per restare sotto il
        // limite di frequenza dell'API gratuita di Abacus.
        for (let i = 0; i < PANELS.length; i++) {{
            const p = PANELS[i];
            if (p.counter_enabled === false) continue;
            try {{
                const totalData = await fetchJsonWithRetry(counterGetUrlFor(p.name), 4);
                const offsetData = await fetchJsonWithRetry(offsetGetUrlFor(p.name), 4, true);
                totalClicksByPanel[i] = totalData.value;
                offsetClicksByPanel[i] = offsetData.value;
            }} catch (e) {{
                totalClicksByPanel[i] = undefined;
                offsetClicksByPanel[i] = undefined;
                console.error('Impossibile leggere il contatore di ' + p.name, e);
            }}
            updateCardCounters();
            await sleep(150);
        }}
        counterLoadRunning = false;
        updateAdminTitle();
        updateCardCounters();
    }}

    async function resetCounterGlobally() {{
        const mainTitle = document.getElementById('main-title');
        for (let i = 0; i < PANELS.length; i++) {{
            const p = PANELS[i];
            if (p.counter_enabled === false) continue;
            mainTitle.innerText = 'Azzeramento in corso... (' + (i + 1) + '/' + PANELS.length + ')';
            try {{
                const totalData = await fetchJsonWithRetry(counterGetUrlFor(p.name), 4);
                const target = totalData.value;
                const offsetData = await fetchJsonWithRetry(offsetGetUrlFor(p.name), 4, true);
                let current = offsetData.value;
                if (current > target) throw new Error('Azzeramento incoerente: impossibile ridurre il valore remoto');
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
        if (document.getElementById('detail-view').style.display === 'block') return;
        let val = 0;
        for (let i = 0; i < PANELS.length; i++) {{
            if (PANELS[i].counter_enabled === false) continue;
            val += visibleCounter(i) ?? 0;
        }}
        document.getElementById('main-title').innerText = `Rosticcerie (${{val.toLocaleString('it-IT')}})`;
    }}

    function updateCardCounters() {{
        if (!isAdmin) return;
        for (let i = 0; i < PANELS.length; i++) {{
            const el = document.getElementById('card-counter-' + i);
            if (!el) continue;
            if (PANELS[i].counter_enabled === false) {{
                el.style.display = 'none';
                continue;
            }}
            const val = visibleCounter(i);
            el.innerText = val === null ? '…' : val.toLocaleString('it-IT');
            el.title = val === null ? 'Dato non disponibile: riprovare il refresh' : (offsetClicksByPanel[i] > totalClicksByPanel[i] ? 'Totale registrato: valore di azzeramento incoerente' : 'Aperture registrate');
            el.style.display = 'block';
        }}
    }}

    // --- Riordino personalizzato delle caselle iniziali (tenere premuto
    // per "tremare" + trascinare per scambiare posto, come su iOS/Android).
    // L'ordine e' salvato in localStorage: e' quindi personale per ogni
    // dispositivo/browser, non condiviso tra dispositivi diversi ne'
    // pubblicato sul sito.
    const ORDER_STORAGE_KEY = 'rosticcerie-order-v2';
    const DEFAULT_ORDER_NAMES = [
        'Fantasia', 'Bollenti piatti', 'Pane & Co', 'Cibària',
        'Le delizie di Michela', 'Impastamò', 'Santoro (Castellana)', 'Suggerimenti',
    ];

    function buildDefaultOrder() {{
        const nameToIndex = new Map(PANELS.map((p, i) => [p.name, i]));
        const restored = [];
        const seen = new Set();
        DEFAULT_ORDER_NAMES.forEach(name => {{
            if (nameToIndex.has(name) && !seen.has(name)) {{
                restored.push(nameToIndex.get(name));
                seen.add(name);
            }}
        }});
        PANELS.forEach((p, i) => {{
            if (!seen.has(p.name)) {{
                restored.push(i);
                seen.add(p.name);
            }}
        }});
        return restored;
    }}

    let order = buildDefaultOrder();
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

    const SHARE_URL = 'https://sebastiano-mazzarisi.github.io/Rosticcerie/output/rosticceria_ios/Rosticcerie.html';

    async function shareSite(event) {{
        event.stopPropagation();
        const shareData = {{
            title: 'Rosticcerie',
            text: 'Guarda i menu delle rosticcerie',
            url: SHARE_URL,
        }};
        try {{
            if (navigator.share) {{
                await navigator.share(shareData);
                return;
            }}
            await navigator.clipboard.writeText(SHARE_URL);
            alert('Link copiato negli appunti.');
        }} catch (err) {{
            if (err && err.name !== 'AbortError') {{
                alert('Impossibile avviare la condivisione.');
            }}
        }}
    }}

    function resetOrderToDefault() {{
        order = buildDefaultOrder();
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
            card.classList.toggle('is-suggestions', panel.name === 'Suggerimenti');
            card.style.borderColor = panel.card_border || (panel.updated ? '#ffd641' : '#555555');
            card.style.backgroundColor = panel.card_bg || (panel.updated ? '#fff7de' : '#ffffff');
            card.querySelector('.card-name').style.color = panel.card_name_color || (panel.updated ? '#111' : '#777777');
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

        const identityLogo = document.getElementById('identity-logo');
        document.getElementById('identity-block').classList.toggle('has-logo', Boolean(p.logo));
        identityLogo.style.display = p.logo ? 'block' : 'none';
        if (p.logo) {{
            identityLogo.src = p.logo;
            identityLogo.alt = 'Logo ' + p.name;
        }} else {{
            identityLogo.removeAttribute('src');
            identityLogo.alt = '';
        }}
        document.getElementById('main-title').innerText = p.detail_title || p.name;
        document.getElementById('main-updated').innerText = p.updated_label || '{html.escape(today_label)}';
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
            const imageClass = p.name === 'Le delizie di Michela' ? ' class="michela-menu"' : '';
            const sharePanel = p.name === 'Suggerimenti'
                ? '<div class="share-panel"><button type="button" class="share-button" onclick="shareSite(event)"><span class="share-symbol" aria-hidden="true">↗</span>Condividi</button><p class="share-help">Clicca su questo bottone per inviare il link ai tuoi amici.</p></div>'
                : '';
            content.innerHTML = sharePanel + '<img' + imageClass + ' src="' + p.image + '" alt="' + p.name + '">';
            applyDetailImageFit();
        }} else {{
            content.innerHTML = '<p class="error">' + (p.error || 'Menu non disponibile.') + '</p>';
        }}
    }}

    function applyDetailImageFit() {{
        const img = document.querySelector('#detail-content img');
        if (!img) return;
        const desktop = window.matchMedia('(min-width: 900px)').matches;
        const width = desktop ? (window.innerWidth / 3) : window.innerWidth;
        img.style.width = width + 'px';
        img.style.maxWidth = width + 'px';
        img.style.maxHeight = 'none';
        img.style.height = 'auto';
    }}

    function openDetail(i) {{
        document.getElementById('grid-view').style.display = 'none';

        renderDetail(i);
        document.getElementById('detail-view').style.display = 'block';
        document.getElementById('nav-bar').style.display = 'flex';
        applyDetailImageFit();
        window.scrollTo(0, 0);

        recordCurrentView();
    }}

    function showPrev() {{ renderDetail(currentIndex - 1); recordCurrentView(); }}
    function showNext() {{ renderDetail(currentIndex + 1); recordCurrentView(); }}

    function closeDetail() {{
        document.getElementById('identity-block').classList.remove('has-logo');
        document.getElementById('identity-logo').style.display = 'none';
        document.getElementById('identity-logo').removeAttribute('src');
        document.getElementById('detail-view').style.display = 'none';
        document.getElementById('phone-line').style.display = 'none';
        document.getElementById('nav-bar').style.display = 'none';
        document.getElementById('grid-view').style.display = 'grid';
        fitCardNames();
        document.getElementById('main-updated').style.display = '';
        document.getElementById('main-updated').innerText = currentItalianDateLabel();
        document.getElementById('main-signature').style.display = '';

        const mainTitle = document.getElementById('main-title');
        if (isAdmin) {{
            updateAdminTitle();
        }} else {{
            mainTitle.innerText = 'Rosticcerie';
        }}

        window.scrollTo(0, 0);
    }}

    let menuRefreshRunning = false;
    function italianDay() {{
        return new Intl.DateTimeFormat('en-CA', {{timeZone: 'Europe/Rome', year:'numeric',month:'2-digit',day:'2-digit'}}).format(new Date());
    }}
    let lastMenuRefreshDay = '';
    async function forceFreshReload(showFeedback = true) {{
        if (menuRefreshRunning) return;
        menuRefreshRunning = true;
        const signature = document.getElementById('main-signature');
        if (showFeedback) signature.innerText = 'Aggiornamento in corso…';
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        try {{
            const base = window.location.protocol === 'file:'
                ? new URL('https://sebastiano-mazzarisi.github.io/Rosticcerie/output/rosticceria_ios/')
                : new URL('.', window.location.href);
            const statusUrl = new URL('status.json', base);
            statusUrl.searchParams.set('refresh', Date.now().toString());
            const response = await fetch(statusUrl.href, {{cache:'no-store', signal:controller.signal}});
            if (!response.ok) throw new Error('HTTP ' + response.status);
            const status = await response.json();
            if (!Array.isArray(status.pages) || !status.pages.length) throw new Error('Dati non validi');
            status.pages.forEach(source => {{
                const panel = PANELS.find(p => p.name === source.name);
                if (!panel || panel.card_border) return;
                const date = /([0-9]{{2}})\/([0-9]{{2}})\/([0-9]{{4}})/.exec(source.published_at || '');
                panel.menu_date = date ? date[3] + '-' + date[2] + '-' + date[1] : '';
                const time = /([0-9]{{1,2}}:[0-9]{{2}})/.exec(source.published_at || '');
                // Come in refreshMenuDates: se manca un orario preciso (es.
                // Pane & Co, che riporta solo la data) mostriamo comunque la
                // data invece di svuotare il confetto verde, altrimenti
                // questo aggiornamento automatico (che gira gia' al primo
                // caricamento della pagina) lo faceva sparire subito dopo.
                if (time) {{
                    panel.card_reference = time[1];
                }} else if (panel.menu_date) {{
                    panel.card_reference = new Intl.DateTimeFormat('it-IT', {{timeZone: 'Europe/Rome', day: 'numeric', month: 'short'}}).format(new Date(panel.menu_date + 'T12:00:00Z'));
                }} else {{
                    panel.card_reference = '';
                }}
                panel.updated_label = source.published_at || '';
                panel.error = source.error || '';
                if (source.image) {{
                    const imageUrl = new URL(source.image, base);
                    imageUrl.searchParams.set('refresh', Date.now().toString());
                    panel.image = imageUrl.href;
                }} else {{ panel.image = ''; }}
                const card = document.querySelector('.card[data-pid="' + PANELS.indexOf(panel) + '"]');
                if (card && !card.querySelector('.card-reference')) {{
                    const ref = document.createElement('span');
                    ref.className = 'card-reference'; card.appendChild(ref);
                }}
                if (card) card.querySelector('.card-reference').innerText = panel.card_reference;
            }});
            refreshMenuDates();
            refreshReferenceDate();
            if (document.getElementById('detail-view').style.display === 'block') renderDetail(currentIndex);
            lastMenuRefreshDay = italianDay();
            if (isAdmin) loadCounter();
            if (showFeedback) signature.innerText = 'Aggiornato • by Mazzarisi';
        }} catch (error) {{
            refreshMenuDates();
            refreshReferenceDate();
            if (showFeedback) signature.innerText = 'Aggiornamento non riuscito • Tocca per riprovare';
            console.warn('Aggiornamento menu non riuscito', error);
        }} finally {{
            clearTimeout(timeout);
            menuRefreshRunning = false;
        }}
    }}
    function refreshWhenNeeded() {{
        if (!document.hidden && lastMenuRefreshDay !== italianDay()) forceFreshReload(false);
    }}
    document.addEventListener('DOMContentLoaded', refreshWhenNeeded);
    document.addEventListener('visibilitychange', refreshWhenNeeded);
    window.addEventListener('focus', refreshWhenNeeded);
    window.addEventListener('online', refreshWhenNeeded);
    setInterval(refreshWhenNeeded, 60000);

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
        }}
    }}

    function fitCardNames() {{
        document.querySelectorAll('.card-name').forEach(name => {{
            if (!name.clientWidth) return;
            name.style.fontSize = '';
            let size = parseFloat(getComputedStyle(name).fontSize);
            while (size > 10 && (name.scrollHeight > size * 1.1 * 2 + 1 || name.scrollWidth > name.clientWidth + 1)) {{
                size -= 0.5;
                name.style.fontSize = size + 'px';
            }}
            const picture = name.parentElement.querySelector('.suggestions-image');
            if (picture) {{
                const range = document.createRange();
                range.selectNodeContents(name);
                picture.style.width = range.getBoundingClientRect().width + 'px';
            }}
        }});
    }}
    window.addEventListener('resize', fitCardNames);
    document.addEventListener('DOMContentLoaded', fitCardNames);
    window.onload = loadCounter;
    window.addEventListener('resize', applyDetailImageFit);
    document.addEventListener('DOMContentLoaded', () => {{
        refreshReferenceDate();
        initReorder();
        refreshMenuDates();
    }});
  </script>
</head>
<body>
  <header id="main-header">
    <div id="identity-block">
      <img id="identity-logo" alt="">
      <div id="identity-text">
    <h1 id="main-title" onclick="handleTitleClick()">Rosticcerie</h1>
        <div id="phone-line"></div>
      </div>
    </div>
    <div id="reorder-actions">
      <button type="button" id="reorder-reset-btn" onclick="resetOrderToDefault()">Reset</button>
      <button type="button" id="reorder-done-btn" onclick="exitReorderMode()">Fine</button>
    </div>
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
        # Impastamo' puo' pubblicare prima un annuncio di riapertura e poi il
        # menu nello stesso giorno: non riutilizziamo quindi una foto gia'
        # salvata, altrimenti non arriveremmo mai al post del menu.
        if existing_panel and name != "Impastamò":
            print(f"{name}: foto di oggi già presente, salto la verifica.")
            panels.append(existing_panel)
            continue

        print(f"Cerco la prima immagine su Facebook: {name}...")
        try:
            post = extract_first_facebook_image(
                facebook_page["url"],
                prefer_active_closure=(name == "Le delizie di Michela"),
                skip_closure_notices=(name == "Impastamò"),
                skip_first_today_post=(name == "Impastamò"),
                prefer_facebook_date=(name == "Fantasia"),
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
            if existing_panel and name != "Impastamò":
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
    midnight_start = datetime.datetime.combine(moment.date(), MIDNIGHT_REFRESH)
    midnight_end = midnight_start + datetime.timedelta(minutes=MIDNIGHT_REFRESH_GRACE_MINUTES)
    return midnight_start <= moment <= midnight_end or RUN_START <= moment.time() <= RUN_END


def next_run_time(now: datetime.datetime) -> datetime.datetime:
    midnight_run = datetime.datetime.combine(now.date(), MIDNIGHT_REFRESH)
    today_start = datetime.datetime.combine(now.date(), RUN_START)
    today_end = datetime.datetime.combine(now.date(), RUN_END)
    interval = datetime.timedelta(minutes=RUN_INTERVAL_MINUTES)

    if now <= midnight_run:
        return midnight_run
    if now < today_start:
        return today_start
    if now > today_end:
        return midnight_run + datetime.timedelta(days=1)

    next_time = today_start
    while next_time < now:
        next_time += interval

    if next_time <= today_end:
        return next_time
    return midnight_run + datetime.timedelta(days=1)


def monitor_loop(show: bool = False, publish_to_git: bool = True) -> None:
    print("Monitor attivo: estrazione alle 00:01 e ogni 15 minuti tra le 06:00 e le 12:00.")

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
