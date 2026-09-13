# Manuale tecnico di `ImportaStoriaMichela.py`

## Obiettivo

"Le delizie di Michela" pubblica il menu del giorno solo nelle Storie di Facebook, non in un post. Lo script cattura automaticamente l'immagine di quella storia e la importa nel progetto Rosticcerie esattamente come farebbe `Importa_Michela.py` con una foto scattata a mano, ma senza bisogno di intervento quotidiano: scrive `local_menus/michela_<data>.jpg` e pubblica la modifica su GitHub con commit e push automatici.

Sostituisce il passaggio manuale (foto + `Importa_Michela.py`) descritto in `MENU_LOCALE.md`.

## Architettura

Lo script usa la stessa tecnica validata in `Stato.py` (`C:\Dropbox\Prog\Prova\Stato`):

* Python 3, Playwright, Google Chrome;
* un profilo Chrome dedicato e condiviso con `Stato.py`: `%LOCALAPPDATA%\StatoFacebook\chrome`. Se il login è già stato fatto per `Stato.py`, non serve rifarlo: la sessione Facebook salvata funziona per qualsiasi storia pubblica.

Il flusso di ogni controllo è:

1. apertura del profilo Facebook di Michela (id `100045208848338`);
2. apertura della storia (collegamento diretto se ancora valido, altrimenti clic su "Clicca per visualizzare la storia" trovato sul profilo);
3. ricerca dell'immagine visibile più grande nel visualizzatore;
4. download dell'immagine dal CDN Facebook;
5. validazione e normalizzazione tramite `rosticcerie_clean.local_menu.import_image` (stessa funzione usata dall'importazione manuale: EXIF, conversione RGB, JPEG qualità 95, rifiuta immagini troppo piccole o con data futura);
6. scrittura in `local_menus/michela_<data>.jpg`;
7. `git status` sul file: se è identico a quanto già pubblicato, nessun commit; altrimenti `git add` + `git commit` + `git pull --rebase origin main` + `git push` (fino a 3 tentativi);
8. attesa di circa 10 minuti e nuovo controllo.

Il file prodotto viene letto da `pipeline._extract_facebook_image_full` tramite `local_panel()`: se presente per la data odierna, la pipeline lo usa direttamente e non tenta lo scraping Facebook per Michela. La voce "Le delizie di Michela" in `rosticcerie_clean/config.py` è stata riattivata per questo.

## Comandi

Da eseguire dentro la cartella `Progetto` (usa gli stessi moduli di `Rosticceria.py`):

Primo accesso (solo se non è già stato fatto per `Stato.py`):

```
python ImportaStoriaMichela.py --login
```

Monitor continuo (ogni 10 minuti):

```
python ImportaStoriaMichela.py
```

Controllo singolo:

```
python ImportaStoriaMichela.py --once
```

Controllo singolo senza pubblicare su git (solo salvataggio locale):

```
python ImportaStoriaMichela.py --once --no-git
```

Forzare una data diversa da oggi (solo per verifiche):

```
python ImportaStoriaMichela.py --once --date 2026-09-13
```

Interruzione:

```
Ctrl+C
```

## Problemi noti / eredità da Stato.py

Vale tutto quanto già osservato per `Stato.py`: controlli anti-automazione se il login è avviato direttamente da Playwright (per questo il login resta manuale); il profilo Chrome dedicato deve essere chiuso prima di avviare il monitor; la sessione Facebook può scadere e richiedere un nuovo `--login`.

Il collegamento diretto alla storia (`KNOWN_STORY_URL` in cima al file) può scadere o cambiare: in tal caso lo script usa comunque, come ripiego, il clic su "Clicca per visualizzare la storia" trovato aprendo il profilo, quindi non serve intervenire con urgenza — ma aggiornare la costante quando è comodo evita quel passaggio extra ogni volta.

Se il download dell'immagine fallisce, lo script crea `local_menus/michela_diagnostica.png` per capire quale schermata Facebook ha restituito (esclusa dal repository via `.gitignore`).

Se `git pull --rebase` trova un conflitto reale, lo script si ferma con un errore invece di tentare una risoluzione automatica: va risolto a mano nella cartella `Progetto`.

## Cosa resta da fare

La verifica completa deve ancora essere eseguita mentre Michela ha una storia attiva con il menu del giorno, per confermare che l'immagine catturata sia quella giusta e che il commit/push automatico funzioni end-to-end sul sito pubblicato.
