# signalforge-public

Dépôt public minimal contenant **uniquement** le manifeste de vérification de
version in-app d'Antenna Align Pro (et de tout autre projet SignalForge qui
voudrait le réutiliser). Aucune autre donnée — en particulier, aucune donnée
de site opérateur.

## Contenu

- `data/app_version.json` — `{ latestVersion, updateUrl, notes }`, lu au
  lancement de l'app pour proposer une mise à jour. Mis à jour **manuellement**
  à chaque nouveau build à proposer, aucune automatisation pour l'instant.

## Historique

Remplace la partie manifeste de `signalforge-data`, qui est passé privé
(hébergeait aussi des données de sites opérateur non publiques, retirées de
l'app cliente).
