from dataclasses import dataclass, field
from typing import Literal


SourceKind = Literal["facebook_image", "facebook_text", "paneeco"]


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
    ),
    RosticceriaConfig(
        name="Cibària",
        url="https://www.facebook.com/cibaria.asporto",
        kind="facebook_image",
        output_image="Rosticceria_Cibaria.jpg",
        skip_closure_notices=True,
    ),
    RosticceriaConfig(
        name="Impastamò",
        url="https://www.facebook.com/profile.php?id=61560452176728",
        kind="facebook_image",
        output_image="Rosticceria_Impastamo.jpg",
        skip_closure_notices=True,
        photo_grid_first=False,
        force_refresh_today=True,
    ),
    RosticceriaConfig(
        name="Le delizie di Michela",
        url="https://www.facebook.com/profile.php?id=100045208848338",
        kind="facebook_image",
        output_image="Rosticceria_LeDelizieDiMichela.jpg",
        prefer_active_closure=True,
        skip_closure_notices=True,
    ),
    RosticceriaConfig(
        name="Santoro (Castellana)",
        url="https://www.facebook.com/santorogastronomia",
        kind="facebook_image",
        output_image="Rosticceria_Santoro.jpg",
        skip_closure_notices=True,
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
