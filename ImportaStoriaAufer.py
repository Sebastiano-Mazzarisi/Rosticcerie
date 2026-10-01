"""Cattura automaticamente il menu del giorno di "Aufer Gastronomia" dalla
sua storia Instagram e lo pubblica come farebbe un'importazione manuale,
ma senza bisogno di una foto scattata a mano ogni giorno.

Aufer pubblica il menu solo nelle Storie di Instagram: Instagram le nasconde
a chi non e' loggato, quindi non esiste una fonte automatica anonima.
Questo script risolve il problema con la tecnica validata in Stato.py e
ImportaStoriaMichela.py: Chrome con un profilo dedicato e sessione salvata,
login manuale una sola volta, poi lettura automatica dell'immagine piu'
grande visibile nel visualizzatore delle storie.

L'immagine catturata viene validata e normalizzata con la stessa funzione che
usano gli altri script di importazione (rosticcerie_clean.local_menu.import_image),
quindi scritta in local_menus/aufer_<data>.jpg: il resto della pipeline la
legge esattamente come un'importazione manuale.

Va eseguito da dentro questa cartella (Progetto), perche' importa i moduli
rosticcerie_clean e Rosticceria_legacy usati anche da Rosticceria.py.

Installazione: python -m pip install -r requirements.txt
Primo accesso: python ImportaStoriaAufer.py --login
Controllo singolo: python ImportaStoriaAufer.py --once
Monitor continuo (ogni 10 minuti): python ImportaStoriaAufer.py
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

BASE = Path(__file__).resolve().parent  # cartella Progetto

PROFILE_URL = "https://www.instagram.com/aufergastronomia/"
# URL diretto alle storie: Instagram lo accetta senza dover cliccare l'avatar.
# Lo script prova prima questo, poi ricade sul profilo se non funziona.
STORIES_URL = "https://www.instagram.com/stories/aufergastronomia/"

# Slug usato per il file locale (deve corrispondere a local_slug in config.py)
SLUG = "aufer"
NAME = "Aufer Gastronomia"

STORY_CACHE = {'date': None, 'url': None}

# Profilo Chrome dedicato a Instagram (separato da StatoFacebook/chrome
# usato da Stato.py e ImportaStoriaMichela.py, perche' e' un sito diverso
# con sessione diversa).
PROFILE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AuferInstagram' / 'chrome'

# Trova l'immagine principale del menu nella storia Instagram: quella piu'
# grande visibile nella zona centrale dello schermo, escludendo avatar e
# miniature laterali.
IMAGE_JS = """() => {
 const imgs = [...document.querySelectorAll('img')].filter(img => {
   const r = img.getBoundingClientRect();
   const s = getComputedStyle(img);
   return img.complete && img.naturalWidth >= 200 && img.naturalHeight >= 200
     && r.width >= 200 && r.height >= 200 && s.visibility !== 'hidden'
     && s.display !== 'none' && r.right > innerWidth * .25
     && r.left < innerWidth * .85 && r.top < innerHeight && r.bottom > 0;
 });
 imgs.sort((a,b) => {
   const x=a.getBoundingClientRect(), y=b.getBoundingClientRect();
   return y.width*y.height-x.width*x.height;
 });
 return imgs.length ? {src:imgs[0].currentSrc || imgs[0].src, alt:imgs[0].alt} : null;
}"""

# Indicazione di tempo relativa vicino al nome in alto nel visualizzatore
# di Instagram. Instagram mostra tipicamente "Xh" o "X min" o "Adesso"
# nell'header della storia, spesso nello stesso elemento del nome utente.
# Cerca elementi piccoli (altezza < 60px) nella parte alta dello schermo
# (top < 140px) che contengano un'indicazione di tempo relativa.
RECENT_JS = """() => {
 const re = /(^|[^\\p{L}\\p{N}])(\\d{1,2}\\s*(m|min|h|ora|ore)|adesso|ora)(?![\\p{L}\\p{N}])/iu;
 return [...document.querySelectorAll('*')].some(el => {
   const t = (el.innerText || el.textContent || '').trim();
   if (!t || t.length > 120 || !re.test(t)) return false;
   const r = el.getBoundingClientRect();
   return r.width > 0 && r.height > 0 && r.height < 80 && r.top >= 0 && r.top < 250
     && r.left >= 0 && r.left < innerWidth;
 });
}"""


def instagram_story_url(value):
    p = urlparse(value)
    if p.scheme != 'https' or p.hostname not in ('instagram.com', 'www.instagram.com'):
        raise argparse.ArgumentTypeError('Inserire un URL HTTPS di Instagram.')
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
        return False
    add = run_git(['add', relative_path], BASE)
    if add.returncode != 0:
        raise RuntimeError('git add non riuscito: ' + add.stderr.strip())
    commit = run_git(['commit', '-m', f'Aufer: importa storia del {day.isoformat()}'], BASE)
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


def _click_visualizza(page):
    """Clicca 'Visualizza storia' se Instagram mostra il dialogo di conferma
    ("Vuoi visualizzare come <utente>?"). Non fa nulla se il dialogo non c'e'."""
    from playwright.sync_api import TimeoutError as _TE
    selectors = [
        'button:has-text("Visualizza storia")',
        'button:has-text("View story")',
        '[role="button"]:has-text("Visualizza storia")',
        '[role="button"]:has-text("View story")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            btn.wait_for(state='visible', timeout=3000)
            btn.click()
            page.wait_for_timeout(1500)
            return
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('url', nargs='?', default=PROFILE_URL, type=instagram_story_url)
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
        subprocess.Popen([str(chrome), '--user-data-dir=' + str(PROFILE), PROFILE_URL])
        print('Chrome aperto per il login Instagram manuale.')
        print('Completa il login su Instagram. Quando hai finito usa il menu Chrome (tre puntini) > Esci.')
        print('Poi avvia questo script senza --login.')
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
                """Vero se Instagram mostra la pagina di login o richiede accesso."""
                path = urlparse(page.url).path
                if any(part in path for part in ('/login', '/accounts/login')):
                    return True
                if page.locator('input[name="username"]').filter(visible=True).count() > 0:
                    return True
                return False

            def account_visible():
                """Vero se il profilo utente e' accessibile (sessione valida)."""
                # Instagram mostra un'icona/link al profilo in alto a destra
                # quando si e' loggati; in alternativa verifica la presenza
                # dell'avatar del profilo di Aufer senza redirect al login.
                return not needs_login() and page.locator('[aria-label="Home"]').count() > 0

            def story_is_recent():
                """Vero se nell'header della storia compare un'indicazione di
                tempo relativa (es. "2h", "15 min", "Adesso"), tipica di una
                storia pubblicata nelle ultime 24 ore. Se non la trova si
                tratta la storia come non valida per sicurezza."""
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline:
                    if page.evaluate(RECENT_JS):
                        return True
                    page.wait_for_timeout(300)
                return False

            def story_unavailable():
                """Vero se Instagram mostra il placeholder di storia scaduta/
                assente o un messaggio di contenuto non disponibile."""
                markers = [
                    re.compile(r"storia.*non.*disponibile|story.*no longer", re.I),
                    re.compile(r"contenuto.*non.*disponibile|content.*not available", re.I),
                    re.compile(r"questa pagina non.*disponibile|this page isn", re.I),
                ]
                for pattern in markers:
                    marker = page.get_by_text(pattern)
                    try:
                        marker.first.wait_for(state='visible', timeout=3000)
                        return True
                    except PlaywrightTimeoutError:
                        pass
                return False

            def complete_login():
                input('Completa il login su Instagram nella finestra Chrome. Quando sei dentro premi INVIO qui... ')
                if needs_login():
                    raise RuntimeError('Accesso non completato: Instagram mostra ancora la schermata di login.')
                page.goto(args.url, wait_until='domcontentloaded')

            def discover_current_story():
                """Naviga direttamente all'URL delle storie di Aufer.
                Instagram accetta questo URL diretto senza dover cliccare
                sull'avatar del profilo. Ritorna True se si e' arrivati su
                un URL /stories/, False se al momento non c'e' storia attiva."""
                if needs_login():
                    print('Instagram richiede di completare l\'accesso.')
                    complete_login()
                # Prova prima l'URL diretto delle storie
                try:
                    page.goto(STORIES_URL, wait_until='domcontentloaded')
                    # Verifica di essere effettivamente su una pagina storie
                    # (se non c'e' storia Instagram reindirizza al profilo)
                    if '/stories/' in urlparse(page.url).path:
                        # Instagram mostra un dialogo di conferma prima di
                        # aprire la storia ("Vuoi visualizzare come <utente>?")
                        # — clicca subito "Visualizza storia" se presente.
                        _click_visualizza(page)
                        return True
                except Exception:
                    pass
                # Ricaduta: naviga al profilo e cerca il link alla storia
                page.goto(PROFILE_URL, wait_until='domcontentloaded')
                if needs_login():
                    raise RuntimeError('Instagram mostra ancora la schermata di accesso. Ctrl+C e --login.')
                story_link = page.locator('a[href*="/stories/aufergastronomia/"]').first
                try:
                    story_link.wait_for(state='visible', timeout=15000)
                    story_link.click()
                    page.wait_for_url(re.compile(r'https://(?:www\.)?instagram\.com/stories/'), timeout=10000)
                    return True
                except PlaywrightTimeoutError:
                    print('Nessuna storia attiva al momento su Aufer Gastronomia. Nuovo controllo fra 10 minuti.')
                    return False

            def extract_story_image(day):
                """Ritorna il contenuto dell'immagine trovata nella storia, o None se
                al momento non c'e' nessuna storia attiva (non e' un errore)."""
                if needs_login():
                    print('Instagram richiede di completare l\'accesso.')
                    complete_login()
                used_cache = bool(STORY_CACHE['url']) and page.url.rstrip('/') == STORY_CACHE['url'].rstrip('/')
                if '/stories/' not in urlparse(page.url).path:
                    if not discover_current_story():
                        return None
                    used_cache = False
                if story_unavailable():
                    if used_cache:
                        STORY_CACHE['url'] = None
                        if not discover_current_story() or story_unavailable():
                            print('Nessuna storia attiva al momento (Aufer probabilmente non ha ancora '
                                  'pubblicato il menu di oggi). Nuovo controllo fra 10 minuti.')
                            return None
                    else:
                        print('Nessuna storia attiva al momento (Aufer probabilmente non ha ancora '
                              'pubblicato il menu di oggi). Nuovo controllo fra 10 minuti.')
                        return None

                # Attende che l'immagine principale della storia si carichi
                deadline = time.monotonic() + 25
                candidate = None
                while time.monotonic() < deadline:
                    candidate = page.evaluate(IMAGE_JS)
                    if candidate:
                        break
                    page.wait_for_timeout(200)

                if not candidate:
                    # Instagram a volte rende le storie come <video> o canvas
                    # invece di <img>: in quel caso IMAGE_JS non trova nulla.
                    # Fallback: screenshot dell'area centrale della storia.
                    print('Nessun <img> trovato: uso screenshot della storia come fallback.')
                    diagnostic = BASE / 'local_menus' / 'aufer_diagnostica.png'
                    diagnostic.parent.mkdir(parents=True, exist_ok=True)
                    # Ritaglia l'area del visualizzatore (zona centrale dello schermo)
                    vw = page.viewport_size['width'] if page.viewport_size else 1280
                    vh = page.viewport_size['height'] if page.viewport_size else 900
                    clip = {'x': int(vw * 0.35), 'y': 155, 'width': int(vw * 0.45), 'height': vh - 160}
                    page.screenshot(path=str(diagnostic), clip=clip)
                    # Usa lo screenshot come immagine del menu
                    return diagnostic.read_bytes() if diagnostic.exists() and diagnostic.stat().st_size > 10000 else None

                if not story_is_recent():
                    diagnostic = BASE / 'local_menus' / 'aufer_diagnostica.png'
                    diagnostic.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(diagnostic))
                    print('Immagine trovata ma senza indicazione di storia recente (probabile storia '
                          'in evidenza permanente o vecchia): non la importo per sicurezza. '
                          'Schermata: ' + str(diagnostic) + ' Nuovo controllo fra 10 minuti.')
                    return None

                STORY_CACHE['url'] = page.url
                src = candidate['src']
                host = urlparse(src).hostname or ''
                # Instagram serve le immagini da cdninstagram.com o fbcdn.net
                allowed_hosts = ('cdninstagram.com', 'fbcdn.net', 'instagram.com', 'scontent')
                if urlparse(src).scheme != 'https' or not any(h in host for h in allowed_hosts):
                    # Fallback: scarica dall'URL trovato comunque (Instagram
                    # usa sottodomini variabili di cdninstagram.com)
                    if not host.endswith('.com') and not host.endswith('.net'):
                        raise RuntimeError('Formato o origine immagine Instagram non supportato: ' + src)

                response = context.request.get(src, timeout=30000)
                mime = response.headers.get('content-type', '').split(';')[0].lower()
                if not response.ok or mime not in ('image/jpeg', 'image/png', 'image/webp'):
                    raise RuntimeError('Instagram non ha restituito un file immagine valido (mime: ' + mime + ').')
                body = response.body()
                if not body:
                    raise RuntimeError('Il file immagine è vuoto.')
                return body

            def check_once():
                day = args.date or legacy.rome_now().date()
                if STORY_CACHE['date'] != day:
                    STORY_CACHE['date'] = day
                    STORY_CACHE['url'] = None
                target = STORY_CACHE['url'] or args.url
                page.goto(target, wait_until='domcontentloaded')
                body = extract_story_image(day)
                if body is None:
                    return
                tmp = BASE / f'.aufer_story_{day.isoformat()}.tmp'
                tmp.write_bytes(body)
                try:
                    destination = import_image(SLUG, NAME, tmp, day)
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
                    if needs_login():
                        print('Monitor in pausa: completa accesso nel browser Instagram, oppure Ctrl+C e --login.')
                        input('Premi INVIO soltanto dopo avere completato il login... ')
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
