"""Cattura automaticamente il menu del giorno di "Le delizie di Michela" dalla
sua storia Facebook e lo pubblica come farebbe Importa_Michela.py, ma senza
bisogno di una foto scattata a mano ogni giorno.

Michela pubblica il menu solo nelle Storie di Facebook (non in un post), e
l'automazione headless della pipeline principale non riesce ad aprirle in
modo affidabile: Facebook limita/renderizza diversamente le sessioni
automatizzate senza una vera sessione autenticata. Questo script risolve lo
stesso problema con la tecnica validata in Stato.py
(C:\\Dropbox\\Prog\\Prova\\Stato): Chrome con un profilo dedicato e sessione
salvata, login manuale una sola volta, poi lettura automatica dell'immagine
piu' grande visibile nel visualizzatore delle storie.

L'immagine catturata viene validata e normalizzata con la stessa funzione che
usa Importa_Michela.py (rosticcerie_clean.local_menu.import_image), quindi
scritta in local_menus/michela_<data>.jpg: il resto della pipeline
(local_menu.local_panel, la voce "Le delizie di Michela" in config.py, una
volta riattivata) la legge esattamente come un'importazione manuale.

Ogni storia Facebook ha un proprio URL che scade con lei (circa 24h) e non e'
riutilizzabile il giorno dopo: lo script non salva quindi nessun ID fisso,
ma riscopre la storia corrente passando dal profilo di Michela ogni volta
che serve (primo controllo della giornata, o se la storia trovata prima
smette di funzionare), tenendola poi in cache solo per il resto della
giornata (vedi STORY_CACHE piu' sotto).

Va eseguito da dentro questa cartella (Progetto), perche' importa i moduli
rosticcerie_clean e Rosticceria_legacy usati anche da Rosticceria.py.

Installazione: python -m pip install -r requirements.txt
Primo accesso: python ImportaStoriaMichela.py --login
Controllo singolo: python ImportaStoriaMichela.py --once
Monitor continuo (ogni 10 minuti): python ImportaStoriaMichela.py
Interruzione: Ctrl+C
"""
from __future__ import annotations

from pathlib import Path
from datetime import date
from urllib.parse import urlparse
import argparse
import os
import re
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent  # cartella Progetto: qui vivono i moduli rosticcerie_clean

PROFILE_URL = "https://www.facebook.com/profile.php?id=100045208848338"
# CORRETTO IL 17/09/2026 - l'ipotesi precedente era sbagliata: si pensava che
# l'URL di una storia specifica (es. ".../stories/186699229513704/") fosse un
# identificativo stabile del "vassoio storie" di Michela, sempre risolto
# nella storia attualmente attiva. In realta' quell'ID e' legato a UNA
# storia precisa e scade con lei (~24h). Il 16/09/2026 lo script sembrava
# confermarlo solo per coincidenza (verificato a ridosso della pubblicazione
# di quel giorno). Il 17/09/2026 Michela aveva gia' pubblicato il menu
# (confermato da una foto reale della lavagna), ma lo script continuava a
# fallire: quell'ID ormai scaduto mostra permanentemente "Questa storia non
# e' piu' disponibile", indipendentemente da eventuali NUOVE storie con un
# ID diverso pubblicate nel frattempo - ogni storia ha con ogni probabilita'
# un proprio ID che cambia ad ogni pubblicazione e non e' riusabile il
# giorno dopo.
#
# Per questo lo script non naviga piu' direttamente a un ID salvato qui:
# ogni volta che serve la storia corrente (primo controllo della giornata,
# o se l'URL in cache smette di funzionare) riparte dal profilo di Michela
# e clicca sul collegamento alla storia attiva (discover_current_story()
# piu' sotto), che porta sempre a quella REALMENTE corrente. L'URL cosi'
# scoperto resta in STORY_CACHE solo per il resto della giornata/esecuzione,
# cosi' i controlli successivi ogni 10 minuti non devono ripassare dal
# profilo ogni volta.
STORY_CACHE = {'date': None, 'url': None}

# Profilo Chrome dedicato: lo stesso usato da Stato.py. E' condiviso di
# proposito, cosi' non serve un secondo login manuale se quello di Stato.py e'
# gia' stato completato: la sessione Facebook salvata funziona per qualsiasi
# storia pubblica, non solo per quella con cui e' stata validata la tecnica.
PROFILE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'StatoFacebook' / 'chrome'

# Soltanto immagini caricate e visibili al centro del visualizzatore;
# esclude avatar e miniature laterali. Nessun fallback alle foto dei post.
IMAGE_JS = """() => {
 const imgs = [...document.querySelectorAll('img')].filter(img => {
   const r = img.getBoundingClientRect();
   const s = getComputedStyle(img);
   return img.complete && img.naturalWidth >= 200 && img.naturalHeight >= 200
     && r.width >= 200 && r.height >= 200 && s.visibility !== 'hidden'
     && s.display !== 'none' && r.right > innerWidth * .35
     && r.left < innerWidth * .75 && r.top < innerHeight && r.bottom > 0;
 });
 imgs.sort((a,b) => {
   const x=a.getBoundingClientRect(), y=b.getBoundingClientRect();
   return y.width*y.height-x.width*x.height;
 });
 return imgs.length ? {src:imgs[0].currentSrc || imgs[0].src, alt:imgs[0].alt} : null;
}"""

# Indicazione di tempo relativa (es. "1 h", "5 min", "adesso") vicino al nome
# in alto nel visualizzatore. Cerca in base alla POSIZIONE sullo schermo
# (angolo in alto a destra del visualizzatore, sopra il nome/avatar) invece
# che a un nodo di testo isolato con match esatto: Facebook spesso raggruppa
# nome + separatore + orario nello stesso elemento (icone, puntini), quindi
# un testo tipo "Le Delizie di Michela · 1 h" non combacia con una regex
# ancorata "^...$" cercata da get_by_text(). Qui invece si accetta qualsiasi
# elemento piccolo, in alto, il cui testo CONTIENE l'indicazione di tempo.
RECENT_JS = """() => {
 const re = /(^|[^\\p{L}\\p{N}])(\\d{1,2}\\s*(m|min|h)|adesso|ora)(?![\\p{L}\\p{N}])/iu;
 return [...document.querySelectorAll('*')].some(el => {
   const t = (el.innerText || el.textContent || '').trim();
   if (!t || t.length > 24 || !re.test(t)) return false;
   const r = el.getBoundingClientRect();
   return r.width > 0 && r.height > 0 && r.height < 40 && r.top >= 0 && r.top < 140
     && r.left > innerWidth * .35 && r.left < innerWidth;
 });
}"""


def facebook_url(value):
    p = urlparse(value)
    if p.scheme != 'https' or p.hostname not in ('facebook.com', 'www.facebook.com', 'm.facebook.com'):
        raise argparse.ArgumentTypeError('Inserire un URL HTTPS di Facebook.')
    return value


def profile_processes(profile):
    if os.name != 'nt':
        return []
    command = "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Impossibile verificare se il profilo Chrome è occupato.')
    import json
    rows = json.loads(result.stdout.strip() or '[]')
    if isinstance(rows, dict):
        rows = [rows]
    expected = os.path.normcase(os.path.normpath(str(profile)))
    found = []
    for row in rows:
        command_line = row.get('CommandLine') or ''
        match = re.search(r'--user-data-dir=(?:"([^\"]+)"|([^\s]+))', command_line)
        if match and os.path.normcase(os.path.normpath(match.group(1) or match.group(2))) == expected:
            found.append(row['ProcessId'])
    return found


def wait_for_profile(profile):
    processes = profile_processes(profile)
    if processes:
        print('Il Chrome del login è ancora attivo. Nella SUA finestra usa menu tre puntini > Esci.', flush=True)
        print('Attendo la chiusura del profilo dedicato; Ctrl+C per annullare. Non serve ripetere il login.', flush=True)
    while processes:
        time.sleep(3)
        processes = profile_processes(profile)


def run_git(args, cwd):
    result = subprocess.run(['git'] + args, cwd=str(cwd), capture_output=True, text=True)
    return result


def publish_via_git(relative_path, day):
    """Aggiunge, commit e pubblica il menu importato. Ritorna True se ha
    pubblicato qualcosa, False se non c'era nulla di nuovo da pubblicare."""
    status = run_git(['status', '--porcelain', '--', relative_path], BASE)
    if status.returncode != 0:
        raise RuntimeError('git status non riuscito: ' + status.stderr.strip())
    if not status.stdout.strip():
        return False  # la storia non e' cambiata rispetto all'ultima pubblicazione
    add = run_git(['add', relative_path], BASE)
    if add.returncode != 0:
        raise RuntimeError('git add non riuscito: ' + add.stderr.strip())
    commit = run_git(['commit', '-m', f'Michela: importa storia del {day.isoformat()}'], BASE)
    if commit.returncode != 0:
        raise RuntimeError('git commit non riuscito: ' + commit.stderr.strip())
    for attempt in range(3):
        pull = run_git(['pull', '--rebase', 'origin', 'main'], BASE)
        if pull.returncode != 0:
            raise RuntimeError(
                'git pull --rebase non riuscito, probabile conflitto da risolvere a mano: '
                + pull.stderr.strip())
        push = run_git(['push', 'origin', 'main'], BASE)
        if push.returncode == 0:
            return True
        if attempt == 2:
            raise RuntimeError('git push non riuscito dopo 3 tentativi: ' + push.stderr.strip())
        time.sleep(5)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('url', nargs='?', default=PROFILE_URL, type=facebook_url)
    parser.add_argument('--login', action='store_true', help='Apre il browser per effettuare il login manualmente')
    parser.add_argument('--once', action='store_true', help='Esegue un solo controllo; altrimenti ripete ogni 10 minuti')
    parser.add_argument('--date', type=date.fromisoformat, default=None,
                        help="Forza la data del menu (YYYY-MM-DD) invece di oggi; utile solo per verifiche.")
    parser.add_argument('--no-git', action='store_true', help='Salva il file in locale ma non fa commit/push.')
    args = parser.parse_args()

    sys.path.insert(0, str(BASE))
    try:
        from rosticcerie_clean.local_menu import import_image
        import Rosticceria_legacy as legacy
    except ImportError as exc:
        print(f'Esegui questo script da dentro la cartella Progetto: {exc}', file=sys.stderr)
        return 1

    profile_url = args.url
    # Non si sostituisce piu' args.url con un ID di storia salvato (vedi nota
    # su STORY_CACHE sopra): si riparte dal profilo, o dall'URL esplicito
    # passato da riga di comando, e la storia corrente viene scoperta e
    # tenuta in cache per la giornata dentro check_once()/extract_story_image().

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError:
        print('Installare: python -m pip install playwright', file=sys.stderr)
        return 1

    if args.login:
        candidates = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
                      Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Google/Chrome/Application/chrome.exe',
                      Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Google/Chrome/Application/chrome.exe']
        chrome = next((p for p in candidates if p.is_file()), None)
        if chrome is None:
            raise RuntimeError('Google Chrome non trovato.')
        subprocess.Popen([str(chrome), '--user-data-dir=' + str(PROFILE), profile_url])
        print('Chrome aperto per il login manuale. Completa eventuali verifiche Facebook.')
        print('Dopo essere entrato usa il menu Chrome (tre puntini) > Esci, poi avvia questo script senza --login.')
        print('Se hai gia\' fatto --login con Stato.py, il profilo e\' condiviso: non serve rifarlo.')
        return 0

    wait_for_profile(PROFILE)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(PROFILE), channel='chrome', headless=False,
                                                       viewport={'width': 1280, 'height': 900}, locale='it-IT')
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15000)
            page.goto(args.url, wait_until='domcontentloaded')

            def needs_login():
                path = urlparse(page.url).path
                return any(part in path for part in ('/login', '/checkpoint', '/two_step_verification')) or page.locator('input[type="password"]').filter(visible=True).count() > 0

            def account_visible():
                return page.get_by_role('button', name=re.compile(r'^(Il tuo profilo|Your profile|Account)$', re.I)).count() > 0

            def story_is_recent():
                """Vero se, vicino al nome della storia in cima al
                visualizzatore (non nella lista storie a sinistra), compare
                un'indicazione di tempo relativa (es. "1 h", "5 min",
                "adesso"), tipica di una storia pubblicata nelle ultime 24
                ore. La ricerca e' basata sulla POSIZIONE sullo schermo
                (angolo in alto a destra del visualizzatore, RECENT_JS)
                invece che su un nodo di testo isolato con corrispondenza
                esatta: Facebook spesso raggruppa nome, separatore e orario
                nello stesso elemento (es. "Le Delizie di Michela · 1 h"),
                quindi un testo che CONTIENE l'indicazione basta. Se non la
                trova - o se il visualizzatore mostra qualcos'altro (es. una
                foto "in evidenza" permanente, o una storia scaduta rimasta
                in cache) - e' piu' sicuro trattarla come non valida
                piuttosto che rischiare di importare una foto vecchia
                spacciata per il menu di oggi. Nota: se in futuro questo
                controllo scarta storie che invece sono effettivamente di
                oggi, va rivista la regex/l'area di ricerca in RECENT_JS
                guardando cosa appare davvero nella schermata diagnostica."""
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if page.evaluate(RECENT_JS):
                        return True
                    page.wait_for_timeout(300)
                return False

            def story_unavailable():
                """Vero se il visualizzatore mostra il placeholder di storia scaduta/
                assente ("Questa storia non e' piu' disponibile"), tipico di quando
                Michela non ha ancora pubblicato il menu del giorno (l'ultima storia
                e' scaduta dopo 24h) oppure l'ha rimossa. Non e' un errore: va
                trattato come "nessuna storia ancora", da ricontrollare piu' tardi,
                non come un link rotto da riparare."""
                marker = page.get_by_text(re.compile(r"non è più disponibile|is no longer available", re.I))
                try:
                    marker.first.wait_for(state='visible', timeout=5000)
                    return True
                except PlaywrightTimeoutError:
                    return False

            def complete_login():
                input('Completa accesso e verifiche di Facebook in Chrome. Quando vedi il tuo account premi INVIO qui... ')
                if needs_login():
                    raise RuntimeError('Accesso non completato: Facebook mostra ancora login o verifica di sicurezza.')
                page.goto(args.url, wait_until='domcontentloaded')
                try:
                    page.get_by_role('button', name=re.compile(r'^(Il tuo profilo|Your profile|Account)$', re.I)).first.wait_for(state='visible', timeout=15000)
                except PlaywrightTimeoutError:
                    raise RuntimeError('Non riesco a confermare il login. Completa il controllo Facebook nella finestra Chrome e riprova con --login.')

            def discover_current_story():
                """Riparte dal profilo di Michela e clicca sul collegamento alla
                storia attualmente attiva. Ritorna True se si e' arrivati su un
                URL /stories/, False se in questo momento non risulta nessuna
                storia attiva (non e' un errore, va solo ricontrollato piu' tardi)."""
                if urlparse(page.url).path != urlparse(PROFILE_URL).path:
                    page.goto(PROFILE_URL, wait_until='domcontentloaded')
                if needs_login():
                    print('Facebook richiede di completare l’accesso.')
                    complete_login()
                labelled = page.get_by_role('link', name=re.compile(r'visualizza storia|view story', re.I))
                generic = page.locator('a[href*="/stories/"]:not([href*="/stories/create"])')
                story = labelled.or_(generic).filter(visible=True).first
                try:
                    story.wait_for(state='visible', timeout=30000)
                    story.click()
                    page.wait_for_url(re.compile(r'https://(?:www\.)?facebook\.com/stories/'), timeout=15000)
                    return True
                except PlaywrightTimeoutError:
                    if needs_login():
                        reason = 'Facebook mostra ancora la schermata di accesso o un controllo di sicurezza.'
                    elif account_visible():
                        reason = 'Account riconosciuto, ma nessuna storia attiva sul profilo di Michela.'
                    else:
                        reason = 'La pagina non espone il collegamento alla storia; non posso confermare lo stato del login.'
                    if needs_login() or not account_visible():
                        raise RuntimeError(reason + ' Interrompi con Ctrl+C e completa --login.')
                    print(reason + ' Nuovo controllo fra 10 minuti.')
                    return False

            def extract_story_image(day):
                """Ritorna il contenuto dell'immagine trovata nella storia, o None se
                al momento non c'e' nessuna storia attiva (non e' un errore). `day` e'
                la data (locale, Europe/Rome) per cui si sta cercando il menu, usata
                solo per etichettare la cache."""
                if needs_login():
                    print('Facebook richiede di completare l’accesso.')
                    complete_login()
                used_cache = bool(STORY_CACHE['url']) and page.url.rstrip('/') == STORY_CACHE['url'].rstrip('/')
                if '/stories/' not in urlparse(page.url).path:
                    if not discover_current_story():
                        return None
                    used_cache = False
                if story_unavailable():
                    if used_cache:
                        # L'URL scoperto in precedenza oggi non funziona piu'
                        # (storia rimossa/sostituita): niente panico, si scarta
                        # la cache e si riparte SUBITO dal profilo invece di
                        # aspettare altri 10 minuti pensando che Michela non
                        # abbia ancora pubblicato nulla.
                        STORY_CACHE['url'] = None
                        if not discover_current_story() or story_unavailable():
                            print('Nessuna storia attiva al momento (Michela probabilmente non ha ancora '
                                  'pubblicato il menu di oggi). Nuovo controllo fra 10 minuti.')
                            return None
                    else:
                        print('Nessuna storia attiva al momento (Michela probabilmente non ha ancora '
                              'pubblicato il menu di oggi). Nuovo controllo fra 10 minuti.')
                        return None
                open_story = page.get_by_text(re.compile(r'^(Clicca per visualizzare la storia|Click to view story)$', re.I)).first
                pause = page.get_by_role('button', name=re.compile(r'^(Metti in pausa|Pause)$')).first
                deadline = time.monotonic() + 25
                candidate = None
                clicked = False
                paused = False
                while time.monotonic() < deadline:
                    if not clicked and open_story.is_visible():
                        open_story.click(timeout=3000)
                        clicked = True
                    candidate = page.evaluate(IMAGE_JS)
                    if candidate:
                        break
                    if not paused and pause.is_visible():
                        try:
                            pause.click(timeout=1000)
                            paused = True
                        except PlaywrightTimeoutError:
                            pass
                    page.wait_for_timeout(200)
                if not candidate:
                    diagnostic = BASE / 'local_menus' / 'michela_diagnostica.png'
                    diagnostic.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(diagnostic))
                    raise RuntimeError('Nessuna immagine caricata nel visualizzatore. Schermata diagnostica: ' + str(diagnostic))
                if not story_is_recent():
                    diagnostic = BASE / 'local_menus' / 'michela_diagnostica.png'
                    diagnostic.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(diagnostic))
                    print('Immagine trovata ma senza indicazione di storia recente (probabile foto vecchia o in '
                          'evidenza): non la importo per sicurezza. Schermata: ' + str(diagnostic)
                          + ' Nuovo controllo fra 10 minuti.')
                    return None
                # Storia valida e recente: la teniamo in cache per il resto della
                # giornata (STORY_CACHE['date'] e' gia' impostato da check_once),
                # cosi' i prossimi controlli non devono ripassare dal profilo ogni
                # volta.
                STORY_CACHE['url'] = page.url
                src = candidate['src']
                host = urlparse(src).hostname or ''
                if urlparse(src).scheme != 'https' or not (host.endswith('.fbcdn.net') or host.endswith('.facebook.com')):
                    raise RuntimeError('Formato o origine immagine non supportato: nessun file importato.')
                response = context.request.get(src, timeout=30000)
                mime = response.headers.get('content-type', '').split(';')[0].lower()
                if not response.ok or mime not in ('image/jpeg', 'image/png', 'image/webp'):
                    raise RuntimeError('Facebook non ha restituito un file immagine valido.')
                body = response.body()
                if not body:
                    raise RuntimeError('Il file immagine è vuoto.')
                return body

            def check_once():
                day = args.date or legacy.rome_now().date()
                if STORY_CACHE['date'] != day:
                    # Nuovo giorno (o primo controllo): scarta un eventuale URL di
                    # ieri, che ormai sarebbe comunque scaduto.
                    STORY_CACHE['date'] = day
                    STORY_CACHE['url'] = None
                target = STORY_CACHE['url'] or args.url
                page.goto(target, wait_until='domcontentloaded')
                body = extract_story_image(day)
                if body is None:
                    return
                tmp = BASE / f'.michela_story_{day.isoformat()}.tmp'
                tmp.write_bytes(body)
                try:
                    destination = import_image(tmp, day)
                except ValueError as exc:
                    raise RuntimeError(f'Immagine della storia non valida come menu: {exc}')
                finally:
                    tmp.unlink(missing_ok=True)
                print(f'Menu importato dalla storia: {destination}')
                if args.no_git:
                    return
                relative = str(destination.relative_to(BASE))
                if publish_via_git(relative, day):
                    print('Pubblicato su GitHub (commit + push).')
                else:
                    print('Storia identica a quella gia\' pubblicata: nessun nuovo commit.')

            while True:
                started = time.monotonic()
                try:
                    check_once()
                except Exception as exc:
                    print(f'Controllo interrotto: {exc}', flush=True)
                    if page.is_closed():
                        raise RuntimeError('Browser chiuso. Riavvia lo script.')
                    if needs_login() or not account_visible():
                        print('Monitor in pausa: completa accesso/verifica nel browser, oppure Ctrl+C e --login.')
                        input('Premi INVIO soltanto dopo avere completato l’accesso... ')
                        continue
                    if args.once:
                        return 1
                if args.once:
                    return 0
                remaining = max(0, 600 - (time.monotonic() - started))
                print('Prossimo controllo fra circa ' + str(round(remaining / 60, 1)) + ' minuti. Ctrl+C per terminare.', flush=True)
                page.wait_for_timeout(remaining * 1000)
        finally:
            context.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nOperazione annullata.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f'Errore: {exc}', file=sys.stderr)
        sys.exit(1)
