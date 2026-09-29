#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════
SERVIDOR REELSHORT — API em Python (paginação real via URL do site)
───────────────────────────────────────────────────────────────────────
Rotas:
  GET /                                → serve o index.html (front-end)
  GET /api/home                        → VITRINE (slide + seções da home)
  GET /api/shorts?page=1&pageSize=24   → CATÁLOGO paginado (Carregar Mais)
  GET /api/search?q=...                → busca por nome
  GET /api/categories                  → lista de categorias (tags)
  GET /api/shorts/<slug>/episodes      → episódios de um short
  GET /api/image?url=...               → proxy de imagem
  GET /health                          → status

Rodar:
  pip install flask requests beautifulsoup4
  python server.py
═══════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
import time
import threading
from urllib.parse import quote, unquote, urlparse, parse_qs

from flask import Flask, request, jsonify, Response, send_from_directory
import requests
from bs4 import BeautifulSoup

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════
from flask_cors import CORS

BASE = os.getenv("REELSHORT_BASE_URL", "https://www.reelshort.com")
LANG = os.getenv("REELSHORT_LANG", "pt")
TTL = int(os.getenv("REELSHORT_CACHE_TTL", "600"))
PORT = int(os.getenv("SHORTS_PORT", "8000"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
    "Origin": BASE,
}

# Domínios permitidos para o proxy de imagem (evita SSRF)
ALLOWED_IMG = (
    "crazymaplestudios.com",
    "reelshort.com",
    "cmastudios.com",
    "v-img.crazymaplestudios.com",
    "v-mps.crazymaplestudios.com",
)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ═══════════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════════
_cache = {}
_cache_lock = threading.Lock()


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        if time.time() > item["expires"]:
            del _cache[key]
            return None
        return item["value"]


def cache_set(key, value, ttl=TTL):
    with _cache_lock:
        _cache[key] = {"value": value, "expires": time.time() + ttl}
    return value


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════
def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def make_soup(html):
    return BeautifulSoup(html, "html.parser")


def slugify(text):
    if not text:
        return ""
    s = text.lower()
    for a, b in [("á","a"),("à","a"),("â","a"),("ã","a"),("ä","a"),
                 ("é","e"),("è","e"),("ê","e"),("ë","e"),
                 ("í","i"),("ì","i"),("î","i"),("ï","i"),
                 ("ó","o"),("ò","o"),("ô","o"),("õ","o"),("ö","o"),
                 ("ú","u"),("ù","u"),("û","u"),("ü","u"),
                 ("ç","c"),("ñ","n")]:
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def make_slug(title, book_id):
    sp = slugify(title)
    return f"{sp}-{book_id}" if sp and book_id else (sp or book_id)


def normalize_image_url(url):
    if not url or url.startswith("data:"):
        return ""
    if url.startswith("/_next/image"):
        try:
            qs = parse_qs(urlparse(url).query)
            real = qs.get("url", [None])[0]
            if real:
                return unquote(real)
        except Exception:
            pass
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return url


def extract_next_data(soup):
    nd = soup.find("script", id="__NEXT_DATA__")
    if not nd:
        return None
    try:
        return json.loads(nd.string or "")
    except Exception:
        return None


def normalize_book(b):
    title = b.get("book_title") or ""
    book_id = b.get("book_id") or ""
    cover = b.get("book_pic") or b.get("default_pic") or ""
    if not title or not book_id:
        return None
    return {
        "slug": make_slug(title, book_id),
        "bookId": book_id,
        "title": title,
        "cover": cover,
        "description": b.get("special_desc", ""),
        "tags": [t.get("tag_name") for t in (b.get("theme_list") or []) if t.get("tag_name")],
        "chapters": b.get("chapter_count", 0),
        "views": b.get("read_count", 0),
    }


def _achar_books_recursivo(obj, depth=0):
    if depth > 8:
        return []
    if isinstance(obj, dict):
        if "book_title" in obj and "book_id" in obj:
            return [obj]
        for v in obj.values():
            r = _achar_books_recursivo(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and "book_title" in obj[0]:
            return obj
        for item in obj:
            r = _achar_books_recursivo(item, depth + 1)
            if r:
                return r
    return []


# ═══════════════════════════════════════════════════════════════════════
# DESCOBERTA DAS SHELVES — PEGA A URL REAL DO "VER TUDO"
# ═══════════════════════════════════════════════════════════════════════
_shelves_lock = threading.Lock()


def descobrir_shelves():
    """
    Retorna a lista de shelves com:
      [{"id": "51002941", "name": "Novo Lançamento", "base_url": "/pt/shelf/..."}]
    A URL base é capturada diretamente do atributo href do link "Ver tudo".
    """
    key = "shelves:v2"
    cached = cache_get(key)
    if cached:
        return cached

    with _shelves_lock:
        cached = cache_get(key)
        if cached:
            return cached

        html = fetch_html(f"{BASE}/{LANG}")
        soup = make_soup(html)

        shelves = []
        seen_ids = set()

        # 1) Estratégia principal: pega TODOS os <a> com href contendo '/shelf/'
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/shelf/" not in href:
                continue

            # Extrai o ID da URL (último número antes de barra ou fim)
            m = re.search(r"-(\d+)", href)
            if not m:
                continue
            shelf_id = m.group(1)
            if shelf_id in seen_ids:
                continue

            # Nome amigável
            name = a.get_text(strip=True) or f"Shelf {shelf_id}"

            # A base_url é a URL até antes do último segmento (que é a página)
            base_url = href.rstrip("/")

            # Se o href já termina em "1" (página), removemos
            base_url = re.sub(r"/\d+$", "", base_url)

            seen_ids.add(shelf_id)
            shelves.append({
                "id": shelf_id,
                "name": name,
                "base_url": base_url,
            })

        # 2) Fallback: se não achou nada nos <a>, tenta pelo __NEXT_DATA__
        if not shelves:
            parsed = extract_next_data(soup)
            if parsed:
                pp = parsed.get("props", {}).get("pageProps", {})
                fallback = pp.get("fallback", {}) if isinstance(pp, dict) else {}
                for _, v in fallback.items():
                    if isinstance(v, dict) and "bookShelfList" in v:
                        for s in (v.get("bookShelfList") or []):
                            sid = s.get("bs_id")
                            name = s.get("bookshelf_name") or ""
                            if sid and name and str(sid) not in seen_ids:
                                seen_ids.add(str(sid))
                                slug_part = slugify(name)
                                base_url = f"/{LANG}/shelf/{slug_part}-{sid}"
                                shelves.append({
                                    "id": str(sid),
                                    "name": name,
                                    "base_url": base_url,
                                })
                        break

        print(f"[shelves] {len(shelves)} shelves descobertas")
        for s in shelves[:5]:
            print(f"  → {s['name']} | base_url={s['base_url']}")

        cache_set(key, shelves, 3600)
        return shelves


# ═══════════════════════════════════════════════════════════════════════
# PAGINAÇÃO REAL DE UMA SHELF
# ═══════════════════════════════════════════════════════════════════════
def buscar_pagina_shelf(base_url, page):
    """
    Busca /pt/shelf/<slug>-<id>/<page> usando a URL base capturada do site.
    Retorna (lista_books, tem_proxima).
    """
    if base_url.startswith("http"):
        full = f"{base_url.rstrip('/')}/{page}"
    else:
        full = f"{BASE}{base_url.rstrip('/')}/{page}"

    try:
        html = fetch_html(full)
    except requests.HTTPError as e:
        print(f"[shelf {base_url} pág {page}] HTTP {e.response.status_code}")
        return [], False
    except Exception as e:
        print(f"[shelf {base_url} pág {page}] erro: {e}")
        return [], False

    soup = make_soup(html)
    parsed = extract_next_data(soup)
    if not parsed:
        return [], False

    pp = parsed.get("props", {}).get("pageProps", {})

    books = pp.get("list")
    if not isinstance(books, list):
        books = _achar_books_recursivo(pp) or []

    tem_next = bool(soup.find("link", rel="next"))
    return books, tem_next


# ═══════════════════════════════════════════════════════════════════════
# CATÁLOGO PAGINADO ("Carregar Mais" real)
# ═══════════════════════════════════════════════════════════════════════
def buscar_pagina_catalogo(page, page_size=24):
    """
    Retorna a página `page` do catálogo consolidado.
    Percorre as shelves + páginas internas na ordem, mesclando tudo.
    """
    shelves = descobrir_shelves()
    if not shelves:
        print("[catalog] Nenhuma shelf encontrada!")
        return [], False

    offset_global = (page - 1) * page_size
    resultado = []
    faltam = page_size
    acumulado = 0

    for shelf in shelves:
        base_url = shelf["base_url"]

        for shelf_page in range(1, 51):
            if faltam <= 0:
                return resultado, True

            books, tem_next = buscar_pagina_shelf(base_url, shelf_page)
            if not books:
                break

            bloco = []
            for b in books:
                nb = normalize_book(b)
                if nb:
                    bloco.append(nb)

            if not bloco:
                break

            if acumulado + len(bloco) <= offset_global:
                acumulado += len(bloco)
                if not tem_next:
                    break
                continue

            inicio = max(0, offset_global - acumulado)
            for b in bloco[inicio:]:
                resultado.append(b)
                faltam -= 1
                if faltam <= 0:
                    return resultado, True

            acumulado += len(bloco)

            if not tem_next:
                break

    return resultado, False


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /  →  SERVE O INDEX.HTML
# ═══════════════════════════════════════════════════════════════════════
@app.route("/")
def route_index():
    return send_from_directory(".", "index.html")


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/image  →  PROXY DE IMAGEM
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/image")
def route_image():
    """Proxy de imagem — evita hotlink e CORS."""
    url = request.args.get("url", "")
    if not url:
        return "", 400

    # Valida domínio (evita SSRF)
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "", 400

    if not any(host.endswith(d) for d in ALLOWED_IMG):
        return "", 403

    try:
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        r.raise_for_status()

        content_type = r.headers.get("Content-Type", "image/jpeg")
        return Response(
            r.iter_content(chunk_size=8192),
            content_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as e:
        print(f"[image proxy] erro: {e}")
        return "", 502


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /health
# ═══════════════════════════════════════════════════════════════════════
@app.route("/health")
def route_health():
    return jsonify({"ok": True, "cache_size": len(_cache)})


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/home
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/home")
def route_home():
    key = "home:v1"
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        html = fetch_html(f"{BASE}/{LANG}")
        soup = make_soup(html)

        slider, sections = [], []
        parsed = extract_next_data(soup)
        hall = None

        if parsed:
            pp = parsed.get("props", {}).get("pageProps", {})
            fallback = pp.get("fallback", {}) if isinstance(pp, dict) else {}
            for _, v in fallback.items():
                if isinstance(v, dict) and ("banners" in v or "bookShelfList" in v):
                    hall = v
                    break

        if hall:
            for b in (hall.get("banners") or [])[:5]:
                title = re.sub(r"^高清\s*", "", b.get("title") or "").strip()
                pic = b.get("pic") or ""
                jump = b.get("jump_param") or {}
                book_id = jump.get("book_id") or ""
                book_title = jump.get("book_title") or title
                thumb = jump.get("book_pic") or ""
                series_slug = make_slug(book_title, book_id)
                tags = [t.get("tag_name") for t in (jump.get("theme_list") or [])[:3] if t.get("tag_name")]

                if series_slug and pic:
                    slider.append({
                        "slug": series_slug,
                        "title": book_title,
                        "banner": pic,
                        "thumbnail": thumb,
                        "tags": tags,
                    })

        if hall:
            for shelf in (hall.get("bookShelfList") or []):
                name = shelf.get("bookshelf_name") or ""
                books = shelf.get("books") or []
                if not name or not books:
                    continue

                items, seen = [], set()
                for b in books[:20]:
                    nb = normalize_book(b)
                    if not nb or nb["slug"] in seen:
                        continue
                    seen.add(nb["slug"])
                    items.append({"slug": nb["slug"], "title": nb["title"], "cover": nb["cover"]})

                if items:
                    sections.append({
                        "title": name,
                        "shelfId": str(shelf.get("bs_id", "")),
                        "items": items,
                    })

        result = {"slider": slider, "sections": sections}
        cache_set(key, result, 1800)
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "slider": [], "sections": []}), 502


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/shorts
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/shorts")
def route_shorts():
    try:
        page = max(1, int(request.args.get("page", "1")))
        page_size = max(1, min(60, int(request.args.get("pageSize", "24"))))
    except ValueError:
        return jsonify({"error": "parâmetros inválidos"}), 400

    key = f"shorts:p{page}:s{page_size}"
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        items, tem_mais = buscar_pagina_catalogo(page, page_size)
        result = {
            "page": page,
            "pageSize": page_size,
            "count": len(items),
            "hasNext": tem_mais,
            "items": items,
        }
        cache_set(key, result, 300)
        return jsonify(result)
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "items": []}), 502


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/search
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/search")
def route_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "parâmetro q obrigatório"}), 400

    key = f"search:{q.lower()}"
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        url = f"{BASE}/{LANG}/search?keywords={quote(q)}"
        html = fetch_html(url)
        soup = make_soup(html)

        items, seen = [], set()
        for a in soup.select('a[href*="/movie/"]'):
            href = a.get("href", "")
            m = re.search(r"/movie/([^/?#]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            img = a.select_one("img")
            alt = img.get("alt") if img else ""
            title = (a.get("title") or alt or "").strip()
            if not title:
                continue
            items.append({
                "slug": slug,
                "title": title[:120],
                "cover": normalize_image_url(img.get("src", "")) if img else "",
            })

        result = {"query": q, "total": len(items), "items": items[:40]}
        cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "items": []}), 502


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/categories  →  LISTA DE CATEGORIAS (tags dos livros)
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/categories")
def route_categories():
    key = "categories:v1"
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        # Coleta as tags dos livros que aparecem na home
        html = fetch_html(f"{BASE}/{LANG}")
        soup = make_soup(html)
        parsed = extract_next_data(soup)

        categorias = {}
        if parsed:
            pp = parsed.get("props", {}).get("pageProps", {})
            fallback = pp.get("fallback", {}) if isinstance(pp, dict) else {}
            for _, v in fallback.items():
                if isinstance(v, dict) and "bookShelfList" in v:
                    for shelf in (v.get("bookShelfList") or []):
                        for b in (shelf.get("books") or []):
                            for t in (b.get("theme_list") or []):
                                tag_id = t.get("tag_id")
                                tag_name = t.get("tag_name")
                                if tag_id and tag_name:
                                    categorias[tag_id] = {
                                        "id": tag_id,
                                        "name": tag_name,
                                        "slug": slugify(tag_name),
                                    }
                    break

        lista = sorted(categorias.values(), key=lambda x: x["name"])
        result = {"total": len(lista), "categories": lista}
        cache_set(key, result, 3600)
        return jsonify(result)

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e), "categories": []}), 502


# ═══════════════════════════════════════════════════════════════════════
# ROTA: /api/shorts/<slug>/episodes
# ═══════════════════════════════════════════════════════════════════════
@app.route("/api/shorts/<path:slug>/episodes")
def route_short_episodes(slug):
    key = f"episodes:{slug}"
    cached = cache_get(key)
    if cached:
        return jsonify(cached)

    try:
        url = f"{BASE}/{LANG}/full-episodes/{slug}"
        html = fetch_html(url)
        soup = make_soup(html)

        episodes, seen_nums = [], set()

        parsed = extract_next_data(soup)
        if parsed:
            pp = parsed.get("props", {}).get("pageProps", {})
            data = pp.get("data", {}) if isinstance(pp, dict) else {}
            chapter_list = data.get("chapter_list") or data.get("chapterList") or []
            for i, ch in enumerate(chapter_list):
                num = ch.get("serial_number") or ch.get("chapter_index") or (i + 1)
                if num in seen_nums:
                    continue
                seen_nums.add(num)
                dur = ch.get("duration", 0)
                episodes.append({
                    "number": num,
                    "title": ch.get("chapter_title") or f"Episódio {num}",
                    "thumbnail": ch.get("video_pic", ""),
                    "duration": f"PT{dur // 60}M{dur % 60}S" if dur else "",
                    "url": f"{BASE}/{LANG}/episodes/{ch.get('chapter_id', '')}",
                })

        if not episodes:
            for a in soup.select('a[href*="/episodes/"]'):
                href = a.get("href", "")
                if "/episodes/" not in href:
                    continue
                img = a.select_one("img")
                title = ""
                h = a.select_one("h3, h2, [class*=title]")
                if h:
                    title = h.get_text(strip=True)
                if not title:
                    title = (a.get("title") or "").strip()
                num = len(episodes) + 1
                m = re.search(r"Ep(?:is[oó]dio)?\s*(\d+)", title, re.I)
                if m:
                    num = int(m.group(1))
                if num in seen_nums:
                    continue
                seen_nums.add(num)
                episodes.append({
                    "number": num,
                    "title": title or f"Episódio {num}",
                    "thumbnail": normalize_image_url(img.get("src", "")) if img else "",
                    "url": href if href.startswith("http") else BASE + href,
                })

        episodes.sort(key=lambda x: x.get("number", 0))
        h1 = soup.select_one("h1")
        result = {
            "slug": slug,
            "title": h1.get_text(strip=True) if h1 else slug,
            "total": len(episodes),
            "episodes": episodes,
        }
        cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "episodes": []}), 502


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔═══════════════════════════════════════════════════╗")
    print("║  ReelShort API Server                             ║")
    print(f"║  Base: {BASE}/{LANG}")
    print(f"║  Porta: {PORT}")
    print("╚═══════════════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)