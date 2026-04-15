# Projektstarter Butler

Dieses Plugin kombiniert den Projektstarter mit dem AttributionButler in einem eigenstaendigen Paket.

- Toolbar-Klick oeffnet ein gemeinsames Overlay fuer Projektstatus und Butler-Einstellungen
- Projektordner verbinden und Projektstruktur aufbauen
- Projektgebiet laden, Template-Layer optional per Button hinzufuegen
- Betreiberliste und Datenquellen projektweit pflegen und auf ausgewaehlte Layer anwenden
- Butler-Profil direkt im QGIS-Projekt speichern, ohne zusaetzliche JSON-Datei

Release-Hinweis:

- Die veroeffentlichte QGIS-Installation laeuft ueber `trassify_master_tools`.
- Fuer Butler-Aenderungen synchronisiert `python3 tools/release_projektstarter_butler.py` die Butler- und Bundle-Version und erzeugt `plugins.xml` plus `trassify_master_tools.zip` neu.
- Auf GitHub erledigt `.github/workflows/release-projektstarter-butler.yml` diesen Schritt automatisch nach einem Push auf `main`.
