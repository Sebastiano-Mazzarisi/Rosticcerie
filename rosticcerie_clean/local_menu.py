"""Menu di Michela fornito localmente, valido solo per la data dichiarata."""
from datetime import date
from pathlib import Path
import io
from PIL import Image, ImageOps
import Rosticceria_legacy as legacy

NAME = "Le delizie di Michela"

def menu_path(day: date) -> Path:
    return Path(legacy.script_dir()) / "local_menus" / f"michela_{day.isoformat()}.jpg"

def import_image(source: Path, day: date) -> Path:
    if day > legacy.rome_now().date():
        raise ValueError("La data del menu non puo' essere futura.")
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if min(image.size) < 200:
            raise ValueError("Immagine troppo piccola: serve la foto leggibile del menu.")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=95)
    destination = menu_path(day)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(buffer.getvalue())
    temporary.replace(destination)
    return destination

def local_panel(day: date | None = None):
    day = day or legacy.rome_now().date()
    path = menu_path(day)
    if not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        image_bytes = path.read_bytes()
    except (OSError, ValueError):
        print("Michela: immagine locale non valida; controllo Facebook.")
        return None
    return {
        "name": NAME,
        "image_bytes": legacy.add_date_footer(image_bytes, day.strftime("%d/%m/%Y")),
        "text": "",
        "published_at": day.strftime("%d/%m/%Y"),
        "published_at_raw": "Data del menu confermata all'importazione locale",
    }
