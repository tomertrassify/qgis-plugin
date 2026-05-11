# Custom Toolbar Overlay

QGIS-Plugin zum Aufraeumen der oberen Werkzeugleisten:

- vorhandene Standardleisten ein- oder ausblenden
- eigene kompakte Werkzeugleisten anlegen
- vorhandene QGIS-Standardleisten direkt als Kopie uebernehmen und dann anpassen
- vorhandene QGIS-Toolbar-Tools in beliebiger Reihenfolge kombinieren
- Werkzeuge werden ueber statische Proxy-Kopien dupliziert, Originalleisten bleiben also erhalten
- Dropdown-Unteraktionen aus Toolbar-Menues in der Toolliste finden
- eigene Dropdown-Gruppen aus mehreren QGIS-Aktionen bauen
- native QGIS-Dropdown-Buttons koennen als echte Dropdown-Buttons uebernommen werden
- widget-basierte QGIS-Toolbar-Buttons wie spezielle Digitalisierungs-Buttons werden ebenfalls erkannt, auch wenn QGIS Hauptaktion und Dropdown intern auf getrennte verschachtelte Knöpfe aufteilt
- Tools aus Nebenfenstern wie Georeferenzierer werden aus Sicherheitsgruenden nicht als generische Quelle uebernommen
- Sichtbarkeit von Werkzeugleisten wird mit direkten QGIS-Aenderungen synchronisiert
- Positionen eigener Werkzeugleisten bleiben beim Speichern erhalten und werden nach normalem QGIS-Neustart wiederhergestellt
- deaktivierte QGIS-Werkzeuge werden in Custom-Toolbars ebenfalls ausgegraut, auch wenn QGIS intern nur den Original-Toolbar-Button deaktiviert
- Toolbar-Debug-Export fuer problematische QGIS-Sonderbuttons
- deaktivierte Custom-Buttons rendern ihr Icon explizit im Disabled-Zustand
- native QGIS-Dropdown-Buttons uebernehmen beim Wechsel auch das aktuell aktive Unterwerkzeug-Icon
- Presets als JSON importieren und exportieren
- Branding-Logo per Checkbox links oben einblenden
- Plugin-Button per Checkbox in der QGIS-Toolbar anzeigen
- Reset-Button fuer Rueckkehr zum sichtbaren QGIS-Standard
- Einstellungen zwischen QGIS-Sitzungen speichern
- schlichte native Qt-Dialogoberflaeche ohne Custom-Styling

## Installation

1. Den Ordner [custom_toolbar_overlay](/Users/tomermaith/Documents/qgis-favorite-tools/custom_toolbar_overlay) nach
   `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   kopieren.
2. QGIS neu starten oder den Plugin-Ordner neu laden.
3. Das Plugin `Custom Toolbar Overlay` im QGIS-Pluginmanager aktivieren.

## Nutzung

1. `Plugins -> Custom Toolbar Overlay -> Eigene Werkzeugleisten konfigurieren` oeffnen.
2. Optional `Branding-Logo links oben anzeigen` und `Plugin-Button in QGIS-Toolbar anzeigen` aktivieren.
3. Im Dialog Standardleisten abwaehlen, die nicht sichtbar sein sollen.
4. Eigene Werkzeugleisten anlegen oder per `Aus Standardleiste kopieren` eine QGIS-Leiste als Ausgangspunkt duplizieren.
5. Gewuenschte Tools einzeln oder als eigenes Dropdown aus der mittleren Liste hinzufuegen.
6. Reihenfolge speichern.

## Debug-Export

- `Plugins -> Custom Toolbar Overlay -> Toolbar-Debug exportieren`
- Die erzeugte JSON-Datei kann direkt zum Analysieren von QGIS-Sonderbuttons weitergegeben werden.

Shortcut: `Ctrl+Alt+T`

## Presets

- Im Bereich `Vorlagen` lassen sich eingebaute Vorlagen anwenden.
- `Preset exportieren` schreibt die aktuelle Konfiguration als JSON-Datei.
- `Preset importieren` laedt eine solche JSON-Datei wieder in den Dialog.
- Wenn du mir spaeter ein exportiertes Preset schickst, kann ich es direkt als eingebaute Vorlage unter [custom_toolbar_overlay/presets](/Users/tomermaith/Documents/qgis-favorite-tools/custom_toolbar_overlay/presets) mitliefern.
