"""
pipeline/extract_csv.py — Extraction de la Source 3 CSV RH (Lot L4)
==================================================================

Lit les 4 exports RH avec l'encodage et le séparateur DÉCLARÉS dans
sources/s3_csv/create_source.SCHEMAS (jamais devinés) :
    enseignants, departements : UTF-8, ','   ·   salaires, absences : ISO-8859-1, ';'
Contrôles bloquants : en-tête conforme au PDF, même nombre de champs sur chaque ligne.
Aucune valeur n'est modifiée : un champ vide reste une chaîne vide (et non NULL),
les dates restent dans leur format d'origine, les doublons sont conservés.

Exécution seule : python -m pipeline.extract_csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from pipeline.extract_common import extract_object
from pipeline.landing import Batch, new_batch_id
from pipeline.registry import objects_of
from sources.s3_csv.create_source import OUTPUT_DIR, SCHEMAS

SOURCE = "s3_csv"


class FormatCSVError(ValueError):
    """Fichier non conforme à la structure déclarée."""


def lire_csv(path: Path, key: str):
    schema = SCHEMAS[key]
    with path.open(encoding=schema.encodage, errors="strict", newline="") as handle:
        reader = csv.reader(handle, delimiter=schema.separateur)
        entete = next(reader)
        if entete != schema.entetes:
            raise FormatCSVError(f"{path.name} : en-tête {entete} différent du PDF {schema.entetes}")
        for numero, row in enumerate(reader, start=2):
            if len(row) != len(schema.entetes):
                raise FormatCSVError(f"{path.name} ligne {numero} : {len(row)} champs au lieu de {len(schema.entetes)}")
            yield row


def extract(batch: Batch, meta=None, dossier: Path = OUTPUT_DIR) -> dict[str, int]:
    resultats = {}
    for obj in objects_of(SOURCE):
        path = dossier / SCHEMAS[obj.objet].nom
        resultats[obj.objet] = extract_object(batch, obj, lambda p=path, k=obj.objet: lire_csv(p, k), str(path), meta)
    return resultats


if __name__ == "__main__":
    print(extract(Batch(new_batch_id())))
    sys.exit(0)
