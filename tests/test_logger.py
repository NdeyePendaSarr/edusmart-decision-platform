"""Tests unitaires — common/logger.py"""
import pytest

from common.logger import get_logger, log_step


def test_get_logger_idempotent():
    first = get_logger("test_idempotence")
    nb_handlers = len(first.handlers)
    second = get_logger("test_idempotence")
    assert first is second
    assert len(second.handlers) == nb_handlers
    assert first.name == "edusmart.test_idempotence"


def test_log_step_relance_les_exceptions():
    logger = get_logger("test_log_step")
    with pytest.raises(ValueError):
        with log_step(logger, "étape volontairement en échec"):
            raise ValueError("erreur de test")


def test_log_step_succes():
    logger = get_logger("test_log_step")
    with log_step(logger, "étape réussie"):
        resultat = 1 + 1
    assert resultat == 2
