# signalforge-public

Dépôt public des fichiers SignalForge lus par l'app Antenna Align Pro.
Aucune donnée de site opérateur non publique.

## Contenu

- `data/app_version.json` — `{ latestVersion, iosUrl, androidUrl, notes }`, lu
  au lancement de l'app pour proposer une mise à jour. Mis à jour
  **manuellement** à chaque nouveau build à proposer.
- **Snapshot ANFR en tuiles** — données publiques ouvertes de l'ANFR
  (« Données sur les réseaux mobiles », data.gouv.fr, **Licence Ouverte 2.0**),
  découpées en tuiles de 0,25° et servies par Cloudflare Pages :
  `https://signalforge-anfr.pages.dev/index.json` et `/tiles/<ky>_<kx>.json`.
  - `tools/build_tiles.py` — téléchargement de la dernière publication
    data.gouv, validation, génération (bibliothèque standard Python).
  - `.github/workflows/anfr-tiles.yml` — tous les jours à 16h UTC, ne republie
    que si l'ANFR a publié une nouvelle version (hebdomadaire, le jeudi).
    Lancement manuel : onglet Actions → anfr-tiles → Run workflow
    (`force` pour republier le même snapshot).
  - `data/anfr/index.json` — copie de l'index publié, commitée à chaque
    publication (trace des snapshots + évite la désactivation des workflows
    planifiés après 60 jours sans activité). Les tuiles ne sont **pas**
    versionnées ici.
  - Secrets requis : `CLOUDFLARE_API_TOKEN` (Cloudflare Pages : Edit),
    `CLOUDFLARE_ACCOUNT_ID`.

Source des données : ANFR — Données sur les réseaux mobiles,
https://www.data.gouv.fr/datasets/donnees-sur-les-reseaux-mobiles

## Historique

Remplace la partie manifeste de `signalforge-data`, qui est passé privé
(hébergeait aussi des données de sites opérateur non publiques, retirées de
l'app cliente).
