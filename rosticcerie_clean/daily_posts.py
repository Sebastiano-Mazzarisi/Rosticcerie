"""Accumula i post gia' acquisiti oggi anche se Facebook ne restituisce meno."""
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import Rosticceria_legacy as legacy

def post_key(post):
    photo = urlparse(post.get("photo_url", ""))
    query = parse_qs(photo.query)
    identity = query.get("fbid", [""])[0]
    if not identity and photo.path and photo.path not in ("/", "/photo.php", "/photo/"):
        identity = photo.netloc + photo.path
    if not identity:
        identity = urlparse(post.get("image_url", "")).path
    if not identity:
        identity = hashlib.sha256(post.get("image_bytes", b"")).hexdigest()
    return hashlib.sha256(identity.encode()).hexdigest()

def merge_today(name, posts):
    day = legacy.rome_now().date()
    path = Path(legacy.publish_dir()) / "daily_posts" / (legacy.safe_file_name(name) + ".json")
    collected = {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("date") == day.isoformat():
            for key, post in saved.get("posts", {}).items():
                post["image_bytes"] = base64.b64decode(post.pop("image_base64"), validate=True)
                collected[key] = post
    except (OSError, ValueError, KeyError):
        pass
    for post in posts:
        if legacy.parse_status_date(post.get("published_at", "")) != day:
            continue
        key = post_key(post)
        if key in collected:
            continue
        try:
            image = legacy.download_image(post["image_url"])
        except Exception as exc:
            print(f"{name}: immagine non scaricabile ({type(exc).__name__}), conservo i post acquisiti.")
            continue
        collected[key] = dict(post, image_bytes=image)
    encoded = {}
    for key, post in collected.items():
        encoded[key] = {k: v for k, v in post.items() if k != "image_bytes"}
        encoded[key]["image_base64"] = base64.b64encode(post["image_bytes"]).decode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"date": day.isoformat(), "posts": encoded}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    print(f"{name}: {len(posts)} post rilevati, {len(collected)} post conservati per oggi.")
    return list(collected.values())
