# Manuale d'uso: Pulisci_Repository.py

## A cosa serve

Cancella dal repository i file che gli script del progetto Rosticcerie
scrivono automaticamente ma non rileggono mai più: soprattutto le foto
d'archivio dei menu passati, che nel tempo hanno fatto crescere la
cartella `output/rosticceria_ios` (e di conseguenza `.git`) di decine di
megabyte, rendendo i commit più lenti.

Non tocca nessun file "corrente": le foto oggi visibili sul sito, i testi,
i manifest, l'HTML, le icone, l'audio e i loghi restano sempre al loro
posto.

## Come si usa

Il file va lanciato dalla cartella `Progetto` (la stessa in cui si trova
`Rosticceria_legacy.py`), con un doppio clic o da riga di comando:

```
python Pulisci_Repository.py
```

Lanciato così, **non cancella nulla**: mostra solo un'anteprima di cosa
verrebbe cancellato, con l'elenco dei file e lo spazio totale che si
libererebbe. Utile per controllare prima di procedere.

Per cancellare davvero:

```
python Pulisci_Repository.py --applica
```

Anche in questo caso lo script chiede una conferma esplicita (`s` per
confermare) prima di cancellare qualsiasi cosa, mostrando di nuovo
l'elenco completo.

Dopo la cancellazione, lancia come sempre `commit_e_push.bat`: senza
quel passaggio i file spariscono solo dal tuo PC, ma restano ancora
presenti su GitHub finché non fai il commit e il push.

## Cosa cancella, e perché è sicuro

- **`output/rosticceria_ios/<Nome>_AAAAMMGG_OOMM.jpg`** — la copia
  d'archivio con data e ora nel nome che `Rosticceria_legacy.py` scrive
  a ogni aggiornamento (funzione `save_publish_files`), oltre alla foto
  "corrente" senza data. Il sito e lo script leggono sempre e solo la
  foto senza data (es. `Fantasia.jpg`): quella con la data non viene mai
  più riletta da nessuna parte. Vengono cancellate **tutte**, qualunque
  sia la loro data.

- **`local_menus/<slug>_<data>.jpg`** con una data diversa da oggi — il
  file usato quando il menu va importato a mano (Michela, Aufer).
  `rosticcerie_clean/local_menu.py` legge solo il file della data
  odierna, quindi uno con una data passata non servirà mai più. Il file
  `local_menus/michela_diagnostica.png` non viene toccato (non è un file
  di questo tipo ed è comunque già escluso da git).

- **`Menu/<data>-<Nome>.jpg`** con una data diversa da oggi — stessa
  logica del punto precedente, per i menu del "genitore" caricati a
  mano in questa cartella.

- **`rosticcerie_clean/local_menu-1.py`** — un doppione di
  `local_menu.py` rimasto per errore (probabilmente una copia salvata
  per sbaglio con un altro nome). Lo script lo cancella solo se il suo
  contenuto è identico byte per byte all'originale, quindi non rischia
  di cancellare qualcosa di diverso.

- **Cartelle `__pycache__` e file `.pyc`** — file che Python crea da
  solo per velocizzare l'esecuzione e ricrea automaticamente quando
  servono di nuovo. Sono già esclusi dal repository dal file
  `.gitignore`, quindi cancellarli non cambia nulla su GitHub: libera
  solo un po' di spazio sul disco.

- **`debug_facebook_feed_*.png`** — screenshot salvati dallo scraper
  quando analizza Facebook, usati solo per capire eventuali problemi al
  momento in cui vengono creati. Non sono richiamati da nessuna parte
  del sito o del codice.

## Cosa NON cancella

Le foto correnti (`output/rosticceria_ios/<Nome>.jpg` senza data), i
file di testo/JSON/manifest/HTML del sito, le icone, `Rosticcerie.mp3`,
i loghi (`Logo-*.jpg`) e qualunque file in `local_menus/`/`Menu/` datato
con la giornata odierna.

## Una cosa importante da sapere

Questo script pulisce la cartella di lavoro, ma **non riduce lo spazio
già occupato dalla cronologia di git** (la cartella `.git`, che oggi è
la parte più pesante del repository): git conserva per sempre ogni
versione mai committata di un file, quindi le foto d'archivio già
inviate a GitHub in passato restano nella cronologia anche dopo questa
pulizia. Ridurre anche quello richiede un'operazione diversa e più
delicata (riscrivere la cronologia con `git filter-repo` o BFG, seguita
da un push forzato): chiedi pure se vuoi valutarla a parte.
