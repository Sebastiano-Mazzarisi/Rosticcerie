"""Importa una foto verificata del menu, senza accedere a Facebook."""
import argparse
from datetime import date
from pathlib import Path
from rosticcerie_clean.local_menu import import_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Foto del solo menu, gia' verificata")
    parser.add_argument("--date", required=True, type=date.fromisoformat,
                        help="Data scritta sul menu, nel formato YYYY-MM-DD")
    args = parser.parse_args()
    path = import_image(args.image, args.date)
    print(f"Menu importato: {path}")
    print("Pubblica questo file in local_menus su GitHub per attivare l'aggiornamento.")


if __name__ == "__main__":
    main()
