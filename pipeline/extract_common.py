"""
pipeline/extract_common.py — Logique commune aux 5 extracteurs (Lot L4)
======================================================================

extract_object() : pour UN objet source
    1. ouvre une étape EXTRACT dans meta.etl_execution_log (si un MetaStore est fourni) ;
    2. écrit les lignes dans la zone d'atterrissage (valeurs en texte, None = NULL) ;
    3. enregistre le nombre de lignes et l'empreinte dans le manifeste du lot ;
    4. met à jour meta.metadata_sources (dernière extraction, statut).
Aucune valeur n'est modifiée : l'extracteur fournit les valeurs TELLES QUE LUES.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from common.logger import get_logger
from pipeline.landing import Batch, update_manifest, write_landing
from pipeline.registry import SourceObject

logger = get_logger("extract")


def extract_object(batch: Batch, obj: SourceObject, rows: Callable[[], Iterable[Sequence[str | None]]],
                   emplacement: str, meta=None) -> int:
    if meta is None:
        n, empreinte = write_landing(batch, obj, rows())
    else:
        try:
            with meta.step(batch.batch_id, "EXTRACT", obj.source, obj.objet) as step:
                n, empreinte = write_landing(batch, obj, rows())
                step.nb_lignes = n
        except Exception:
            meta.record_extraction(batch.batch_id, obj, batch.extracted_at, 0, "ECHEC")
            raise
        meta.record_extraction(batch.batch_id, obj, batch.extracted_at, n, "SUCCES")
    update_manifest(batch, obj, n, empreinte, emplacement)
    logger.info("[EXTRACT] %-14s %-16s %7d lignes", obj.source, obj.objet, n)
    return n
