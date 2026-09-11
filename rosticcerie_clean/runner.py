from __future__ import annotations

import time

import Rosticceria_legacy as legacy

from .pipeline import extract_all
from .counters import snapshot_if_due


def run_once(show: bool = False, publish_to_git: bool = True) -> None:
    snapshot_if_due()
    panels = extract_all()
    output_dir = legacy.save_publish_files(panels)
    print(f"File per iOS aggiornati in: {output_dir}")

    if show:
        legacy.show_fullscreen(panels)

    if publish_to_git:
        legacy.git_publish_if_available(output_dir)


def run_loop(show: bool = False, publish_to_git: bool = True) -> None:
    while True:
        now = legacy.rome_now()
        next_time = legacy.next_run_time(now)
        wait_seconds = max(0, (next_time - now).total_seconds())
        print(f"Prossima esecuzione: {next_time:%d/%m/%Y %H:%M:%S}")
        time.sleep(wait_seconds)
        run_once(show=show, publish_to_git=publish_to_git)

