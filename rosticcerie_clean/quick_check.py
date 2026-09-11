"""Confronto leggero prima della scansione completa delle foto Facebook."""
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import Rosticceria_legacy as legacy

FULL_CHECK_SECONDS = 3600

def fingerprint(items):
    stable = []
    for item in items:
        url = urlparse(item.get("href", ""))
        photo_id = parse_qs(url.query).get("fbid", [""])[0]
        src = urlparse(item.get("src", "")).path
        if src and ("fbcdn" in item.get("src", "") or "scontent" in item.get("src", "")):
            stable.append((photo_id or src, item.get("alt", ""), item.get("text", "")))
    if not stable:
        return None
    return hashlib.sha256(json.dumps(sorted(set(stable)), ensure_ascii=False).encode()).hexdigest()

def probe(config):
    try:
        with legacy.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width":1366,"height":1000})
                cookies = legacy.load_facebook_cookies(str(Path(legacy.script_dir()) / legacy.COOKIE_FILE))
                if cookies: context.add_cookies(cookies)
                page = context.new_page()
                items = []
                urls = [config.url]
                if config.name == "Impastamò": urls.append(legacy.build_photos_tab_url(config.url))
                for url in urls:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)
                    if any(part in page.url for part in ("login", "checkpoint", "two_step")): return None
                    images = page.locator('div[role="article"] img, div[aria-posinset] img' if url == config.url else 'a[href*="/photo"] img')
                    data = images.evaluate_all("""images => images.map(i=>({src:i.currentSrc||i.src,alt:i.alt||'',href:i.closest('a[href]')?.href||''}))""")
                    # Include captions without volatile reaction counts/timestamps.
                    for post in page.locator('div[role="article"]').all()[:10]:
                        caption = legacy.best_text_from_post(post)
                        if caption: items.append({"src":"https://fbcdn.test/caption", "text":caption})
                    if not data: return None
                    items.extend(data)
                return fingerprint(items)
            finally:
                browser.close()
    except Exception as exc:
        print(f"{config.name}: verifica rapida inconcludente ({type(exc).__name__}); ricerca completa.")
        return None

def state_path(name):
    return Path(legacy.publish_dir()) / "quick_checks" / (legacy.safe_file_name(name)+".json")

def unchanged(name, signature, now=None):
    if not signature: return False
    now = time.time() if now is None else now
    try:
        data = json.loads(state_path(name).read_text(encoding="utf-8"))
        age = now - data["full_checked_at"]
        return data["date"] == legacy.rome_now().date().isoformat() and data["signature"] == signature and 0 <= age < FULL_CHECK_SECONDS
    except (OSError, ValueError, KeyError, TypeError): return False

def remember(name, signature):
    if not signature: return
    path = state_path(name); path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"signature":signature,"full_checked_at":time.time(),"date":legacy.rome_now().date().isoformat()}),encoding="utf-8")
    temporary.replace(path)
