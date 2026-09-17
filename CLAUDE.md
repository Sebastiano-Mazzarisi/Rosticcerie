# Rosticcerie — contesto per Claude Code

Questo file viene letto automaticamente da Claude Code ogni volta che lo apri
in questa cartella: è il modo per "passare il testimone" tra una sessione
Cowork (cloud) e una sessione Claude Code locale su questo PC, senza doverlo
rispiegare ogni volta.

## Cos'è il progetto

Rosticceria.py scarica ogni giorno i menu di alcuni locali (foto + testo) da
Facebook (Rosticceria Fantasia, Cibarìa, Impastamò, Le delizie di Michela,
Santoro, Bollenti piatti) e dal sito di Pane & Co, e li pubblica come PWA
per iPhone su GitHub Pages.

- Repo: https://github.com/Sebastiano-Mazzarisi/Rosticcerie (branch main)
- Sito pubblicato: https://sebastiano-mazzarisi.github.io/Rosticcerie/output/rosticceria_ios/index.html

## IMPORTANTE: dove si modifica davvero il codice

Il vero "sorgente" dell'HTML/CSS/JS della PWA (compresi popup, layout,
stili) è **`Rosticceria_legacy.py`**, non i file generati.

Catena di chiamata: `Rosticceria.py` (entry point sottile) ->
`rosticcerie_clean/runner.py` (`import Rosticceria_legacy as legacy`) ->
`Rosticceria_legacy.py` (motore vero: scraping + template HTML/CSS/JS
incorporato).

Modificare direttamente `Rosticcerie.html` o `output/rosticceria_ios/*.html`
NON serve a nulla: l'automazione (vedi sotto) li rigenera da
`Rosticceria_legacy.py` entro 10 minuti, sovrascrivendo qualsiasi modifica
manuale. Qualsiasi fix va fatto in `Rosticceria_legacy.py`.

## Automazione GitHub Actions

`.github/workflows/rosticceria-ios.yml` esegue
`python Rosticceria.py --once --no-git` ogni 10 minuti dalle 5:00 alle 20:00
ora italiana (piu' un run di refresh a mezzanotte), e committa in automatico
`output/rosticceria_ios/` se cambia qualcosa. Questo significa che il
branch main riceve commit automatici molto spesso: prima di pushare, fare
sempre `git pull --rebase origin main`, e se il push finale fallisce per
modifiche remote nel frattempo, ripetere pull --rebase + push.

## Cartelle su questo PC

- `C:\Dropbox\Prog\Rosticcerie\Progetto\` — questa cartella: clone git live,
  collegato a GitHub, è l'unico riferimento da usare.
- `C:\Dropbox\Prog\Rosticcerie\Backup\<AAAA-MM-GG-HH-MM>\` — backup periodici.
- `C:\Dropbox\Prog\Fantasia\` — vecchia cartella con tentativi e versioni
  precedenti, superata, da non usare (Nino la cancellera' quando vuole).

## Attenzione: Dropbox e Git

Questa cartella e' sincronizzata con Dropbox. Un `git clone` (o altre
scritture massicce di file .pack) fatto direttamente qui puo' fallire con
"Permission denied" perche' Dropbox blocca i file appena scritti. Se serve
riclonare, farlo fuori da Dropbox (es. `C:\Temp\...`) e poi spostare la
cartella dentro `C:\Dropbox\Prog\Rosticcerie\`, oppure mettere in pausa la
sincronizzazione di Dropbox durante l'operazione.

## Menu di Michela dalla Storia Facebook (automatico dal 2026-09-13)

"Le delizie di Michela" pubblica il menu solo nelle Storie di Facebook, non
in un post: lo scraping headless della pipeline non riesce ad aprirle in
modo affidabile, quindi la voce in `rosticcerie_clean/config.py` era
stata disattivata e richiedeva una foto manuale ogni giorno via
`Importa_Michela.py`.

E' stata riattivata usando `ImportaStoriaMichela.py` (nuovo script, nella
stessa cartella), basato sulla tecnica validata a parte in
`C:\Dropbox\Prog\Prova\Stato\Stato.py`: Chrome con un profilo dedicato e
sessione autenticata (login manuale una sola volta), letto automaticamente
il visualizzatore delle storie. Va eseguito in continuo sul PC di Nino
(non in GitHub Actions, che non ha una sessione Facebook salvata):

- `python ImportaStoriaMichela.py --login` (una sola volta, o riusa il
  login gia' fatto per Stato.py: il profilo Chrome e' condiviso apposta)
- `python ImportaStoriaMichela.py` per il monitor continuo (ogni 10 minuti)

Ogni volta che trova una storia nuova, salva
`local_menus/michela_<data>.jpg` (stessa normalizzazione di
`Importa_Michela.py`, via `rosticcerie_clean/local_menu.import_image`) e fa
da solo commit + push (pull --rebase prima del push, come sotto). La
pipeline (`pipeline._extract_facebook_image_full`) legge quel file tramite
`local_panel()` e lo usa direttamente, senza toccare Facebook; se per un
giorno il file manca ancora, tenta come ripiego il vecchio scraping della
storia (`story_url` in config.py), con lo stesso limite di affidabilita' di
sempre.

## Notifica push (beep sul cellulare) quando esce un nuovo menu

Dal 17/09/2026, `save_publish_files()` in `Rosticceria_legacy.py` manda una
notifica push (con suono) tramite [ntfy.sh](https://ntfy.sh) ogni volta che
una rosticceria pubblica il menu del giorno — cioè quando l'immagine appena
estratta è DIVERSA da quella già pubblicata (confronto byte per byte prima
di sovrascrivere il file, non un semplice "il pannello è cambiato"): questo
evita notifiche ripetute per Michela, il cui pannello viene rigenerato a
ogni giro anche quando la foto locale importata è sempre la stessa.

Come funziona:

- Il "topic" ntfy (una stringa segreta che funziona come canale/password:
  chi la conosce può ricevere le notifiche) NON è scritto nel codice, perché
  questo repository è pubblico. Va letto dalla variabile d'ambiente
  `NTFY_TOPIC`.
- Su GitHub Actions è impostato come secret del repository (Settings →
  Secrets and variables → Actions → `NTFY_TOPIC`) e passato allo step
  "Estrai foto" in `.github/workflows/rosticceria-ios.yml` via `env:`.
- Se `NTFY_TOPIC` non è impostata, `notify_new_menus()` non fa nulla (solo
  un messaggio in log): la pubblicazione dei menu continua normalmente,
  semplicemente senza notifiche.
- Sul cellulare (iPhone di Nino): app **ntfy** dall'App Store, poi
  "Iscriviti a un argomento" con lo stesso valore di `NTFY_TOPIC`.
- La funzione è centralizzata in `save_publish_files()`, quindi copre TUTTE
  le rosticcerie (incluso il menu di Michela, sia quando arriva
  automaticamente da `ImportaStoriaMichela.py` sia quando viene importato a
  mano con `Importa_Michela.py`) senza bisogno di duplicare la logica altrove:
  qualunque strada porti a un nuovo file in `local_menus/`, la notifica parte
  comunque al giro successivo della pipeline principale, quando quel file
  viene letto e pubblicato come immagine finale.
- Se in futuro serve cambiare argomento ntfy (es. sospetto che sia trapelato),
  basta aggiornare il secret `NTFY_TOPIC` su GitHub e re-iscrivere l'app sul
  telefono al nuovo nome: nessuna modifica di codice necessaria.

## Stile di lavoro

- Messaggi di commit descrittivi, in italiano.
- Nino preferisce che i task (modifica + commit + push) vengano portati a
  termine in autonomia, senza dover eseguire lui i comandi — cosa che da
  Claude Code, girando localmente su questo PC con shell reale, e' possibile
  (a differenza di una sessione Cowork nel cloud, che puo' solo leggere/
  scrivere singoli file e non eseguire comandi su questo PC).
