from dataclasses import dataclass, field
from typing import Literal


SourceKind = Literal["facebook_image", "facebook_text", "paneeco", "local_menu"]


@dataclass(frozen=True)
class RosticceriaConfig:
    name: str
    url: str
    kind: SourceKind
    output_image: str = ""
    display_name: str = ""
    required_terms: tuple[str, ...] = field(default_factory=tuple)
    prefer_active_closure: bool = False
    skip_closure_notices: bool = False
    skip_first_today_post: bool = False
    photo_grid_first: bool = False
    force_refresh_today: bool = False
    prefer_facebook_date: bool = False
    story_url: str = ""
    # Slug fisso per il menu importato a mano in local_menus/<slug>_<data>.jpg
    # (vedi rosticcerie_clean/local_menu.py). Usato sia da "Le delizie di
    # Michela" (ripiego se lo scraping delle Storie Facebook fallisce) sia
    # da rosticcerie con kind="local_menu" (nessuna fonte automatica).
    local_slug: str = ""
    # Nome usato nella cartella Menu/ affiancata a Progetto/ per i file
    # AAAA-MM-GG-{menu_slug}.jpg salvati manualmente dall'utente.
    # Se il file e' presente, viene usato con priorita' assoluta su qualsiasi
    # sorgente automatica (Facebook, Instagram, sito).
    menu_slug: str = ""

    @property
    def label(self) -> str:
        return self.display_name or self.name


ROSTICCERIE: list[RosticceriaConfig] = [
    RosticceriaConfig(
        name="Fantasia",
        url="https://www.facebook.com/RosticceriaFantasia",
        kind="facebook_image",
        output_image="Rosticceria_Fantasia.jpg",
        skip_closure_notices=True,
        prefer_facebook_date=True,
        menu_slug="Fantasia",
    ),
    RosticceriaConfig(
        name="Cibària",
        url="https://www.facebook.com/cibaria.asporto",
        kind="facebook_image",
        output_image="Rosticceria_Cibaria.jpg",
        skip_closure_notices=True,
        menu_slug="Cibaria",
    ),
    RosticceriaConfig(
        name="Impastamò",
        url="https://www.facebook.com/profile.php?id=61560452176728",
        kind="facebook_image",
        output_image="Rosticceria_Impastamo.jpg",
        skip_closure_notices=True,
        photo_grid_first=False,
        force_refresh_today=True,
        menu_slug="Impastamo",
    ),
    # Michela pubblica il menu solo nelle Storie di Facebook, che
    # l'automazione headless della pipeline non riesce ad aprire in modo
    # affidabile (Facebook limita/renderizza diversamente le sessioni
    # automatizzate). Riattivata il 2026-09-13: ImportaStoriaMichela.py, in
    # esecuzione locale con una sessione Chrome autenticata (stessa tecnica
    # validata in Stato.py), scrive ogni giorno local_menus/michela_<data>.jpg;
    # local_panel() lo trova e la pipeline lo usa direttamente (vedi
    # pipeline._extract_facebook_image_full), senza toccare Facebook. Il
    # story_url qui sotto resta come ripiego, tentato solo se quel file per
    # oggi manca ancora: resta soggetto allo stesso limite di affidabilita'.
    RosticceriaConfig(
        name="Le delizie di Michela",
        url="https://www.facebook.com/profile.php?id=100045208848338",
        kind="facebook_image",
        output_image="Rosticceria_LeDelizieDiMichela.jpg",
        story_url="https://www.facebook.com/stories/186699229513704/",
        force_refresh_today=True,
        prefer_active_closure=True,
        skip_closure_notices=True,
        local_slug="michela",
        menu_slug="Michela",
    ),
    # Aufer pubblica il menu solo nelle Storie di Instagram (anche quelle "in
    # evidenza", permanenti): Instagram le nasconde del tutto a chi non e'
    # loggato, quindi non esiste una fonte automatica anonima come per le
    # altre rosticcerie. Per ora il menu va importato a mano ogni giorno con
    # Importa_Aufer.py (stesso meccanismo di Importa_Michela.py); in futuro
    # si potra' automatizzare con una sessione Instagram autenticata dedicata,
    # sullo stesso modello di ImportaStoriaMichela.py.
    RosticceriaConfig(
        name="Aufer",
        url="https://www.instagram.com/aufergastronomia/",
        kind="local_menu",
        output_image="Rosticceria_Aufer.jpg",
        local_slug="aufer",
        menu_slug="Aufer",
    ),
    RosticceriaConfig(
        name="Santoro (Castellana)",
        url="https://www.facebook.com/santorogastronomia",
        kind="facebook_image",
        output_image="Rosticceria_Santoro.jpg",
        skip_closure_notices=True,
        menu_slug="Santoro",
    ),
    RosticceriaConfig(
        name="Pane & Co",
        url="https://www.paneeco.it/menu",
        kind="paneeco",
    ),
    RosticceriaConfig(
        name="Bollenti piatti",
        display_name="Bollenti piatti",
        url="https://www.facebook.com/BollentiPiatti",
        kind="facebook_text",
        required_terms=("secondi piatti",),
    ),
]
