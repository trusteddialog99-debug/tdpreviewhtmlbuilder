import io
import json
import re
from html import escape
from urllib.parse import urlparse

import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="trustedDialog Preview Integration Assistant", page_icon="✉️", layout="wide")

TARGETS = {
    1: (1088, 464),
    2: (532, 352),
    3: (348, 260),
}

STYLE = """
<style>
.block-container {max-width: 1180px; padding-top: 2rem;}
.td-hero {padding: 1.4rem 1.6rem; border-radius: 18px; background: linear-gradient(135deg,#153e72,#315f9d); color:white; margin-bottom:1rem;}
.td-muted {color:#667085; font-size:.92rem;}
.td-card {border:1px solid #e5e7eb; border-radius:14px; padding:14px; background:#fff;}
[data-testid="stMetric"] {background:#f8fafc; border:1px solid #e5e7eb; padding:10px; border-radius:12px;}
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)
st.markdown("""
<div class="td-hero">
  <h2 style="margin:0">trustedDialog Preview Integration Assistant</h2>
  <p style="margin:.45rem 0 0">Newsletter-HTML hochladen, Preview-Motive auswählen, JSON-LD oder HTML Microdata erzeugen und das fertige HTML exportieren.</p>
</div>
""", unsafe_allow_html=True)


def is_https(url: str) -> bool:
    try:
        p = urlparse(url.strip())
        return p.scheme.lower() == "https" and bool(p.netloc)
    except Exception:
        return False


def srcset_urls(value: str):
    out = []
    for item in (value or "").split(","):
        candidate = item.strip().split(" ")[0].strip()
        if candidate:
            out.append(candidate)
    return out


def extract_images(html: str):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(url, source, alt="", width="", height=""):
        url = (url or "").strip()
        if not url or url.startswith(("data:", "cid:")) or url in seen:
            return
        seen.add(url)
        found.append({"url": url, "source": source, "alt": alt or "", "width": width or "", "height": height or ""})

    for img in soup.find_all("img"):
        add(img.get("src"), "img/src", img.get("alt"), img.get("width"), img.get("height"))
        for u in srcset_urls(img.get("srcset")):
            add(u, "img/srcset", img.get("alt"), img.get("width"), img.get("height"))

    for source in soup.find_all("source"):
        for u in srcset_urls(source.get("srcset")):
            add(u, "source/srcset")

    css_patterns = [
        r"background(?:-image)?\s*:\s*url\([\"']?([^\"')]+)",
    ]
    for tag in soup.find_all(style=True):
        for pattern in css_patterns:
            for u in re.findall(pattern, tag.get("style", ""), flags=re.I):
                add(u, "inline CSS")

    for style in soup.find_all("style"):
        txt = style.get_text(" ")
        for pattern in css_patterns:
            for u in re.findall(pattern, txt, flags=re.I):
                add(u, "style block")
    return found


def remove_existing_td_markup(soup: BeautifulSoup):
    removed = 0
    for script in list(soup.find_all("script", attrs={"type": "application/ld+json"})):
        txt = script.string or script.get_text(" ")
        if any(k in txt for k in ("PromotionCard", "DiscountOffer", "schema.org")):
            script.decompose(); removed += 1
    for tag in list(soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/(PromotionCard|DiscountOffer)", re.I)})):
        tag.decompose(); removed += 1
    return removed


def build_jsonld(images, code, description, start, end):
    graph = []
    if images:
        graph.append({"@type": "PromotionCard", "image": images})
    if code.strip():
        offer = {"@type": "DiscountOffer", "discountCode": code.strip()}
        if description.strip(): offer["description"] = description.strip()
        if start: offer["availabilityStarts"] = start.isoformat()
        if end: offer["availabilityEnds"] = end.isoformat()
        graph.append(offer)
    # trustedDialog erwartet ein JSON-LD-Array aus einzelnen Objekten.
    payload = []
    for item in graph:
        payload.append({"@context": "https://schema.org", **item})
    return '<script type="application/ld+json">\n' + json.dumps(payload, ensure_ascii=False, indent=2) + '\n</script>'


def build_microdata(images, code, description, start, end):
    parts = []
    if images:
        parts.append('<div itemscope itemtype="https://schema.org/PromotionCard" style="display:none">')
        for u in images:
            parts.append(f'  <span itemprop="image">{escape(u)}</span>')
        parts.append('</div>')
    if code.strip():
        parts.append('<section itemscope itemtype="https://schema.org/DiscountOffer" style="display:none">')
        parts.append(f'  <span itemprop="discountCode">{escape(code.strip())}</span>')
        if description.strip(): parts.append(f'  <span itemprop="description">{escape(description.strip())}</span>')
        if start: parts.append(f'  <time itemprop="availabilityStarts" datetime="{start.isoformat()}"></time>')
        if end: parts.append(f'  <time itemprop="availabilityEnds" datetime="{end.isoformat()}"></time>')
        parts.append('</section>')
    return "\n".join(parts)


def integrate(original_html, snippet, method, replace_existing):
    soup = BeautifulSoup(original_html, "html.parser")
    removed = remove_existing_td_markup(soup) if replace_existing else 0
    frag = BeautifulSoup(snippet, "html.parser")
    nodes = list(frag.contents)
    if method == "JSON-LD":
        target = soup.head or soup.body or soup
    else:
        target = soup.body or soup
    for node in nodes:
        target.append(node)
    return str(soup), removed


uploaded = st.file_uploader("1. Fertiges Newsletter-HTML hochladen", type=["html", "htm"])
if not uploaded:
    st.info("Lade zunächst eine .html- oder .htm-Datei hoch. Die App führt keine Scripts aus, sondern analysiert den HTML-Quelltext.")
    st.stop()

raw = uploaded.getvalue()
for enc in ("utf-8", "utf-8-sig", "latin-1"):
    try:
        html = raw.decode(enc)
        break
    except UnicodeDecodeError:
        html = None
if html is None:
    st.error("Die Datei konnte nicht als Text gelesen werden.")
    st.stop()

images = extract_images(html)
st.success(f"HTML geladen: {uploaded.name} · {len(images)} Bild-URL(s) erkannt")

left, right = st.columns([1.12, .88])
with left:
    st.subheader("2. Preview-Motive auswählen")
    if not images:
        st.warning("Im HTML wurden keine externen Bild-URLs gefunden. Du kannst Preview-URLs unten manuell ergänzen.")

    options = []
    for i, im in enumerate(images):
        label = f"{i+1}. {im['alt'][:45] or 'Bild'} · {im['url'][:90]}"
        options.append(label)

    chosen_labels = st.multiselect("Bis zu drei Bilder aus dem Newsletter", options, max_selections=3)
    selected = [images[options.index(label)] for label in chosen_labels]

    manual = st.text_area("Optional: eigene/optimierte HTTPS-Bild-URLs", placeholder="Eine URL pro Zeile, z. B. später vom trustedDialog Asset-Service")
    manual_urls = [x.strip() for x in manual.splitlines() if x.strip()]
    final_images = [x["url"] for x in selected] + manual_urls
    final_images = list(dict.fromkeys(final_images))[:3]

    if final_images:
        target_w, target_h = TARGETS[len(final_images)]
        st.caption(f"Zielgröße für {len(final_images)} Preview-Bild(er): {target_w} × {target_h} px je Bild")
        for idx, u in enumerate(final_images, 1):
            icon = "✅" if is_https(u) else "⚠️"
            st.write(f"{icon} **Bild {idx}:** `{u}`")
    st.caption("Hinweis: Diese MVP-Version verändert oder hostet externe Bilder noch nicht. Für eine optimierte Variante kannst du bereits eine neue HTTPS-URL eintragen.")

with right:
    st.subheader("3. Integration konfigurieren")
    method = st.radio("Format", ["JSON-LD", "HTML Microdata"], horizontal=True)
    replace = st.checkbox("Vorhandene trustedDialog/schema.org Preview-Blöcke ersetzen", value=True)
    st.markdown("**Optionaler Gutscheincode**")
    code = st.text_input("Gutscheincode", max_chars=50)
    description = st.text_input("Beschreibung", max_chars=50)
    use_dates = st.checkbox("Gültigkeitszeitraum hinterlegen")
    c1, c2 = st.columns(2)
    start = c1.date_input("Start") if use_dates else None
    end = c2.date_input("Ende") if use_dates else None

st.divider()
st.subheader("4. Prüfen & exportieren")
issues = []
if not final_images and not code.strip(): issues.append("Mindestens ein Preview-Bild oder ein Gutscheincode sollte angegeben werden.")
if len(final_images) > 3: issues.append("Maximal drei Preview-Bilder verwenden.")
for u in final_images:
    if not is_https(u): issues.append(f"Keine gültige öffentliche HTTPS-URL: {u}")
if code and len(code.strip()) < 2: issues.append("Der Gutscheincode sollte mindestens zwei Zeichen enthalten.")
if start and end and end < start: issues.append("Das Enddatum liegt vor dem Startdatum.")

if issues:
    for issue in issues: st.warning(issue)
else:
    st.success("Die lokale Plausibilitätsprüfung ist ohne Fehler durchgelaufen.")

snippet = build_jsonld(final_images, code, description, start, end) if method == "JSON-LD" else build_microdata(final_images, code, description, start, end)
output_html, removed = integrate(html, snippet, method, replace)

m1, m2, m3 = st.columns(3)
m1.metric("Bild-URLs", len(final_images))
m2.metric("Format", method)
m3.metric("Ersetzte Blöcke", removed)

with st.expander("Generierten Code anzeigen", expanded=True):
    st.code(snippet, language="html")

with st.expander("Erkannte Bilder aus dem Newsletter"):
    if images:
        for i, im in enumerate(images, 1):
            st.write(f"**{i}.** {im['source']} · Alt: `{im['alt'] or '-'}` · Größe im Markup: `{im['width'] or '?'} × {im['height'] or '?'}`")
            st.caption(im["url"])
    else:
        st.write("Keine externen Bilder erkannt.")

out_name = re.sub(r"\.(html?|HTML?)$", "", uploaded.name) + "_trustedDialog.html"
st.download_button(
    "Fertiges HTML herunterladen",
    data=output_html.encode("utf-8"),
    file_name=out_name,
    mime="text/html",
    type="primary",
    disabled=bool(issues),
    use_container_width=True,
)

st.caption("MVP: HTML-Analyse, Bildauswahl, JSON-LD/Microdata-Erzeugung, Dubletten-Entfernung und Export. Nächster sinnvoller Ausbau: visueller Crop-Editor + Asset-Hosting + Inbox-Preview-Simulation.")
