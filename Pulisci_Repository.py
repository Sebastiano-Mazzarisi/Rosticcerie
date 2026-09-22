"""Pulisce dal repository Rosticcerie i file generati automaticamente che
non servono piu' a nessuno: le foto d'archivio dei menu passati (scritte
da save_publish_files() e mai piu' rilette da nessuno script) e qualche
altro scarto minore. Per i dettagli e le spiegazioni complete vedi
MANUALE_Pulisci_Repository.md nella stessa cartella.

Uso (da lanciare dentro la cartella Progetto, o comunque nella stessa
cartella in cui si trova questo file):

    python Pulisci_Repository.py             mostra solo un'anteprima,
                                              non cancella nulla
    python Pulisci_Repository.py --applica   cancella davvero (chiede
                                              conferma prima di procedere)

Dopo aver cancellato, ricordati di lanciare come sempre commit_e_push.bat
per salvare la sparizione di questi file anche su git/GitHub.
"""
import argparse
import re
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def formatta_dimensione(num_byte: int) -> str:
    valore = float(num_byte)
    for unita in ("B", "KB", "MB", "GB"):
        if valore < 1024 or unita == "GB":
            return f"{valore:.1f} {unita}"
        valore /= 1024
    return f"{valore:.1f} GB"


def trova_foto_archivio_output():
    """output/rosticceria_ios/<Nome>_AAAAMMGG_OOMM.jpg: copia storica
    scritta da save_publish_files() a ogni aggiornamento e mai piu' riletta
    da nessuno (il sito e lo script usano solo <Nome>.jpg, senza data).
    Sicura da cancellare sempre, qualunque sia la data."""
    cartella = BASE_DIR / "output" / "rosticceria_ios"
    pattern = re.compile(r"^.+_\d{8}_\d{4}\.jpg$", re.IGNORECASE)
    if not cartella.is_dir():
        return []
    return [p for p in cartella.iterdir() if p.is_file() and pattern.match(p.name)]


def trova_menu_scaduti(nome_cartella: str, pattern: "re.Pattern", indice_data: int, oggi: date):
    """File di local_menus/ o Menu/ con una data diversa da oggi:
    rosticcerie_clean/local_menu.py legge solo il file della data odierna,
    quindi uno con una data passata non verra' mai piu' usato."""
    cartella = BASE_DIR / nome_cartella
    if not cartella.is_dir():
        return []
    scaduti = []
    for p in cartella.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if not m:
            continue
        try:
            data_file = date.fromisoformat(m.group(indice_data))
        except ValueError:
            continue
        if data_file < oggi:
            scaduti.append(p)
    return scaduti


def trova_duplicato_local_menu():
    """rosticcerie_clean/local_menu-1.py: copia di local_menu.py rimasta per
    errore (il trattino nel nome le impedisce persino di essere importata
    da Python). Viene cancellato solo se e' davvero identico byte per byte
    all'originale, per sicurezza."""
    originale = BASE_DIR / "rosticcerie_clean" / "local_menu.py"
    duplicato = BASE_DIR / "rosticcerie_clean" / "local_menu-1.py"
    if duplicato.is_file() and originale.is_file() and duplicato.read_bytes() == originale.read_bytes():
        return [duplicato]
    return []


def trova_pycache():
    """Cartelle __pycache__ e file .pyc: gia' esclusi dal repository dal
    .gitignore, ma occupano spazio su disco inutilmente. Python li ricrea
    da solo alla prossima esecuzione, quindi cancellarli non rompe nulla."""
    cartelle = [p for p in BASE_DIR.rglob("__pycache__") if p.is_dir()]
    gia_incluse = set(cartelle)
    sciolti = [
        p for p in BASE_DIR.rglob("*.pyc")
        if p.is_file() and not any(genitore in gia_incluse for genitore in p.parents)
    ]
    return cartelle + sciolti


def trova_debug_facebook():
    """debug_facebook_feed_*.png nella cartella principale: screenshot di
    diagnostica dello scraper Facebook, non richiamati da nessuna parte del
    sito o del codice."""
    pattern = re.compile(r"^debug_facebook_feed.*\.png$", re.IGNORECASE)
    return [p for p in BASE_DIR.iterdir() if p.is_file() and pattern.match(p.name)]


def elenco_file(percorsi):
    """Espande le cartelle nell'elenco in una lista piatta dei file che
    contengono, per poterli contare/pesare; i file singoli restano com'erano."""
    file_piatti = []
    for p in percorsi:
        if p.is_dir():
            file_piatti.extend(f for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            file_piatti.append(p)
    return file_piatti


def cancella(percorsi):
    import shutil
    for p in percorsi:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()


GRUPPI = [
    ("Foto d'archivio in output/rosticceria_ios (mai rilette da nessuno)",
     lambda oggi: trova_foto_archivio_output()),
    ("File scaduti in local_menus/ (data diversa da oggi)",
     lambda oggi: trova_menu_scaduti(
         "local_menus", re.compile(r"^([a-z0-9]+)_(\d{4}-\d{2}-\d{2})\.jpg$", re.IGNORECASE), 2, oggi)),
    ("File scaduti in Menu/ (data diversa da oggi)",
     lambda oggi: trova_menu_scaduti(
         "Menu", re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.(jpg|jpeg|png)$", re.IGNORECASE), 1, oggi)),
    ("Duplicato rosticcerie_clean/local_menu-1.py",
     lambda oggi: trova_duplicato_local_menu()),
    ("Cache Python (__pycache__, *.pyc) - gia' esclusa da git",
     lambda oggi: trova_pycache()),
    ("Screenshot di diagnostica debug_facebook_feed_*.png",
     lambda oggi: trova_debug_facebook()),
]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--applica", action="store_true",
        help="Cancella davvero i file (senza questa opzione mostra solo un'anteprima)")
    args = parser.parse_args()

    oggi = date.today()
    print(f"Cartella analizzata: {BASE_DIR}")
    print(f"Data di oggi: {oggi.isoformat()}\n")

    risultati = [(titolo, funzione(oggi)) for titolo, funzione in GRUPPI]

    totale_file = 0
    totale_byte = 0
    for titolo, percorsi in risultati:
        if not percorsi:
            continue
        file_piatti = elenco_file(percorsi)
        dim = sum(f.stat().st_size for f in file_piatti)
        totale_byte += dim
        totale_file += len(file_piatti)
        print(f"- {titolo}: {len(file_piatti)} file, {formatta_dimensione(dim)}")
        for p in sorted(percorsi)[:10]:
            print(f"    {p.relative_to(BASE_DIR)}")
        if len(percorsi) > 10:
            print(f"    ... e altri {len(percorsi) - 10} elementi")
        print()

    if totale_file == 0:
        print("Niente da cancellare: il repository e' gia' pulito.")
        return

    print(f"TOTALE: {totale_file} file, {formatta_dimensione(totale_byte)}\n")

    if not args.applica:
        print("Questa e' solo un'ANTEPRIMA: nessun file e' stato cancellato.")
        print("Per cancellare davvero, rilancia con:  python Pulisci_Repository.py --applica")
        return

    risposta = input(
        f"Confermi la cancellazione di {totale_file} file "
        f"({formatta_dimensione(totale_byte)})? [s/N] ")
    if risposta.strip().lower() not in ("s", "si", "sì", "y", "yes"):
        print("Annullato: nessun file e' stato cancellato.")
        return

    for _, percorsi in risultati:
        cancella(percorsi)

    print(f"\nFatto: cancellati {totale_file} file ({formatta_dimensione(totale_byte)}).")
    print("Ricordati di lanciare commit_e_push.bat per salvare la sparizione")
    print("di questi file anche su git/GitHub (altrimenti restano cancellati")
    print("solo su questo PC).")


if __name__ == "__main__":
    main()
