from __future__ import annotations

from typing import Dict, List

import Rosticceria_legacy as legacy

from .config import ROSTICCERIE, RosticceriaConfig


def _existing(config: RosticceriaConfig, require_today: bool = True) -> Dict | None:
    return legacy.existing_publish_panel_if_today(config.name, require_today=require_today)


def _extract_facebook_image(config: RosticceriaConfig) -> Dict:
    existing = _existing(config)
    if existing and not config.force_refresh_today:
        print(f"{config.name}: foto di oggi gia' presente, salto la verifica.")
        return existing

    print(f"{config.name}: cerco immagine Facebook...")
    post = legacy.extract_first_facebook_image(
        config.url,
        prefer_active_closure=config.prefer_active_closure,
        skip_closure_notices=config.skip_closure_notices,
        skip_first_today_post=config.skip_first_today_post,
    )
    image_bytes = legacy.download_image(post["image_url"])

    if config.name == "Fantasia":
        image_bytes = legacy.crop_fantasia_chalkboard(image_bytes)
    elif config.name == "Le delizie di Michela":
        closure_signal = f"{post.get('text', '')} {post.get('image_alt', '')}"
        if legacy.looks_like_closure_notice(closure_signal):
            print(f"{config.name}: avviso chiusura rilevato, tengo immagine intera.")
            if not legacy.clean_post_text(post.get("text", "")):
                alt_text = legacy.clean_facebook_alt_text(post.get("image_alt", ""))
                if alt_text:
                    post["text"] = alt_text
        else:
            image_bytes = legacy.crop_michela_chalkboard(image_bytes)
    elif config.name == "Santoro (Castellana)":
        image_bytes = legacy.add_white_border(image_bytes, border=10)

    image_bytes = legacy.add_date_footer(image_bytes, post.get("published_at", ""))
    legacy.save_image(image_bytes, config.output_image)

    return {
        "name": config.name,
        "image_bytes": image_bytes,
        "text": post.get("text", ""),
        "published_at": post.get("published_at", ""),
        "published_at_raw": post.get("published_at_raw", ""),
    }


def _extract_paneeco(config: RosticceriaConfig) -> Dict:
    existing = _existing(config)
    if existing:
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
    panel = legacy.extract_first_facebook_text_menu(page_config)
    legacy.save_image(panel["image_bytes"], f"Rosticceria_{legacy.safe_file_name(config.name)}.jpg")
    return panel


def _fallback_panel(config: RosticceriaConfig, exc: Exception) -> Dict:
    existing = _existing(config, require_today=False)
    if existing:
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

