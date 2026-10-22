import json
import re
from html import escape
from urllib.parse import urlparse

import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="trustedDialog Preview Integration Assistant v3", page_icon="✉️", layout="wide")

TARGETS = {1: (1088, 464), 2: (532, 352), 3: (348, 260)}

st.markdown("""
<style>
.block-container {max-width:1180px;padding-top:2rem}
.hero {padding:1.35rem 1.5rem;border-radius:18px;background:linear-gradient(135deg,#122f57,#315f9d);color:white;margin-bottom:1rem}
[data-testid="stMetric"] {background:#f8fafc;border:1px solid #e5e7eb;padding:10px;border-radius:12px}
</style>
<div class="hero"><h2 style="margin:0">trustedDialog Preview Integration Assistant · v3</h2>
<p style="margin:.45rem 0 0">Erzeugt JSON-LD bzw. HTML Microdata exakt nach dem bereitgestellten trustedDialog Preview Template.</p></div>
""", unsafe_allow_html=True)


def is_https(url):
    try:
        p = urlparse(url.strip())
        return p.scheme.lower() == "https" and bool(p.netloc)
    except Exception:
        return False


def srcset_urls(value):
    return [x.strip().split(" ")[0] for x in (value or "").split(",") if x.strip()]


def extract_images(html):
    soup = BeautifulSoup(html, "html.parser")
    found, seen = [], set()
    def add(url, source, alt="", width="", height=""):
        url = (url or "").strip()
        if not url or url.startswith(("data:", "cid:")) or url in seen:
            return
        seen.add(url)
        found.append({"url":url,"source":source,"alt":alt or "","width":width or "","height":height or ""})
    for img in soup.find_all("img"):
        add(img.get("src"), "img/src", img.get("alt"), img.get("width"), img.get("height"))
        for u in srcset_urls(img.get("srcset")): add(u, "img/srcset", img.get("alt"), img.get("width"), img.get("height"))
    for source in soup.find_all("source"):
        for u in srcset_urls(source.get("srcset")): add(u, "source/srcset")
    pattern = r"background(?:-image)?\s*:\s*url\([\"']?([^\"')]+)"
    for tag in soup.find_all(style=True):
        for u in re.findall(pattern, tag.get("style", ""), flags=re.I): add(u, "inline CSS")
    for style in soup.find_all("style"):
        for u in re.findall(pattern, style.get_text(" "), flags=re.I): add(u, "style block")
    return found


def remove_existing_td_markup(soup):
    removed = 0
    for script in list(soup.find_all("script", attrs={"type":"application/ld+json"})):
        txt = script.string or script.get_text(" ")
        if "PromotionCard" in txt or "DiscountOffer" in txt:
            script.decompose(); removed += 1
    for tag in list(soup.find_all(attrs={"itemtype":re.compile(r"http://schema\.org/(PromotionCard|DiscountOffer)", re.I)})):
        outer = tag.find_parent("div", attrs={"aria-hidden":"true"})
        (outer or tag).decompose(); removed += 1
    return removed


def build_jsonld(images, include_discount, description, code, start_iso, end_iso):
    # Exakt Template: Array; jede PromotionCard ist ein eigenes Objekt; image ist STRING;
    # Schema-Kontext exakt http://schema.org/
    items = []
    for url in images:
        items.append({"@context":"http://schema.org/", "@type":"PromotionCard", "image":url})
    if include_discount:
        items.append({
            "@context":"http://schema.org/",
            "@type":"DiscountOffer",
            "description":description,
            "discountCode":code,
            "availabilityStarts":start_iso,
            "availabilityEnds":end_iso,
        })
    return '<script type="application/ld+json">\n' + json.dumps(items, ensure_ascii=False, indent=2) + '\n</script>'


def build_microdata(images, include_discount, description, code, start_iso, end_iso):
    # Exakt dieselbe Wrapper-/Elementstruktur wie im bereitgestellten Template.
    parts = ['<div', 'style="display:none; max-height:0; overflow:hidden; mso-hide:all;"', 'aria-hidden="true">']
    for url in images:
        parts += [
            '<div itemscope itemtype="http://schema.org/PromotionCard">',
            f'  <span itemprop="image">{escape(url)}</span>',
            '</div>'
        ]
    if include_discount:
        parts += [
            '<section itemscope itemtype="http://schema.org/DiscountOffer">',
            '  <p>',
            f'    <span itemprop="discountCode">{escape(code)}</span>',
            f'    <span itemprop="description">{escape(description)}</span>',
            '  </p>',
            '  <p>',
            f'    <time itemprop="availabilityStarts" datetime="{escape(start_iso)}"></time>',
            f'    <time itemprop="availabilityEnds" datetime="{escape(end_iso)}"></time>',
            '  </p>',
            '</section>'
        ]
    parts.append('</div>')
    return "\n".join(parts)


def integrate(original_html, snippet, method, replace_existing):
    soup = BeautifulSoup(original_html, "html.parser")
    removed = remove_existing_td_markup(soup) if replace_existing else 0
    frag = BeautifulSoup(snippet, "html.parser")
    target = (soup.head or soup.body or soup) if method == "JSON-LD" else (soup.body or soup)
    for node in list(frag.contents): target.append(node)
    return str(soup), removed

uploaded = st.file_uploader("1. Fertiges Newsletter-HTML hochladen", type=["html","htm"])
if not uploaded:
    st.info("Bitte Newsletter als .html oder .htm hochladen.")
    st.stop()

raw = uploaded.getvalue()
html = None
for enc in ("utf-8","utf-8-sig","latin-1"):
    try:
        html = raw.decode(enc); break
    except UnicodeDecodeError: pass
if html is None:
    st.error("Datei konnte nicht als HTML-Text gelesen werden."); st.stop()

images = extract_images(html)
st.success(f"{uploaded.name} geladen · {len(images)} Bild-URL(s) erkannt")

left, right = st.columns([1.1,.9])
with left:
    st.subheader("2. Preview-Inhalt")
    options = [f"{i+1}. {im['alt'][:40] or 'Bild'} · {im['url'][:85]}" for i,im in enumerate(images)]
    chosen = st.multiselect("Bis zu drei Bilder auswählen", options, max_selections=3)
    selected = [images[options.index(x)]["url"] for x in chosen]
    manual = st.text_area("Optional: eigene/optimierte HTTPS-Bild-URLs", placeholder="Eine URL pro Zeile")
    manual_urls = [x.strip() for x in manual.splitlines() if x.strip()]
    final_images = list(dict.fromkeys(selected + manual_urls))[:3]
    if final_images:
        w,h = TARGETS[len(final_images)]
        st.caption(f"Zielgröße bei {len(final_images)} Bild(ern): {w} × {h} px je Bild")
        for i,u in enumerate(final_images,1): st.write(("✅" if is_https(u) else "⚠️") + f" Bild {i}: `{u}`")

with right:
    st.subheader("3. Integration")
    method = st.radio("Format", ["JSON-LD","HTML Microdata"], horizontal=True)
    content_mode = st.radio("Inhalt", ["Nur Bilder","Bilder + Gutscheincode","Nur Gutscheincode"])
    replace = st.checkbox("Vorhandene Preview-Blöcke ersetzen", value=True)
    include_discount = content_mode in ("Bilder + Gutscheincode","Nur Gutscheincode")
    include_images = content_mode in ("Nur Bilder","Bilder + Gutscheincode")
    if include_discount:
        description = st.text_input("Codebeschreibung", value="")
        code = st.text_input("Gutscheincode", value="")
        c1,c2 = st.columns(2)
        start_iso = c1.text_input("availabilityStarts", value="2026-01-01T00:00:00+02:00")
        end_iso = c2.text_input("availabilityEnds", value="2026-12-31T23:59:59+02:00")
    else:
        description=code=start_iso=end_iso=""

used_images = final_images if include_images else []
issues=[]
if include_images and not used_images: issues.append("Für die gewählte Variante ist Bild 1 verpflichtend.")
for u in used_images:
    if not is_https(u): issues.append(f"Bild muss über einen HTTPS-Link eingebunden werden: {u}")
if include_discount and len(code) < 2: issues.append("discountCode ist verpflichtend und muss mindestens zwei Zeichen enthalten.")

st.divider(); st.subheader("4. Prüfen & exportieren")
if issues:
    for x in issues: st.warning(x)
else:
    st.success("Pflichtfelder der gewählten Template-Variante sind erfüllt.")

snippet = build_jsonld(used_images, include_discount, description, code, start_iso, end_iso) if method=="JSON-LD" else build_microdata(used_images, include_discount, description, code, start_iso, end_iso)
output_html, removed = integrate(html, snippet, method, replace)

with st.expander("Generierten Template-Code anzeigen", expanded=True): st.code(snippet, language="html")

name = re.sub(r"\.(html?|HTML?)$", "", uploaded.name) + "_trustedDialog_v3.html"
st.download_button("Fertiges HTML herunterladen", output_html.encode("utf-8"), file_name=name, mime="text/html", type="primary", disabled=bool(issues), use_container_width=True)
