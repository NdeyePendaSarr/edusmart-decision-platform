"""
common/anomaly_journal.py — Journal des anomalies injectées (Lot L2)
====================================================================

Rôle
    Chaque anomalie volontaire (PDF) est enregistrée au moment de son
    injection : code, table, colonne, identifiant de la ligne, valeur avant,
    valeur après. Ce journal est la « vérité terrain » :
    - porte G1 : prouver que chaque type d'anomalie demandé est présent,
      au bon taux (2 à 5 %) ;
    - Phase 15 : vérifier que le pipeline ETL détecte TOUTES les anomalies.

    Comme le référentiel maître, ce journal n'est JAMAIS lu par l'ETL.

Réutilisé par les 5 sources (L2-a à L2-e).
"""

from __future__ import annotations

import csv
import os
import tempfile
from collections import Counter
from dataclasses import astuple, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class AnomalyType:
    """Définition d'un type d'anomalie et de sa justification dans les PDF."""

    code: str
    table: str
    colonne: str
    description: str
    source_pdf: str


@dataclass(frozen=True)
class AnomalyRecord:
    code: str
    table: str
    colonne: str
    id_ligne: str
    valeur_originale: str
    valeur_injectee: str


JOURNAL_COLUMNS = [f.name for f in fields(AnomalyRecord)]


class AnomalyJournal:
    """Collecte les anomalies d'une source puis les écrit en CSV."""

    def __init__(self, source: str, types: dict[str, AnomalyType]):
        self.source = source
        self.types = types
        self.records: list[AnomalyRecord] = []

    def add(self, code: str, id_ligne: str, valeur_originale, valeur_injectee) -> None:
        if code not in self.types:
            raise KeyError(f"Type d'anomalie inconnu : {code}")
        t = self.types[code]
        self.records.append(AnomalyRecord(
            code, t.table, t.colonne, str(id_ligne),
            "" if valeur_originale is None else str(valeur_originale),
            "" if valeur_injectee is None else str(valeur_injectee),
        ))

    def counts(self) -> dict[str, int]:
        """Nombre d'anomalies par code (0 pour les types jamais injectés)."""
        c = Counter(r.code for r in self.records)
        return {code: c.get(code, 0) for code in self.types}

    def write_csv(self, path: Path) -> int:
        """Écriture atomique ; retourne le nombre de lignes écrites."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(JOURNAL_COLUMNS)
                writer.writerows(astuple(r) for r in self.records)
            os.replace(tmp, path)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise
        return len(self.records)


def read_journal(path: Path) -> list[AnomalyRecord]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [AnomalyRecord(**row) for row in csv.DictReader(handle)]
