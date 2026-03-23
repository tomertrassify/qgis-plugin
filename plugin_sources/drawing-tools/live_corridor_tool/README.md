# Schutzrohr (QGIS Plugin)

## Funktion
- Aktion wird bevorzugt in die QGIS-Digitalisierungsleiste eingebunden (rechts neben dem Stützpunkt-Werkzeug). Fallback: eigene `Schutzrohr`-Toolbar.
- Mit dem **normalen QGIS-Werkzeug \"Linienobjekt hinzufügen\"** zeichnen (Snapping/Magnet/Tracing bleiben normal aktiv).
- Toggle kann während derselben Linie an/aus geschaltet werden.
- `Option/Alt` (macOS) oder `Alt/Strg + Mausrad` (Windows/Linux): Abstand links/rechts live ändern.
- Permanente Live-Anzeige der aktuellen Breite in der QGIS-Statusleiste.
- Der eingestellte Abstand gilt sofort für Vorschau **und** erzeugte Geometrien.
- Wenn Toggle **AN** ist, gibt es Live-Vorschau und der aktuelle Abschnitt wird für den Korridor gesammelt.
- Wenn Toggle **AUS** geschaltet wird, wird der Korridor sofort für genau diesen ON-Abschnitt erzeugt.
- Danach kann dieselbe normale Linie direkt weitergezeichnet werden.
- Bei Rechtsklick/Enter wird ein noch aktiver ON-Abschnitt ebenfalls abgeschlossen.
- Der Toggle ist in QGIS-Kurzbefehlen verfügbar: `Einstellungen -> Tastenkürzel`, nach `Schutzrohr` suchen und Taste setzen.

## Einstellungen
Über `Schutzrohr Einstellungen` können folgende Optionen gesetzt werden:
- Abstand je Seite als Eingabefeld (zusätzlich zum Mausrad).
- Nur-Box-Modus (ohne Mittellinie): zeichnet nur die Box, blockiert dabei das native Linienzeichnen während Toggle AN.
- Ausgabe in aktivem Linienlayer oder in temporärem Layer.
- Bei temporärem Layer: Box als Linien- oder Polygon-Geometrie ohne Attribute erzeugen.

## Hinweis
- Im Nur-Box-Modus bleibt die Live-Vorschau aktiv, es wird aber keine Mittellinie mitgezeichnet oder erzeugt.
- Aktivierung ist nur mit aktivem **editierbarem Linienlayer** möglich.
- Ohne Nur-Box-Modus kann der Toggle nur im Werkzeug **Linienobjekt hinzufügen** aktiviert werden.
- Mit Nur-Box-Modus wird beim Aktivieren auf einen eigenen Zeichenmodus gewechselt (Linienobjekt hinzufügen/Stützpunktwerkzeug nicht aktiv).
- Wenn im Nur-Box-Modus ein anderes Werkzeug aktiviert wird, schaltet sich der Toggle automatisch aus.
- Ist Aktivierung im aktuellen Kontext nicht erlaubt, wird das Toggle-Icon ausgegraut.
