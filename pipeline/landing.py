"""
pipeline/landing.py — Zone d'atterrissage (landing) des lots (Lot L4)
====================================================================

Entre l'extraction et le chargement, chaque objet est écrit dans
    data/landing/<batch_id>/<source>/<objet>.csv
au MÊME format pour toutes les sources :
    - UTF-8, séparateur ',', guillemets si nécessaire, fins de ligne '\\n' ;
    - NULL écrit \\N (sans guillemets), chaîne vide écrite "" : les deux restent distincts ;
    - colonnes source + colonnes techniques (_batch_id, _source, _extracted_at, _row_number).

Le fichier a donc exactement la forme de la table de staging : load.py se
réduit à un COPY. Un manifeste (manifest.json) récapitule le lot : lignes
extraites et empreinte de chaque objet, utilisées par la porte G2.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from common.config import get_settings
from pipeline.registry import NULL_MARKER, SourceObject

SEP_CHAMP, SEP_LIGNE = "\x1f", "\x1e"   # séparateurs de l'empreinte (unité et enregistrement ASCII)


def new_batch_id(now: datetime | None = None) -> str:
    """Identifiant de lot lisible et triable : B20260927T104512."""
    return (now or datetime.now()).strftime("B%Y%m%dT%H%M%S")


@dataclass
class Batch:
    batch_id: str
    extracted_at: datetime = field(default_factory=lambda: datetime.now().replace(microsecond=0))
    root: Path | None = None

    @property
    def dir(self) -> Path:
        return (self.root or get_settings().paths.data_dir / "landing") / self.batch_id

    def path(self, obj: SourceObject) -> Path:
        return self.dir / obj.source / obj.landing_file

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def tech_values(self, obj: SourceObject, row_number: int) -> list[str]:
        return [self.batch_id, obj.source, self.extracted_at.strftime("%Y-%m-%d %H:%M:%S"), str(row_number)]


class Empreinte:
    """Empreinte MD5 incrémentale d'une suite de lignes (colonnes source uniquement)."""

    def __init__(self):
        self._md5, self._premiere = hashlib.md5(), True

    def ajouter(self, valeurs: Sequence[str | None]) -> None:
        ligne = SEP_CHAMP.join(NULL_MARKER if v is None else v for v in valeurs)
        self._md5.update(((SEP_LIGNE if not self._premiere else "") + ligne).encode("utf-8"))
        self._premiere = False

    def hexdigest(self) -> str:
        return self._md5.hexdigest()


def write_landing(batch: Batch, obj: SourceObject, rows: Iterable[Sequence[str | None]]) -> tuple[int, str]:
    """
    Écrit les lignes (valeurs source en texte, None = NULL) et retourne
    (nombre de lignes, empreinte). Écriture atomique.
    """
    path = batch.path(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    empreinte, n = Empreinte(), 0
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{obj.objet}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(obj.toutes_colonnes)
            for n, valeurs in enumerate(rows, start=1):
                if len(valeurs) != len(obj.colonnes):
                    raise ValueError(f"{obj.source}.{obj.objet} ligne {n} : {len(valeurs)} valeurs, "
                                     f"{len(obj.colonnes)} attendues")
                empreinte.ajouter(valeurs)
                writer.writerow([NULL_MARKER if v is None else v for v in valeurs] + batch.tech_values(obj, n))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return n, empreinte.hexdigest()


def read_landing(batch: Batch, obj: SourceObject):
    """Relit un fichier d'atterrissage : génère les valeurs source (\\N -> None)."""
    with batch.path(obj).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        entete = next(reader)
        if tuple(entete) != obj.toutes_colonnes:
            raise ValueError(f"En-tête inattendu dans {batch.path(obj)}")
        k = len(obj.colonnes)
        for row in reader:
            yield [None if v == NULL_MARKER else v for v in row[:k]]


def update_manifest(batch: Batch, obj: SourceObject, nb_lignes: int, empreinte: str, source_info: str) -> None:
    """Ajoute ou remplace l'entrée d'un objet dans le manifeste du lot."""
    manifest = read_manifest(batch) if batch.manifest_path.exists() else {
        "batch_id": batch.batch_id, "extracted_at": batch.extracted_at.isoformat(sep=" "), "objets": {}}
    manifest["objets"][f"{obj.source}.{obj.objet}"] = {
        "source": obj.source, "objet": obj.objet, "table_staging": obj.stg_table, "fichier": str(batch.path(obj)),
        "nb_lignes": nb_lignes, "empreinte": empreinte, "emplacement": source_info,
    }
    batch.dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=batch.dir, prefix=".manifest_", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        json.dump(manifest, h, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, batch.manifest_path)


def read_manifest(batch: Batch) -> dict:
    return json.loads(batch.manifest_path.read_text(encoding="utf-8"))


def latest_batch(root: Path | None = None) -> Batch:
    """Le lot le plus récent présent dans data/landing/ (pour relancer un chargement)."""
    base = root or get_settings().paths.data_dir / "landing"
    lots = sorted(p.name for p in base.glob("B*") if (p / "manifest.json").exists())
    if not lots:
        raise FileNotFoundError(f"Aucun lot dans {base} : lancez d'abord l'extraction")
    manifest = json.loads((base / lots[-1] / "manifest.json").read_text(encoding="utf-8"))
    return Batch(lots[-1], datetime.fromisoformat(manifest["extracted_at"]), root)
