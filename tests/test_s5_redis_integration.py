"""
Test d'intégration — Source 5 sur un VRAI serveur Redis (conteneur edusmart_redis).
Désactivé par défaut. Pour l'exécuter :
    PowerShell : $env:EDUSMART_INTEGRATION = "1"; python -m pytest tests/test_s5_redis_integration.py -v
ATTENTION : vide la base Redis d'EduSmart (FLUSHDB) puis recharge le snapshot.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("EDUSMART_INTEGRATION") != "1",
                                reason="test d'intégration : définir EDUSMART_INTEGRATION=1")


@pytest.fixture(scope="module")
def loaded():
    from common.referential import main as build_ref
    from sources.s5_redis import generate_data, insert_data
    assert build_ref() == 0
    assert generate_data.main() == 0
    assert insert_data.main() == 0


@pytest.fixture
def client(loaded):
    import redis
    from common.config import get_settings
    c = redis.Redis(**get_settings().redis.connect_kwargs())
    yield c
    c.close()


def test_porte_g1(loaded):
    from sources.s5_redis import verify_source
    assert verify_source.main() == 0


def test_ttl_reels(client):
    """Sessions : TTL <= 24 h ; sessions E01 : aucun TTL (-1), elles n'expireront jamais."""
    ttls = [client.ttl(k) for k in client.scan_iter("session:*")]
    assert all(t == -1 or 0 < t <= 86400 for t in ttls)
    assert ttls.count(-1) > 0


def test_classement_trie_automatiquement(client):
    """PDF : « les étudiants sont triés automatiquement » (SORTED SET)."""
    top = client.zrevrange("leaderboard:python", 0, 2, withscores=True)
    assert len(top) == 3 and top[0][1] >= top[1][1] >= top[2][1]


def test_rechargement_idempotent(loaded):
    from sources.s5_redis import insert_data, verify_source
    assert insert_data.main() == 0
    assert verify_source.main() == 0
