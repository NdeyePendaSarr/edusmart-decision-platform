"""
common/logger.py — Journalisation commune (Lot L0)
==================================================

Rôle
    Fournir à tous les scripts (générateurs, ETL, tests) un logger homogène :
    - sortie console (suivi en direct) ;
    - fichier logs/edusmart.log avec rotation (5 fichiers de 5 Mo) ;
    - un gestionnaire de contexte `log_step` qui chronomètre une étape et
      trace son succès ou son échec. Il servira de base à la table
      meta.etl_execution_log (Phase 6 : source, date, durée, statut, erreurs).

Choix techniques
    - Messages en ASCII pour les symboles (pas d'emoji) : la console Windows
      (cp1252) provoquerait des « Logging error ».
    - La sortie console est reconfigurée en UTF-8 quand c'est possible, pour
      les accents français.
    - `propagate = False` : évite les doublons si une bibliothèque configure
      le logger racine.
    - Idempotent : appeler get_logger deux fois ne duplique pas les handlers.

Utilisation
    from common.logger import get_logger, log_step
    logger = get_logger("referential")
    with log_step(logger, "Génération du référentiel"):
        ...
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from typing import Iterator

from common.config import get_settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_LOG_FILE = "edusmart.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def _configure_console_encoding() -> None:
    """Force l'UTF-8 sur la console si possible (utile sous Windows)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass  # flux non reconfigurable (ex. capture pytest) : on garde l'existant


def get_logger(name: str, log_file: str = DEFAULT_LOG_FILE) -> logging.Logger:
    """
    Retourne un logger nommé « edusmart.<name> ».

    Paramètres
        name     : nom du module ou de l'étape (ex. "referential", "extract_mysql").
        log_file : nom du fichier dans logs/ (par défaut edusmart.log).
    """
    full_name = name if name.startswith("edusmart.") else f"edusmart.{name}"
    logger = logging.getLogger(full_name)
    if logger.handlers:  # déjà configuré : idempotence
        return logger

    settings = get_settings()
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    _configure_console_encoding()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        settings.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.paths.logs_dir / log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:  # disque en lecture seule, droits insuffisants...
        logger.warning("Journal fichier indisponible (%s) : console uniquement.", exc)

    return logger


@contextmanager
def log_step(logger: logging.Logger, step: str) -> Iterator[None]:
    """
    Chronomètre une étape et journalise début, fin et durée.
    En cas d'exception, la trace complète est journalisée puis l'exception
    est RELANCÉE (on ne masque jamais une erreur).
    """
    start = time.perf_counter()
    logger.info("[DEBUT] %s", step)
    try:
        yield
    except Exception:
        logger.exception("[ECHEC] %s (%.2f s)", step, time.perf_counter() - start)
        raise
    logger.info("[FIN] %s (%.2f s)", step, time.perf_counter() - start)
