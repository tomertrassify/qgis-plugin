# Sparte Betreiber Regeln

Dieses Plugin fuegt einen checkbaren Toggle hinzu.

Wenn der Toggle aktiv ist, wird der aktuell aktive Vektor-Layer automatisch
ueber die Felder `Sparte` und `Betreiber` als verschachtelter
`QgsRuleBasedRenderer` gepflegt:

- Oberste Ebene: jede `Sparte`
- Unter jeder `Sparte`: die gefundenen `Betreiber`
- Farben pro `Sparte` bleiben stabil und verschieben sich nicht, wenn spaeter neue Werte hinzukommen

Das Plugin reagiert auf Attributaenderungen, neue Features und relevante Commit-Signale,
solange der aktive Layer die beiden Felder `Sparte` und `Betreiber` enthaelt.
