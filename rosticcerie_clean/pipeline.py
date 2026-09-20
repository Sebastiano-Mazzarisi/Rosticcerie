from __future__ import annotations

from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import time

import Rosticceria_legacy as legacy

from .config import ROSTICCERIE, RosticceriaConfig
from .daily_posts import merge_today
from . import quick_check
from .local_menu import local_panel, parent_menu_panel


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


def _extract_facebook_image(config: RosticceriaConfig, force: bool = False) -> Dict:
    if config.local_slug and local_panel(config.local_slug, config.name):
        return _extract_facebook_image_full(config)
    saved = _existing(config, require_today=False)
    # Le storie hanno una sorgente separata: non inferirne lo stato dal feed.
    # Con force=True si salta la verifica rapida e si esegue sempre la scansione completa.
    signature = None if config.story_url else quick_check.probe(config)
    if not force and saved and quick_check.unchanged(config.name, signature):
        print(f"{config.name}: verifica rapida, nessuna variazione; riuso i dati salvati.")
        return saved
    panel = _extract_facebook_image_full(config)
    if panel.get("image_bytes") and not panel.get("error"):
        quick_check.remember(config.name, signature)
    return panel


def _extract_facebook_image_full(config: RosticceriaConfig) -> Dict:
    if config.local_slug:
        supplied = local_panel(config.local_slug, config.name)
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


def _extract_paneeco(config: RosticceriaConfig, force: bool = False) -> Dict:
    existing = _existing(config)
    if not force and existing and legacy.format_card_reference(existing.get("published_at", ""), True):
        print("Pane&Co: menu di oggi gia' presente, salto la verifica.")
        return existing

    print("Pane&Co: creo menu dal sito...")
    panel = legacy.extract_paneeco_menu()
    legacy.save_image(panel["image_bytes"], "Rosticceria_Pane_Co.jpg")
    return panel


def _extract_local_menu(config: RosticceriaConfig) -> Dict:
    """Rosticcerie senza alcuna fonte automatica (es. Aufer, il cui menu e'
    solo nelle Storie di Instagram, illeggibili senza login): il pannello
    viene esclusivamente dal file importato a mano in local_menus/. Se manca
    quello di oggi, si solleva un errore cosi' _fallback_panel() tiene
    l'ultimo menu salvato (stesso comportamento delle altre sorgenti)."""
    panel = local_panel(config.local_slug, config.name)
    if panel:
        print(f"{config.name}: uso il menu locale di oggi.")
        legacy.save_image(panel["image_bytes"], config.output_image)
        return panel
    raise RuntimeError(f"Nessun menu locale importato oggi per {config.name}.")


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


def _extract_timed(config: RosticceriaConfig, force: bool = False):
    started = time.perf_counter()
    outcome = "ok"
    try:
        # Priorita' 1: immagine manuale nella cartella Menu/ (AAAA-MM-GG-Nome.jpg).
        # Se presente, sovrascrive qualsiasi sorgente automatica.
        manual = parent_menu_panel(config.menu_slug, config.name) if config.menu_slug else None
        if manual:
            if config.output_image:
                legacy.save_image(manual["image_bytes"], config.output_image)
            panel = manual
        elif config.kind == "facebook_image":
            panel = _extract_facebook_image(config, force=force)
        elif config.kind == "facebook_text":
            panel = _extract_facebook_text(config)
        elif config.kind == "paneeco":
            panel = _extract_paneeco(config, force=force)
        elif config.kind == "local_menu":
            panel = _extract_local_menu(config)
        else:
            raise RuntimeError(f"Sorgente non gestita: {config.kind}")
    except Exception as exc:
        panel = _fallback_panel(config, exc)
        outcome = "error" if panel.get("error") else "fallback"
    elapsed = time.perf_counter() - started
    print(f"TEMPI {config.name}: {elapsed:.1f}s ({outcome})", flush=True)
    return panel, {"name": config.name, "seconds": round(elapsed, 2), "outcome": outcome}


def extract_all(force: bool = False) -> List[Dict]:
    started = time.perf_counter()
    # Ogni estrazione crea e chiude Playwright nel proprio thread.
    # Due sessioni al massimo, senza condividere browser, context o page.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="rosticceria") as pool:
        results = list(pool.map(lambda c: _extract_timed(c, force=force), ROSTICCERIE))
    elapsed = time.perf_counter() - started
    timings = [timing for _, timing in results]
    report = {
        "updated_at": legacy.rome_now().isoformat(),
        "workers": 2,
        "elapsed_seconds": round(elapsed, 2),
        "sum_restaurant_seconds": round(sum(item["seconds"] for item in timings), 2),
        "restaurants": timings,
    }
    print(f"TEMPI estrazione completa: {elapsed:.1f}s con 2 sessioni", flush=True)
    try:
        target = Path(legacy.publish_dir()) / "extraction-timings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"Riepilogo tempi non salvato: {exc}")
    return [panel for panel, _ in results]
