"""Menu forniti localmente (foto verificata a mano), validi solo per la
data dichiarata. Usato sia per "Le delizie di Michela" (ripiego quando lo
scraping delle Storie Facebook non riesce) sia per rosticcerie che non
hanno affatto una fonte automatica, come Aufer, il cui menu e' pubblicato
solo nelle Storie di Instagram: Instagram le nasconde a chiunque non sia
loggato, quindi vanno importate a mano (Importa_Michela.py / Importa_Aufer.py)
o da uno script con una sessione autenticata dedicata, sullo stesso modello
di ImportaStoriaMichela.py.

Ogni rosticceria gestita cosi' ha uno "slug" breve (es. "michela", "aufer")
che identifica il file in local_menus/<slug>_<data>.jpg: e' fisso e non
deriva dal nome visualizzato, cosi' i file gia' pubblicati restano validi
anche se il nome cambia.

In alternativa (e con priorita' massima), si puo' salvare manualmente
l'immagine del menu nella cartella Menu/ accanto a Progetto/, con il nome
AAAA-MM-GG-NomeRosticceria.jpg  (es. 2026-09-20-Fantasia.jpg).
Il campo menu_slug in config.py definisce il nome atteso per ciascuna
rosticceria. Se il file e' presente oggi, viene usato prima di qualsiasi
sorgente automatica (Facebook, Instagram, sito)."""
from datetime import date
from pathlib import Path
import io
from PIL import Image, ImageOps
import Rosticceria_legacy as legacy

# Retro-compatibilita': alcuni punti del codice (es. Importa_Michela.py
# prima di questa modifica) si aspettavano NAME/slug impliciti per Michela.
NAME = "Le delizie di Michela"
MICHELA_SLUG = "michela"


def parent_menu_path(menu_slug: str, day: date) -> Path | None:
    """Cerca nella cartella Menu/ (affiancata a Progetto/) un file
    AAAA-MM-GG-{menu_slug}.jpg/jpeg/png salvato manualmente dall'utente.
    Restituisce il Path se trovato, None altrimenti."""
    if not menu_slug:
        return None
    # Progetto/ e' script_dir(); Menu/ e' una sorella di Progetto/ sotto Rosticcerie/
    folder = Path(legacy.script_dir()).parent / "Menu"
    for ext in ("jpg", "jpeg", "png", "JPG", "JPEG", "PNG"):
        p = folder / f"{day.isoformat()}-{menu_slug}.{ext}"
        if p.is_file():
            return p
    return None


def parent_menu_panel(menu_slug: str, name: str, day: date | None = None):
    """Restituisce un pannello dall'immagine manuale in Menu/, se presente per oggi.
    Ha priorita' massima su qualsiasi sorgente automatica."""
    day = day or legacy.rome_now().date()
    path = parent_menu_path(menu_slug, day)
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        image_bytes = path.read_bytes()
    except (OSError, ValueError):
        print(f"{name}: immagine in Menu/ non valida ({path.name}).")
        return None
    print(f"{name}: trovata immagine manuale Menu/{path.name}.")
    return {
        "name": name,
        "image_bytes": legacy.add_date_footer(image_bytes, day.strftime("%d/%m/%Y")),
        "text": "",
        "published_at": day.strftime("%d/%m/%Y"),
        "published_at_raw": "Menu importato manualmente dalla cartella Menu/",
    }


def menu_path(slug: str, day: date) -> Path:
    return Path(legacy.script_dir()) / "local_menus" / f"{slug}_{day.isoformat()}.jpg"


def import_image(slug: str, name: str, source: Path, day: date) -> Path:
    if day > legacy.rome_now().date():
        raise ValueError("La data del menu non puo' essere futura.")
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if min(image.size) < 200:
            raise ValueError("Immagine troppo piccola: serve la foto leggibile del menu.")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
    destination = menu_path(slug, day)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(destination)
    return destination


def local_panel(slug: str, name: str, day: date | None = None):
    day = day or legacy.rome_now().date()
    path = menu_path(slug, day)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        image_bytes = path.read_bytes()
    except (OSError, ValueError):
        print(f"{name}: immagine locale non valida.")
        return None
    return {
        "name": name,
        "image_bytes": legacy.add_date_footer(image_bytes, day.strftime("%d/%m/%Y")),
        "text": "",
        "published_at": day.strftime("%d/%m/%Y"),
        "published_at_raw": "Data del menu confermata all'importazione locale",
    }
