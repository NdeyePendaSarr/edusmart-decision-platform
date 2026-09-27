"""
pipeline/meta.py — Métadonnées et journal d'exécution (Phase 6, Lot L4)
======================================================================

    MetaStore(conn)
        .init_schema()               DDL meta + staging (idempotent)
        .sync_sources(emplacements)  17 lignes de meta.metadata_sources, depuis le registre
        .step(batch, etape, obj)     gestionnaire de contexte : écrit une ligne
                                     etl_execution_log (EN_COURS -> SUCCES / ECHEC),
                                     avec durée, nombre de lignes et message d'erreur

Chaque ligne du journal est VALIDÉE immédiatement (autocommit) : même si le
pipeline s'arrête brutalement, la trace de l'étape en échec est conservée.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from pipeline.registry import OBJECTS, PIPELINE_VERSION, SourceObject, objects_of

SQL_DIR = Path(__file__).resolve().parent / "sql"
DDL_FILES = (SQL_DIR / "meta" / "01_meta_tables.sql", SQL_DIR / "staging" / "01_staging_tables.sql")


class StepResult:
    """Objet rempli par l'étape : nombre de lignes traitées."""

    def __init__(self):
        self.nb_lignes: int | None = None


class MetaStore:
    def __init__(self, conn):
        self.conn = conn
        self.conn.autocommit = True

    def init_schema(self) -> None:
        with self.conn.cursor() as cur:
            for path in DDL_FILES:
                cur.execute(path.read_text(encoding="utf-8"))

    def sync_sources(self, emplacements: dict[str, str]) -> None:
        """Insère ou met à jour la partie descriptive des 17 objets (l'état d'extraction est conservé)."""
        with self.conn.cursor() as cur:
            for o in OBJECTS:
                cur.execute("""
                    INSERT INTO meta.metadata_sources (code_source, objet, technologie, emplacement, table_staging,
                        nb_colonnes, encodage, separateur, description, version_schema)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (code_source, objet) DO UPDATE SET technologie = EXCLUDED.technologie,
                        emplacement = EXCLUDED.emplacement, table_staging = EXCLUDED.table_staging,
                        nb_colonnes = EXCLUDED.nb_colonnes, encodage = EXCLUDED.encodage,
                        separateur = EXCLUDED.separateur, description = EXCLUDED.description,
                        version_schema = EXCLUDED.version_schema, mis_a_jour_le = CURRENT_TIMESTAMP""",
                            (o.source, o.objet, o.technologie, emplacements.get(o.source, ""),
                             f"staging.{o.stg_table}", len(o.colonnes), o.encodage, o.separateur or None,
                             o.description, o.version_schema))

    def record_extraction(self, batch_id: str, obj: SourceObject, extracted_at: datetime, nb: int, statut: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE meta.metadata_sources SET derniere_extraction = %s, dernier_batch_id = %s,
                               derniere_nb_lignes = %s, dernier_statut = %s, mis_a_jour_le = CURRENT_TIMESTAMP
                           WHERE code_source = %s AND objet = %s""",
                        (extracted_at, batch_id, nb, statut, obj.source, obj.objet))

    def record_failure(self, batch_id: str, etape: str, source: str, message: str) -> int:
        """
        Trace l'échec d'une source ENTIÈRE (ex. connexion refusée avant toute lecture) :
        une ligne ECHEC par objet qui n'a pas encore de trace pour ce lot et cette étape.
        Retourne le nombre de lignes ajoutées.
        """
        maintenant, ajoutees = datetime.now(), 0
        with self.conn.cursor() as cur:
            for obj in objects_of(source):
                cur.execute("""SELECT 1 FROM meta.etl_execution_log
                               WHERE batch_id = %s AND etape = %s AND code_source = %s AND objet = %s""",
                            (batch_id, etape, source, obj.objet))
                if cur.fetchone():
                    continue
                cur.execute("""INSERT INTO meta.etl_execution_log (batch_id, etape, code_source, objet, date_debut,
                                   date_fin, duree_secondes, nb_lignes, nb_erreurs, erreurs, statut, version_pipeline)
                               VALUES (%s, %s, %s, %s, %s, %s, 0, 0, 1, %s, 'ECHEC', %s)""",
                            (batch_id, etape, source, obj.objet, maintenant, maintenant, message[:2000],
                             PIPELINE_VERSION))
                if etape == "EXTRACT":
                    self.record_extraction(batch_id, obj, maintenant, 0, "ECHEC")
                ajoutees += 1
        return ajoutees

    @contextmanager
    def step(self, batch_id: str, etape: str, source: str, objet: str) -> Iterator[StepResult]:
        debut, t0 = datetime.now(), time.perf_counter()
        with self.conn.cursor() as cur:
            cur.execute("""INSERT INTO meta.etl_execution_log (batch_id, etape, code_source, objet, date_debut,
                               statut, version_pipeline) VALUES (%s, %s, %s, %s, %s, 'EN_COURS', %s)
                           RETURNING id_execution""", (batch_id, etape, source, objet, debut, PIPELINE_VERSION))
            id_execution = cur.fetchone()[0]
        result = StepResult()
        try:
            yield result
        except Exception as exc:
            self._close(id_execution, t0, result.nb_lignes, "ECHEC", f"{type(exc).__name__}: {exc}"[:2000])
            raise
        self._close(id_execution, t0, result.nb_lignes, "SUCCES", None)

    def _close(self, id_execution: int, t0: float, nb: int | None, statut: str, erreur: str | None) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""UPDATE meta.etl_execution_log SET date_fin = %s, duree_secondes = %s, nb_lignes = %s,
                               nb_erreurs = %s, erreurs = %s, statut = %s WHERE id_execution = %s""",
                        (datetime.now(), round(time.perf_counter() - t0, 3), nb, 0 if erreur is None else 1,
                         erreur, statut, id_execution))
