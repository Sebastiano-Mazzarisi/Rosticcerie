# Nome.py: Rosticceria.py
# Data e ora ultima modifica: 08/09/2026 19:25
# Descrizione: Entry point pulito per estrarre e pubblicare i menu delle rosticcerie.
# File di input: cookies.txt
# File di output: output/rosticceria_ios/status.json, Rosticcerie.html, immagini jpg
# Parametri: --once, --show, --no-git

import argparse

from rosticcerie_clean.runner import run_loop, run_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Estrae e pubblica i menu delle rosticcerie.")
    parser.add_argument("--once", action="store_true", help="Esegue una sola estrazione e poi termina.")
    parser.add_argument("--show", action="store_true", help="Mostra anche la finestra locale a schermo intero.")
    parser.add_argument("--no-git", action="store_true", help="Non prova a pubblicare con GitHub/git.")
    args = parser.parse_args()

    if args.once:
        run_once(show=args.show, publish_to_git=not args.no_git)
    else:
        run_loop(show=args.show, publish_to_git=not args.no_git)


if __name__ == "__main__":
    main()
