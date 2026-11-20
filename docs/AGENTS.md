# 🤖 Instrukcje dla Agenta AI: Moduł Dokumentacji (`docs/`)

> Przed edycją plików w tym folderze zapoznaj się z nadrzędnym plikiem [`/AGENTS.md`](../AGENTS.md) oraz [`/CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 🎯 Zakres i Rola Modułu (`Scope`)
Katalog `docs/` stanowi centralną bazę wiedzy geoprzestrzennej projektu. Zawiera:
1. Rejestr otwartych polskich i europejskich usług danych przestrzennych (WMS, WFS, WCS, STAC API, REST).
2. Taryfikatory i opisy techniczne państwowych zbiorów danych (GUGiK, IMGW, IUNG, GIOŚ, PIG, Copernicus).
3. Instrukcje techniczne i specyfikacje integracyjne.

---

## 📂 Struktura Katalogu
```text
docs/
├── polskie_rejestry_publiczne_gis.csv   # Tabela ze źródłami, formatami i adresami URL (46 usług)
└── polskie_rejestry_publiczne_gis.md    # Szczegółowy opis z podziałem na kategorie
```

---

## 🛑 Zasady Specyficzne dla Dokumentacji (`Twarde Reguły`)

1. **Zasada spójności dwukierunkowej:**
   * Każda zmiana lub dodanie nowego źródła danych **musi** zostać odzwierciedlona w obu plikach naraz:
     * W pliku maszynowym `polskie_rejestry_publiczne_gis.csv` (rozdzielnik: średnik `;`),
     * W pliku czytelnym dla człowieka `polskie_rejestry_publiczne_gis.md` (tabela Markdown).
2. **Neutralność technologiczna:**
   * Utrzymuj neutralny, ogólnogeograficzny i inżynieryjny charakter opisów jako uniwersalnej bazy wiedzy GIS.
3. **Prawdziwość linków:**
   * Dodawaj wyłącznie zweryfikowane, oficjalne adresy państwowe i unijne (domeny `.gov.pl`, `.imgw.pl`, `.europa.eu`).
