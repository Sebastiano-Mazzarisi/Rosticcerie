# Menu locale di Michela

Nel checkout aggiornato del progetto:

```powershell
python Importa_Michela.py "C:\percorso\menu.jpg" --date 2026-09-10
```

La data va letta sul menu e indicata esplicitamente. Usare una foto leggibile del solo menu, non uno screenshot di login o dell'intero browser. Lo script valida il formato immagine, non il suo contenuto.

Pubblicare il file creato in `local_menus/` con git. Il push attiva il workflow anche fuori fascia oraria. Michela usa il file solo nella data indicata, prima di contattare Facebook; dal giorno successivo torna alla ricerca normale e all'eventuale ultimo menu salvato con la sua data originale. Gli altri locali seguono la pipeline esistente.

Questa funzione non acquisisce automaticamente le storie. Il comando Chrome con la sola porta 9222 non abilita il debug sul profilo predefinito da Chrome 136. Un profilo dedicato richiede una propria autenticazione; non risolve automaticamente il blocco della verifica in due passaggi.
