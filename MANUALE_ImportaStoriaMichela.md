# Manuale tecnico di `ImportaStoriaMichela.py`

## Obiettivo

"Le delizie di Michela" pubblica il menu del giorno solo nelle Storie di Facebook, non in un post. Lo script cattura automaticamente l'immagine di quella storia e la importa nel progetto Rosticcerie esattamente come farebbe `Importa_Michela.py` con una foto scattata a mano, ma senza bisogno di intervento quotidiano: scrive `local_menus/michela_<data>.jpg` e pubblica la modifica su GitHub con commit e push automatici.

Sostituisce il passaggio manuale (foto + `Importa_Michela.py`) descritto in `MENU_LOCALE.md`.

## Architettura

Lo script usa la stessa tecnica validata in `Stato.py` (`C:\Dropbox\Prog\Prova\Stato`):

* Python 3, Playwright, Google Chrome;
* un profilo Chrome dedicato e condiviso con `Stato.py`: `%LOCALAPPDATA%\StatoFacebook\chrome`. Se il login è già stato fatto per `Stato.py`, non serve rifarlo: la sessione Facebook salvata funziona per qualsiasi storia pubblica.

Il flusso di ogni controllo è:

1. se per la data di oggi è già stata scoperta e messa in cache (in memoria, solo per l'esecuzione corrente) l'URL della storia corrente, si riparte direttamente da lì; altrimenti si apre il profilo Facebook di Michela (id `100045208848338`) e si clicca su "Clicca per visualizzare la storia"/l'avatar della storia per raggiungere quella attualmente attiva (`discover_current_story()`); se l'URL in cache risulta scaduto, viene scartato e si ripassa subito dal profilo nello stesso controllo;
2. verifica che la storia sia effettivamente disponibile e recente (non un placeholder scaduto né una foto "in evidenza" vecchia);
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

**Correzione del 17/09/2026 — bug del link fisso alla storia.** Fino al 16/09/2026 lo script navigava direttamente a un URL di storia salvato in `KNOWN_STORY_URL` (`.../stories/186699229513704/`), nell'ipotesi che fosse l'identificativo stabile del "vassoio storie" di Michela, sempre risolto nella storia attualmente attiva. Quell'ipotesi era sbagliata: l'URL era in realtà legato a UNA storia precisa, e come ogni storia Facebook scade dopo ~24h. Il 16/09/2026 lo script sembrava funzionare solo per coincidenza (verificato a ridosso della pubblicazione di quel giorno). Il 17/09/2026 Michela aveva già pubblicato il menu (confermato da una foto reale della lavagna), ma lo script continuava a fallire: quel link ormai scaduto mostrava permanentemente "Questa storia non è più disponibile", anche se nel frattempo esisteva una storia nuova con un URL diverso — ogni pubblicazione riceve con ogni probabilità un proprio ID, non riusabile il giorno dopo.

**Correzione applicata**: `KNOWN_STORY_URL` è stato eliminato. Lo script ora riscopre sempre la storia corrente passando dal profilo di Michela (stessa logica di clic già usata come ripiego), e la tiene in una cache in memoria (`STORY_CACHE`) valida solo per la giornata/esecuzione corrente: così i controlli successivi ogni 10 minuti restano rapidi (non serve ripassare dal profilo ogni volta), ma non si rischia più di restare bloccati su un link di ieri. Se l'URL in cache smette di funzionare durante il giorno (storia rimossa o sostituita), lo script se ne accorge da solo e ripassa subito dal profilo nello stesso controllo, senza aspettare altri 10 minuti.

**Diagnosi del fallimento dell'11:21 del 16/09/2026** (per riferimento storico): la schermata diagnostica mostrava "Questa storia non è più disponibile" — non un link rotto, ma il fatto che a quell'ora Michela non aveva ancora pubblicato il menu (l'ultima storia era scaduta dopo le 24h). Lo script riconosce esplicitamente questo messaggio (funzione `story_unavailable()`) e lo tratta come "nessuna storia ancora", non come errore: registra un messaggio e riprova al controllo successivo, invece di fermarsi con un'eccezione e scrivere `michela_diagnostica.png`. Il fallimento del 17/09/2026 era invece il bug del link fisso descritto sopra, ora corretto.

Se il download dell'immagine fallisce per un motivo diverso (es. nessuna immagine trovata pur con la storia aperta), lo script crea comunque `local_menus/michela_diagnostica.png` per capire quale schermata Facebook ha restituito (esclusa dal repository via `.gitignore`).

Se `git pull --rebase` trova un conflitto reale, lo script si ferma con un errore invece di tentare una risoluzione automatica: va risolto a mano nella cartella `Progetto`.

## Eseguirlo automaticamente senza tenere un terminale aperto

Lo script si autocorregge già da solo se lasciato in esecuzione continua (senza `--once`): ogni 10 minuti ricontrolla, e appena Michela pubblica il menu lo importa. Il problema pratico è che questo richiede un terminale aperto tutto il giorno sul PC.

Per renderlo davvero "automatico" senza doverci pensare, conviene usare **Utilità di pianificazione di Windows** (Task Scheduler) per eseguire `python ImportaStoriaMichela.py --once` ogni 10 minuti dalle 5:00 alle 20:00, sullo stesso orario dell'automazione principale su GitHub Actions:

1. Apri "Utilità di pianificazione" (cerca "Utilità di pianificazione" nel menu Start).
2. "Crea attività..." (non "Crea attività di base", per avere più opzioni).
3. Scheda **Generale**: nome "Importa Storia Michela"; seleziona "Esegui indipendentemente dalla connessione dell'utente" solo se necessario (di norma non serve).
4. Scheda **Trigger**: "Nuovo...", ripeti "Giornalmente", poi nelle opzioni avanzate spunta "Ripeti l'attività ogni: 10 minuti" con durata "1 giorno", e imposta l'ora di inizio alle 5:00 (se vuoi limitarla anche alle 20:00, serve un secondo trigger che disabilita/ferma, oppure lascia che giri tutto il giorno: uno `--once` che trova "nessuna storia" non fa danni, semplicemente non pubblica nulla).
5. Scheda **Azioni**: "Nuova...", Programma/script: il percorso completo di `python.exe` (quello con Playwright installato); Aggiungi argomenti: `ImportaStoriaMichela.py --once`; Inizia in: `C:\Dropbox\Prog\Rosticcerie\Progetto`.
6. Scheda **Condizioni**: togli la spunta da "Avvia l'attività solo se il computer è collegato alla rete elettrica" se il PC è un portatile che usi anche a batteria.
7. Salva. La prima volta assicurati di aver già fatto `python ImportaStoriaMichela.py --login` manualmente (sessione condivisa con `Stato.py`), altrimenti l'attività pianificata troverà la schermata di login e fallirà silenziosamente (va controllato ogni tanto finché non scade la sessione).

Nota: l'attività pianificata apre comunque una finestra di Chrome visibile (lo script non gira headless, per evitare i controlli anti-bot di Facebook), quindi la vedrai comparire e sparire ogni 10 minuti. È normale.

## Cosa resta da fare

Verificata il 16/09/2026 la cattura end-to-end con una storia realmente attiva (immagine del menu trovata, indicatore "1 h" riconosciuto come recente), ma con il bug del link fisso descritto sopra (corretto il 17/09/2026, non ancora riverificato dal vivo). Al prossimo `--once` (o al prossimo giro del monitor continuo) con una storia di Michela attiva, controllare che:

* lo script trovi la storia passando dal profilo (nessun riferimento a un ID salvato);
* l'immagine venga importata e pubblicata correttamente;
* i controlli successivi nello stesso giorno restino rapidi (uso della cache, senza ripassare dal profilo ogni volta) — visibile nel log solo indirettamente: se non compare più "Account riconosciuto, ma nessuna storia attiva" a ogni giro dopo la prima pubblicazione, la cache sta funzionando.

Se si vuole l'automazione completa, resta da configurare l'attività pianificata descritta sopra.
