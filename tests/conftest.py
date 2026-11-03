"""
Garde-fou de la suite de tests : aucun test unitaire n'écrit dans les fichiers suivis par Git.

Un fichier réécrit à l'identique n'apparaît pas dans `git status` : on compare donc la date de
modification et la taille, relevées au début et à la fin de la session.

Désactivé en mode intégration (EDUSMART_INTEGRATION=1) : ces tests régénèrent volontairement
le référentiel et les correspondances (mappings/).
"""
import os
import subprocess
from pathlib import Path

import pytest

from common import referential as ref
from common.config import get_settings

RACINE = Path(__file__).resolve().parent.parent


def fichiers_suivis() -> list[str]:
    """Chemins suivis par Git, relatifs à la racine du dépôt."""
    sortie = subprocess.run(["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, check=True)
    return [chemin for chemin in sortie.stdout.decode("utf-8").split("\0") if chemin]


def empreintes(chemins: list[str]) -> dict[str, tuple[int, int] | None]:
    """{chemin: (date de modification en ns, taille)} ; None si le fichier n'existe pas."""
    resultat: dict[str, tuple[int, int] | None] = {}
    for chemin in chemins:
        try:
            infos = (RACINE / chemin).stat()
            resultat[chemin] = (infos.st_mtime_ns, infos.st_size)
        except FileNotFoundError:
            resultat[chemin] = None
    return resultat


@pytest.fixture(scope="session", autouse=True)
def fichiers_suivis_intacts():
    """Fait échouer la session si un test a écrit dans un fichier suivi par Git."""
    if os.getenv("EDUSMART_INTEGRATION") == "1":
        yield
        return
    chemins = fichiers_suivis()
    avant = empreintes(chemins)
    yield
    apres = empreintes(chemins)
    modifies = sorted(chemin for chemin in chemins if avant[chemin] != apres[chemin])
    assert not modifies, f"Des tests ont écrit dans des fichiers suivis par Git : {modifies}"


@pytest.fixture(scope="module")
def referentiel_temporaire(tmp_path_factory):
    """Référentiel écrit hors du dépôt : load_referential() le lit à la place de data/referential/."""
    dossier = tmp_path_factory.mktemp("referential")
    ref.write_referential(ref.build_referential(get_settings().generation), dossier)
    chemin = dossier / ref.REFERENTIAL_FILENAME
    charger = ref.load_referential
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ref, "load_referential", lambda path=None: charger(path or chemin))
        yield chemin
