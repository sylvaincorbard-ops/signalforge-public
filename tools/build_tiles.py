#!/usr/bin/env python3
"""
Snapshot ANFR « Données sur les réseaux mobiles » → tuiles JSON de 0,25°.

Source : https://www.data.gouv.fr/datasets/donnees-sur-les-reseaux-mobiles
(même jeu que l'API data.anfr.fr `observatoire_2g_3g_4g` lue par l'app),
publié chaque semaine. Licence Ouverte 2.0 (Etalab) : réutilisation
commerciale autorisée, mention obligatoire de la source et de la date de
mise à jour — reprises dans index.json pour que l'app les affiche.

Sortie (dossier --out) :
  index.json            métadonnées du snapshot + liste des tuiles existantes
  tiles/<ky>_<kx>.json  une tuile par cellule de TILE_DEG × TILE_DEG degrés,
                        ky = floor(lat / TILE_DEG), kx = floor(lng / TILE_DEG)

Format d'une tuile (v1), compact et déterministe (trié par sup_id) :
  {"v":1,"k":"<ky>_<kx>","s":[
    [sup_id, lat, lng, sup_nm_haut, nat_id, tpo_id,
     adr_lb_lieu, adr_lb_add1, adr_lb_add2, adr_lb_add3, adr_nm_cp,
     [[adm_lb_nom, generation, emr_lb_systeme, statut, list_azimut], ...]],
    ...]}
Champ CSV vide → null (l'API omet le champ : l'app le reconstruit absent,
cf. services/anfrTiles.ts::tileToRecords, pour garder la parité exacte avec
recordsToTowers). statut codé sur une lettre (STATUS_CODES). list_azimut
conservé tel quel ("90|240") — pas encore lu par l'app (V1.1 Secteurs).

Usage :
  python3 build_tiles.py --download --out ./public
  python3 build_tiles.py --csv observatoireOd_20261029.csv --snapshot 20261029 --out ./public
  ... --previous ./ancien/index.json   (garde-fou ±10 % sur le nombre de lignes)

Aucune dépendance hors bibliothèque standard. Code de sortie ≠ 0 et rien
d'écrit si la validation échoue — l'ancien snapshot reste alors en ligne.
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

TILE_DEG = 0.25
FORMAT_VERSION = 1
DATASET_API = 'https://www.data.gouv.fr/api/1/datasets/donnees-sur-les-reseaux-mobiles/'
DATASET_PAGE = 'https://www.data.gouv.fr/datasets/donnees-sur-les-reseaux-mobiles'
LICENSE = 'Licence Ouverte 2.0 (Etalab)'
PRODUCER = 'ANFR'

# Les 13 champs lus par l'app (services/anfrQuery.ts::ANFR_FIELDS) + statut
# et list_azimut. Un en-tête sans l'un d'eux = changement de schéma ANFR →
# échec, pas de publication.
REQUIRED_COLUMNS = [
    'sup_id', 'coordonnees', 'adm_lb_nom', 'generation', 'sup_nm_haut',
    'nat_id', 'tpo_id', 'emr_lb_systeme',
    'adr_lb_lieu', 'adr_lb_add1', 'adr_lb_add2', 'adr_lb_add3', 'adr_nm_cp',
    'statut', 'list_azimut',
]
STATUS_CODES = {
    'En service': 'S',
    'Techniquement opérationnel': 'T',
    'Projet approuvé': 'P',
}
MIN_ROWS = 500_000              # export du 29/10/2026 : 821 309 lignes
MAX_ROW_DRIFT = 0.10            # ±10 % par rapport au snapshot précédent
MAX_BAD_COORD_RATIO = 0.001     # au-delà, le format des coordonnées a changé


class ValidationError(Exception):
    pass


def tile_key(lat: float, lng: float) -> str:
    return f'{math.floor(lat / TILE_DEG)}_{math.floor(lng / TILE_DEG)}'


def none_if_empty(v):
    v = (v or '').strip()
    return v if v else None


def parse_coord(raw: str):
    # "46.177499999999995 , 3.3741666666666665"
    parts = [p.strip() for p in (raw or '').split(',')]
    if len(parts) != 2:
        return None
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 6), round(lng, 6)


def http_get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'signalforge-anfr-tiles/1'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_resource() -> dict:
    """Ressource ZIP la plus récente du jeu data.gouv (les URL changent à
    chaque publication : jamais en dur)."""
    meta = json.loads(http_get(DATASET_API, timeout=60))
    zips = [r for r in meta.get('resources', [])
            if (r.get('format') or '').lower() == 'zip' and 'observatoire' in (r.get('title') or '').lower()]
    if not zips:
        raise ValidationError('aucune ressource ZIP « observatoire » sur data.gouv')
    zips.sort(key=lambda r: r.get('last_modified') or '', reverse=True)
    return zips[0]


def snapshot_id_from(title: str, last_modified: str) -> str:
    m = re.search(r'(20\d{6})', title or '')
    if m:
        return m.group(1)
    return (last_modified or '')[:10].replace('-', '')


def download_csv(workdir: str):
    res = latest_resource()
    snap = snapshot_id_from(res.get('title'), res.get('last_modified'))
    print(f'[anfr-tiles] ressource : {res["title"]} ({res.get("filesize")} o) — snapshot {snap}')
    data = http_get(res['url'], timeout=600)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(csv_names) != 1:
            raise ValidationError(f'ZIP inattendu : {z.namelist()}')
        path = os.path.join(workdir, os.path.basename(csv_names[0]))
        with z.open(csv_names[0]) as src, open(path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
    return path, snap, res['url']


def read_sites(csv_path: str):
    with open(csv_path, encoding='utf-8', newline='') as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = ';' if sample.count(';') > sample.count(',') else ','
        reader = csv.DictReader(f, delimiter=delimiter)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValidationError(f'colonnes absentes de l\'export : {missing}')

        rows = bad = 0
        unknown_status = {}
        sites = {}
        for r in reader:
            rows += 1
            coord = parse_coord(r['coordonnees'])
            sup_id = none_if_empty(r['sup_id'])
            if coord is None or sup_id is None:
                bad += 1
                continue
            statut = (r['statut'] or '').strip()
            code = STATUS_CODES.get(statut)
            if code is None:
                unknown_status[statut] = unknown_status.get(statut, 0) + 1
                code = statut or None  # conservé en clair : l'app le traite comme « autre »
            emitter = [
                none_if_empty(r['adm_lb_nom']), none_if_empty(r['generation']),
                none_if_empty(r['emr_lb_systeme']), code, none_if_empty(r['list_azimut']),
            ]
            s = sites.get(sup_id)
            if s is None:
                # Champs du support : identiques d'une ligne à l'autre d'un même
                # sup_id (vérifié sur l'export du 29/10 : 1 seul écart sur
                # 72 940 sites, une adresse vide) — la première ligne fait foi,
                # comme recordsToTowers côté app.
                s = sites[sup_id] = [
                    sup_id, coord[0], coord[1],
                    none_if_empty(r['sup_nm_haut']), none_if_empty(r['nat_id']), none_if_empty(r['tpo_id']),
                    none_if_empty(r['adr_lb_lieu']), none_if_empty(r['adr_lb_add1']),
                    none_if_empty(r['adr_lb_add2']), none_if_empty(r['adr_lb_add3']),
                    none_if_empty(r['adr_nm_cp']),
                    [],
                ]
            s[11].append(emitter)
    return rows, bad, unknown_status, sites


def validate(rows: int, bad: int, previous_rows):
    if rows < MIN_ROWS:
        raise ValidationError(f'{rows} lignes < minimum {MIN_ROWS}')
    if bad / rows > MAX_BAD_COORD_RATIO:
        raise ValidationError(f'{bad} lignes sans coordonnées/sup_id exploitables ({bad / rows:.2%})')
    if previous_rows:
        drift = abs(rows - previous_rows) / previous_rows
        if drift > MAX_ROW_DRIFT:
            raise ValidationError(f'{rows} lignes vs {previous_rows} au snapshot précédent ({drift:.1%} > {MAX_ROW_DRIFT:.0%})')


def sort_key(sup_id: str):
    return (0, int(sup_id), '') if sup_id.isdigit() else (1, 0, sup_id)


def build(csv_path: str, snapshot: str, out_dir: str, resource_url, previous_index):
    rows, bad, unknown_status, sites = read_sites(csv_path)
    previous_rows = None
    if previous_index and os.path.exists(previous_index):
        with open(previous_index, encoding='utf-8') as f:
            previous_rows = json.load(f).get('rows')
    validate(rows, bad, previous_rows)
    if unknown_status:
        print(f'[anfr-tiles] ⚠️ statuts inconnus conservés en clair : {unknown_status}')

    tiles = {}
    for s in sites.values():
        tiles.setdefault(tile_key(s[1], s[2]), []).append(s)

    # Écriture dans un dossier temporaire puis bascule : jamais de sortie à
    # moitié écrite en cas d'erreur.
    tmp = out_dir.rstrip('/') + '.tmp'
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(os.path.join(tmp, 'tiles'))
    index_tiles = {}
    for key in sorted(tiles):
        site_list = sorted(tiles[key], key=lambda s: sort_key(s[0]))
        for s in site_list:
            s[11].sort(key=lambda e: tuple(x or '' for x in e))
        body = json.dumps({'v': FORMAT_VERSION, 'k': key, 's': site_list},
                          ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        with open(os.path.join(tmp, 'tiles', f'{key}.json'), 'wb') as f:
            f.write(body)
        index_tiles[key] = [len(site_list), len(body), hashlib.sha1(body).hexdigest()[:12]]

    source_date = f'{snapshot[:4]}-{snapshot[4:6]}-{snapshot[6:8]}' if re.fullmatch(r'20\d{6}', snapshot) else snapshot
    index = {
        'v': FORMAT_VERSION,
        'snapshot': snapshot,
        'sourceDate': source_date,
        'producer': PRODUCER,
        'dataset': 'Données sur les réseaux mobiles',
        'datasetUrl': DATASET_PAGE,
        'resourceUrl': resource_url,
        'license': LICENSE,
        'generatedAt': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        'tileDeg': TILE_DEG,
        'rows': rows,
        'sites': len(sites),
        'statusCodes': {v: k for k, v in STATUS_CODES.items()},
        # [nb de sites, octets bruts, sha1 tronqué] — l'app sait quelles tuiles
        # existent (pas de requête vers la mer) et détecte un contenu changé.
        'tiles': index_tiles,
    }
    with open(os.path.join(tmp, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, separators=(',', ':'))

    shutil.rmtree(out_dir, ignore_errors=True)
    os.replace(tmp, out_dir)
    total = sum(v[1] for v in index_tiles.values())
    print(f'[anfr-tiles] {rows} lignes, {len(sites)} sites, {bad} lignes ignorées → '
          f'{len(index_tiles)} tuiles, {total / 1e6:.1f} Mo bruts — {out_dir}')
    return index


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument('--csv', help='CSV ANFR déjà extrait')
    src.add_argument('--download', action='store_true', help='télécharge la dernière ressource data.gouv')
    p.add_argument('--snapshot', help='identifiant AAAAMMJJ (obligatoire avec --csv)')
    p.add_argument('--out', required=True, help='dossier de sortie (remplacé)')
    p.add_argument('--previous', help='index.json du snapshot précédent (garde-fou ±10 %%)')
    p.add_argument('--skip-if-same', help='index.json publié : sortie 0 sans rien faire si même snapshot')
    a = p.parse_args(argv)

    try:
        if a.download:
            if a.skip_if_same and os.path.exists(a.skip_if_same):
                res = latest_resource()
                snap = snapshot_id_from(res.get('title'), res.get('last_modified'))
                with open(a.skip_if_same, encoding='utf-8') as f:
                    if json.load(f).get('snapshot') == snap:
                        print(f'[anfr-tiles] snapshot {snap} déjà publié — rien à faire')
                        return 0
            with tempfile.TemporaryDirectory() as wd:
                csv_path, snap, url = download_csv(wd)
                build(csv_path, snap, a.out, url, a.previous)
        else:
            if not a.snapshot:
                p.error('--snapshot est obligatoire avec --csv')
            build(a.csv, a.snapshot, a.out, None, a.previous)
    except ValidationError as e:
        print(f'[anfr-tiles] ❌ validation : {e} — rien n\'est publié', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
