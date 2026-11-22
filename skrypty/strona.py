import argparse
import base64
import json
import os
import re
import shutil
import sys

ZNACZNIK = "<!-- dodatek rolnik -->"
WSTAWKA = (f'{ZNACZNIK}\n<link rel="stylesheet" href="rolnik/rolnik.css">\n'
           '<script src="rolnik/rolnik.js"></script>\n')

# WYSZUKIWANIE HTML:
def znajdz_html(katalog):
    if os.path.isfile(os.path.join(katalog, "index.html")):
        return os.path.join(katalog, "index.html")
    pliki = sorted(f for f in os.listdir(katalog) if f.lower().endswith((".html", ".htm")))
    if not pliki:
        sys.exit(f"W folderze '{katalog}' nie ma pliku .html - wgraj tam zawartość eksportu z qgis2web.")
    for f in pliki:
        with open(os.path.join(katalog, f), encoding="utf-8", errors="replace") as h:
            tekst = h.read().lower()
        if "qgis2web.js" in tekst or "leaflet" in tekst:
            return os.path.join(katalog, f)
    return os.path.join(katalog, pliki[0])


def czytaj(sciezka):
    with open(sciezka, encoding="utf-8") as f:
        return f.read()


def bezpieczny(tekst):
    return re.sub(r"</(script|style)", r"<\\/\1", tekst, flags=re.I)

# TRYB JEDNEGO PLIKU: kodowanie map PNG do Base64 i osadzenie danych w HTML
def wstawka_wbudowana(dodatek, dane):
    meta = json.loads(czytaj(os.path.join(dane, "meta.json")))
    png = {}
    for w in meta["warstwy"]:
        sciezka = os.path.join(dane, w["plik"])
        if os.path.exists(sciezka):
            with open(sciezka, "rb") as f:
                png[w["id"]] = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    js_dane = json.dumps({"meta": meta, "png": png}, ensure_ascii=False, separators=(",", ":"))
    return (f"{ZNACZNIK}\n<style>\n{czytaj(os.path.join(dodatek, 'rolnik.css'))}\n</style>\n"
            f"<script>window.ROLNIK_DANE = {bezpieczny(js_dane)};</script>\n"
            f"<script>\n{bezpieczny(czytaj(os.path.join(dodatek, 'rolnik.js')))}\n</script>\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mapa", default="mapa")
    p.add_argument("--dodatek", default="rolnik")
    p.add_argument("--dane", default="_dane")
    p.add_argument("--wyjscie", default="_site")
    p.add_argument("--jeden-plik", action="store_true",
                   help="wbuduj dodatek i dane w index.html (strona działa po dwukliku, bez serwera)")
    a = p.parse_args()

    indeks = znajdz_html(a.mapa)
    print(f"Strona główna eksportu: {os.path.basename(indeks)}")
    with open(indeks, encoding="utf-8") as f:
        html = f.read()
    niski = html.lower()
    if "qgis2web.js" in niski or "ol.js" in niski:
        print("Wykryto eksport OpenLayers.")
    elif "leaflet" in niski:
        print("Wykryto eksport Leaflet.")
    else:
        sys.exit(f"{indeks} nie wygląda na eksport z qgis2web (brak OpenLayers i Leaflet).")
    # KOPIOWANIE PLIKÓW:
    if os.path.exists(a.wyjscie):
        shutil.rmtree(a.wyjscie)
    shutil.copytree(a.mapa, a.wyjscie)
    if a.jeden_plik:
        wstawka = wstawka_wbudowana(a.dodatek, a.dane)
    else:
        wstawka = WSTAWKA
        shutil.copytree(a.dodatek, os.path.join(a.wyjscie, "rolnik"))
        shutil.copytree(a.dane, os.path.join(a.wyjscie, "rolnik", "dane"),
                        ignore=shutil.ignore_patterns("meta_*.json"))
    # WSTRZYKNIĘCIE DODATKU: wklejenie skryptów rolniczych przed </body> i plik .nojekyll
    if ZNACZNIK not in html:
        poz = html.lower().rfind("</body>")
        html = html[:poz] + wstawka + html[poz:] if poz >= 0 else html + wstawka
    nazwy = {"index.html", os.path.basename(indeks)}
    for nazwa in nazwy:
        with open(os.path.join(a.wyjscie, nazwa), "w", encoding="utf-8") as f:
            f.write(html)
    open(os.path.join(a.wyjscie, ".nojekyll"), "w").close()
    print(f"Strona gotowa w {a.wyjscie}/")


if __name__ == "__main__":
    main()
