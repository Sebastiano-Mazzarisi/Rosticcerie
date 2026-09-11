from __future__ import annotations

from typing import Dict, List

import Rosticceria_legacy as legacy

from .config import ROSTICCERIE, RosticceriaConfig
from .daily_posts import merge_today
from . import quick_check
from .local_menu import NAME as MICHELA_NAME, local_panel


def _existing(config: RosticceriaConfig, require_today: bool = True) -> Dict | None:
    return legacy.existing_publish_panel_if_today(config.name, require_today=require_today)


def _looks_like_menu_panel(panel: Dict | None) -> bool:
    """Vero se il pannello (nuovo o gia' salvato) sembra un vero menu in
    base al testo/alt-text, non un post pubblicitario o altro."""
    if not panel:
        return False
    combined = f"{panel.get('text', '')} {panel.get('image_alt', '')}"
    return legacy.looks_like_real_menu(combined)


def _normalize_bollenti_panel(config: RosticceriaConfig, panel: Dict) -> Dict:
    """Considera aggiornato Bollenti quando il menu e' valido ma manca la data DOM."""
    if config.name != "Bollenti piatti":
        return panel
    text = panel.get("text", "").lower()
    if panel.get("image_bytes") and legacy.looks_like_real_menu(text):
        panel = dict(panel)
        if not panel.get("published_at"):
            panel["published_at"] = legacy.rome_now().strftime("%d/%m/%Y")
        if not panel.get("published_at_raw"):
            panel["published_at_raw"] = "menu valido senza data Facebook"
    return panel


def _elapsed_hours(post: Dict) -> float:
    hours = legacy.hours_since_published(post.get("published_at", ""))
    return hours if hours is not None else float("inf")


def _extract_facebook_image(config: RosticceriaConfig) -> Dict:
    if config.name == MICHELA_NAME and local_panel():
        return _extract_facebook_image_full(config)
    saved = _existing(config, require_today=False)
    # Le storie hanno una sorgente separata: non inferirne lo stato dal feed.
    signature = None if config.story_url else quick_check.probe(config)
    if saved and quick_check.unchanged(config.name, signature):
        print(f"{config.name}: verifica rapida, nessuna variazione; riuso i dati salvati.")
        return saved
    panel = _extract_facebook_image_full(config)
    if panel.get("image_bytes") and not panel.get("error"):
        quick_check.remember(config.name, signature)
    return panel


def _extract_facebook_image_full(config: RosticceriaConfig) -> Dict:
    if config.name == MICHELA_NAME:
        supplied = local_panel()
        if supplied:
            print(f"{config.name}: uso il menu locale di oggi.")
            return supplied
    existing = _existing(config)
    print(f"{config.name}: cerco i post di oggi su Facebook...")
    try:
        posts = legacy.extract_today_facebook_posts(
            config.url,
            prefer_active_closure=config.prefer_active_closure,
            skip_closure_notices=config.skip_closure_notices,
            skip_first_today_post=config.skip_first_today_post,
            photo_grid_first=config.photo_grid_first,
            prefer_facebook_date=config.prefer_facebook_date,
            label=config.name,
            story_url=config.story_url,
        )
    except Exception:
        raise

    if config.name == "Impastamò":
        posts = merge_today(config.name, posts)

    if not posts:
        # Nessun post di oggi: non c'e' niente di fresco, teniamo l'ultimo
        # menu valido gia' salvato. Il riquadro in home restera' grigio solo
        # in questo caso - nessun post odierno.
        fallback = existing if _looks_like_menu_panel(existing) else _existing(config, require_today=False)
        if fallback:
            print(f"{config.name}: nessun post di oggi trovato, tengo l'ultimo menu disponibile.")
            return fallback
        raise RuntimeError(f"Nessun post trovato per {config.name}.")

    posts_oldest_first = sorted(posts, key=_elapsed_hours, reverse=True)
    most_recent_post = min(posts, key=_elapsed_hours)

    # Mostriamo SEMPRE l'unione di tutti i post trovati oggi, cosi' come
    # richiesto - anche se nessuno di essi sembra "il vero menu" (es. solo un
    # post pubblicitario, come talvolta capita a Impastamò): niente viene
    # nascosto o sostituito con un menu vecchio, si vede tutto quello che e'
    # stato pubblicato oggi.
    image_bytes_list = []
    for post in posts_oldest_first:
        img_bytes = post.get("image_bytes") or legacy.download_image(post["image_url"])

        if config.name == "Fantasia":
            img_bytes = legacy.crop_fantasia_chalkboard(img_bytes)
        elif config.name == "Le delizie di Michela":
            closure_signal = f"{post.get('text', '')} {post.get('image_alt', '')}"
            if legacy.looks_like_closure_notice(closure_signal):
                print(f"{config.name}: avviso chiusura rilevato, tengo immagine intera.")
                if not legacy.clean_post_text(post.get("text", "")):
                    alt_text = legacy.clean_facebook_alt_text(post.get("image_alt", ""))
                    if alt_text:
                        post["text"] = alt_text
            else:
                img_bytes = legacy.crop_michela_chalkboard(img_bytes)
        elif config.name == "Santoro (Castellana)":
            img_bytes = legacy.add_white_border(img_bytes, border=10)

        image_bytes_list.append(img_bytes)

    if len(image_bytes_list) > 1:
        print(f"{config.name}: {len(image_bytes_list)} post di oggi, li unisco in un unico pannello.")
        combined_bytes = legacy.combine_images_vertically(image_bytes_list)
    else:
        combined_bytes = image_bytes_list[0]

    combined_text = "\n\n".join(
        text
        for text in (legacy.clean_post_text(post.get("text", "")) for post in posts_oldest_first)
        if text
    )
    if not combined_text:
        # Se nessun post ha del testo (es. Michela), usiamo l'alt-text
        # ripulito del primo che ne ha uno.
        for post in posts_oldest_first:
            alt_text = legacy.clean_facebook_alt_text(post.get("image_alt", ""))
            if alt_text:
                combined_text = alt_text
                break

    image_bytes = legacy.add_date_footer(combined_bytes, most_recent_post.get("published_at", ""))
    legacy.save_image(image_bytes, config.output_image)

    return {
        "name": config.name,
        "image_bytes": image_bytes,
        "text": combined_text,
        "published_at": most_recent_post.get("published_at", ""),
        "published_at_raw": most_recent_post.get("published_at_raw", ""),
    }


def _extract_paneeco(config: RosticceriaConfig) -> Dict:
    existing = _existing(config)
    if existing and legacy.format_card_reference(existing.get("published_at", ""), True):
        print("Pane&Co: menu di oggi gia' presente, salto la verifica.")
        return existing

    print("Pane&Co: creo menu dal sito...")
    panel = legacy.extract_paneeco_menu()
    legacy.save_image(panel["image_bytes"], "Rosticceria_Pane_Co.jpg")
    return panel


def _extract_facebook_text(config: RosticceriaConfig) -> Dict:
    page_config = {
        "name": config.name,
        "display_name": config.label,
        "url": config.url,
        "required_terms": list(config.required_terms),
    }
    print(f"{config.name}: cerco menu testuale Facebook...")
    panel = _normalize_bollenti_panel(
        config, legacy.extract_first_facebook_text_menu(page_config)
    )
    legacy.save_image(panel["image_bytes"], f"Rosticceria_{legacy.safe_file_name(config.name)}.jpg")
    return panel


def _fallback_panel(config: RosticceriaConfig, exc: Exception) -> Dict:
    existing = _existing(config, require_today=False)
    if existing:
        if config.name == "Impastamò" and legacy.looks_like_closure_notice(
            existing.get("text", "")
        ):
            print(f"{config.name}: ultimo dato salvato e' solo un avviso, non lo mostro come menu.")
            return {
                "name": config.name,
                "error": "Menu non trovato: trovato solo un avviso di riapertura.",
            }
        print(f"{config.name}: errore sorgente, tengo ultimo menu salvato: {exc}")
        return existing
    return {"name": config.name, "error": str(exc)}


def extract_all() -> List[Dict]:
    panels: List[Dict] = []
    for config in ROSTICCERIE:
        try:
            if config.kind == "facebook_image":
                panels.append(_extract_facebook_image(config))
            elif config.kind == "facebook_text":
                panels.append(_extract_facebook_text(config))
            elif config.kind == "paneeco":
                panels.append(_extract_paneeco(config))
            else:
                raise RuntimeError(f"Sorgente non gestita: {config.kind}")
        except Exception as exc:
            panels.append(_fallback_panel(config, exc))
    return panels
