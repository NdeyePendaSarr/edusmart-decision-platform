"""
common/senegalese_data.py — Données de référence sénégalaises (Lot L1)
======================================================================

Rôle
    Compléter Faker, qui ne propose pas de locale sénégalaise, avec :
    - des prénoms masculins et féminins et des noms de famille courants au
      Sénégal (aires wolof, pulaar, sérère, diola, mandingue/soninké, lébou) ;
    - les 14 régions administratives et une sélection de villes par région ;
    - le format téléphonique mobile +221 7X XXX XX XX.

Conventions (voir README, registre des conventions)
    - Les poids régionaux sont INDICATIFS : ils ne reproduisent pas un
      recensement officiel. Dakar est surreprésentée, ce qui est réaliste
      pour une plateforme de formation en ligne.
    - Dans chaque région, le chef-lieu (première ville de la liste) est
      trois fois plus probable que les autres villes.
    - Les regroupements de noms servent uniquement à documenter la diversité
      des listes. Ils ne sont PAS stockés dans les données générées et ne
      sont jamais exploités dans l'analyse.
    - Ces listes produisent des personnes FICTIVES : toute ressemblance avec
      une personne réelle est fortuite.

Les fonctions reçoivent un random.Random (voir common/seed.py) : elles sont
donc reproductibles.
"""

from __future__ import annotations

import random
import re
import unicodedata

PAYS = "Sénégal"
INDICATIF = "+221"

# -----------------------------------------------------------------------------
# Prénoms (simples et composés, usages musulmans et chrétiens)
# -----------------------------------------------------------------------------
PRENOMS_MASCULINS: tuple[str, ...] = (
    "Mamadou", "Moussa", "Ousmane", "Abdoulaye", "Cheikh", "Ibrahima", "Modou",
    "Babacar", "Pape", "Alioune", "Mouhamed", "Amadou", "Serigne", "Lamine",
    "Assane", "El Hadji", "Omar", "Souleymane", "Malick", "Aliou", "Saliou",
    "Birame", "Djibril", "Idrissa", "Khadim", "Fallou", "Matar", "Demba",
    "Samba", "Thierno", "Boubacar", "Youssou", "Waly", "Abdou", "Seydou",
    "Mansour", "Ismaïla", "Bassirou", "Pape Moussa", "Mame Cheikh",
    "Jean-Baptiste", "Joseph", "Pascal", "Augustin", "Louis",
)

PRENOMS_FEMININS: tuple[str, ...] = (
    "Aminata", "Fatou", "Awa", "Khady", "Mariama", "Ndeye", "Aïssatou", "Coumba",
    "Adama", "Astou", "Fatoumata", "Bineta", "Sokhna", "Rokhaya", "Dieynaba",
    "Maïmouna", "Seynabou", "Oumou", "Khadija", "Nafissatou", "Penda", "Marème",
    "Yacine", "Ramatoulaye", "Anta", "Ngoné", "Codou", "Diarra", "Aby", "Soda",
    "Arame", "Mame Diarra", "Ndeye Fatou", "Sokhna Aïda",
    "Marie", "Thérèse", "Germaine", "Agnès", "Madeleine",
)

# -----------------------------------------------------------------------------
# Noms de famille, regroupés pour documenter la diversité des listes.
# Une seule graphie par nom (Ba et non Bâ, Gueye et non Guèye) : les listes
# canoniques restent propres, et les variantes orthographiques éventuelles
# resteront détectables comme anomalies.
# -----------------------------------------------------------------------------
NOMS_PAR_AIRE: dict[str, tuple[str, ...]] = {
    "wolof": ("Diop", "Ndiaye", "Fall", "Gueye", "Seck", "Mbaye", "Thiam", "Niang",
              "Lo", "Diagne", "Dieng", "Mbengue", "Kébé", "Wade", "Samb"),
    "pulaar": ("Ba", "Diallo", "Sow", "Barry", "Kane", "Ly", "Sy", "Wane", "Dia",
               "Tall", "Baldé"),
    "sérère": ("Faye", "Diouf", "Ndour", "Sène", "Thiaw", "Dione", "Sarr", "Ngom",
               "Tine", "Senghor"),
    "diola": ("Diatta", "Badji", "Sagna", "Manga", "Coly", "Sambou", "Diédhiou",
              "Goudiaby"),
    "mandingue_soninke": ("Cissé", "Touré", "Traoré", "Camara", "Keïta", "Sylla",
                          "Konaté", "Dramé", "Sakho", "Doucouré"),
    "lebou": ("Ndoye", "Paye", "Mbengue"),  # Mbengue est aussi wolof : dédoublonné ci-dessous
}
NOMS_DE_FAMILLE: tuple[str, ...] = tuple(
    dict.fromkeys(nom for noms in NOMS_PAR_AIRE.values() for nom in noms)  # sans doublon, ordre stable
)

# -----------------------------------------------------------------------------
# 14 régions administratives, poids indicatifs (somme = 100), villes
# (le chef-lieu en premier)
# -----------------------------------------------------------------------------
REGIONS: dict[str, dict] = {
    "Dakar":       {"poids": 30, "villes": ("Dakar", "Pikine", "Guédiawaye", "Rufisque", "Keur Massar")},
    "Thiès":       {"poids": 13, "villes": ("Thiès", "Mbour", "Tivaouane", "Joal-Fadiouth")},
    "Diourbel":    {"poids": 9,  "villes": ("Diourbel", "Touba", "Mbacké", "Bambey")},
    "Saint-Louis": {"poids": 7,  "villes": ("Saint-Louis", "Richard-Toll", "Dagana", "Podor")},
    "Kaolack":     {"poids": 7,  "villes": ("Kaolack", "Nioro du Rip", "Guinguinéo")},
    "Louga":       {"poids": 5,  "villes": ("Louga", "Linguère", "Kébémer")},
    "Fatick":      {"poids": 5,  "villes": ("Fatick", "Foundiougne", "Gossas")},
    "Ziguinchor":  {"poids": 5,  "villes": ("Ziguinchor", "Bignona", "Oussouye")},
    "Kolda":       {"poids": 4,  "villes": ("Kolda", "Vélingara", "Médina Yoro Foulah")},
    "Tambacounda": {"poids": 4,  "villes": ("Tambacounda", "Bakel", "Goudiry", "Koumpentoum")},
    "Matam":       {"poids": 3,  "villes": ("Matam", "Ourossogui", "Kanel")},
    "Kaffrine":    {"poids": 3,  "villes": ("Kaffrine", "Koungheul", "Birkelane", "Malem Hodar")},
    "Sédhiou":     {"poids": 3,  "villes": ("Sédhiou", "Bounkiling", "Goudomp")},
    "Kédougou":    {"poids": 2,  "villes": ("Kédougou", "Saraya", "Salémata")},
}

REGION_NAMES: tuple[str, ...] = tuple(REGIONS)
_REGION_WEIGHTS: tuple[int, ...] = tuple(r["poids"] for r in REGIONS.values())

# Correspondance ville -> région (utile aussi en transformation, Lot L5)
CITY_TO_REGION: dict[str, str] = {
    ville: region for region, info in REGIONS.items() for ville in info["villes"]
}

# -----------------------------------------------------------------------------
# Téléphonie mobile : +221 7X XXX XX XX
# -----------------------------------------------------------------------------
MOBILE_PREFIXES: tuple[str, ...] = ("70", "75", "76", "77", "78")
_MOBILE_PREFIX_WEIGHTS: tuple[int, ...] = (15, 5, 25, 35, 20)  # indicatif

# « international » est le format canonique ; les autres serviront aux
# anomalies « formats de téléphone différents » (Sources 1 et 3)
PHONE_STYLES: tuple[str, ...] = (
    "international",          # +221 77 123 45 67
    "international_compact",  # +221771234567
    "local",                  # 77 123 45 67
    "local_compact",          # 771234567
    "double_zero",            # 00221771234567
)
PHONE_CANONICAL_RE = re.compile(r"^\+221 7[05678] \d{3} \d{2} \d{2}$")

# Domaines pour les adresses e-mail (utilisés à partir de L2)
EMAIL_DOMAINS: tuple[str, ...] = ("gmail.com", "yahoo.fr", "hotmail.com", "outlook.com")


# -----------------------------------------------------------------------------
# Fonctions de tirage
# -----------------------------------------------------------------------------
def random_sexe(rng: random.Random) -> str:
    """Sexe canonique 'M' ou 'F' (les variantes « Homme », « 1 »... sont des anomalies L2)."""
    return rng.choice(("M", "F"))


def random_first_name(rng: random.Random, sexe: str) -> str:
    if sexe == "M":
        return rng.choice(PRENOMS_MASCULINS)
    if sexe == "F":
        return rng.choice(PRENOMS_FEMININS)
    raise ValueError(f"Sexe canonique attendu 'M' ou 'F', reçu {sexe!r}.")


def random_last_name(rng: random.Random) -> str:
    return rng.choice(NOMS_DE_FAMILLE)


def random_region_and_city(rng: random.Random) -> tuple[str, str]:
    """Tire une région (pondérée) puis une ville de cette région (chef-lieu favorisé)."""
    region = rng.choices(REGION_NAMES, weights=_REGION_WEIGHTS, k=1)[0]
    villes = REGIONS[region]["villes"]
    city_weights = [3] + [1] * (len(villes) - 1)
    ville = rng.choices(villes, weights=city_weights, k=1)[0]
    return region, ville


def format_phone(prefix: str, number7: str, style: str = "international") -> str:
    """Met en forme un numéro mobile (prefix = '77', number7 = 7 chiffres)."""
    if prefix not in MOBILE_PREFIXES or not re.fullmatch(r"\d{7}", number7):
        raise ValueError(f"Numéro invalide : prefix={prefix!r}, number7={number7!r}.")
    a, b, c = number7[:3], number7[3:5], number7[5:]
    formats = {
        "international": f"{INDICATIF} {prefix} {a} {b} {c}",
        "international_compact": f"{INDICATIF}{prefix}{number7}",
        "local": f"{prefix} {a} {b} {c}",
        "local_compact": f"{prefix}{number7}",
        "double_zero": f"00221{prefix}{number7}",
    }
    if style not in formats:
        raise ValueError(f"Style inconnu : {style!r}. Styles : {PHONE_STYLES}.")
    return formats[style]


def random_phone(rng: random.Random, style: str = "international") -> str:
    prefix = rng.choices(MOBILE_PREFIXES, weights=_MOBILE_PREFIX_WEIGHTS, k=1)[0]
    number7 = f"{rng.randint(0, 9_999_999):07d}"
    return format_phone(prefix, number7, style)


def _normalize(text: str) -> str:
    """Minuscules sans accents ni espaces superflus : 'DAKAR ' -> 'dakar'."""
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_NORMALIZED_CITY_TO_REGION = {_normalize(v): r for v, r in CITY_TO_REGION.items()}


def region_of_city(city: str | None) -> str | None:
    """
    Région d'une ville, insensible à la casse et aux accents
    ('DAKAR' -> 'Dakar', 'thies' -> 'Thiès'). Renvoie None si inconnue
    (ex. faute de frappe 'dakarr' : ce cas sera traité en transformation).
    """
    if not city:
        return None
    return _NORMALIZED_CITY_TO_REGION.get(_normalize(city))


# -----------------------------------------------------------------------------
# Auto-contrôle des listes
# -----------------------------------------------------------------------------
def validate_reference_data() -> list[str]:
    """Retourne la liste des problèmes détectés (vide si tout est cohérent)."""
    problems: list[str] = []
    if len(REGIONS) != 14:
        problems.append(f"14 régions attendues, {len(REGIONS)} trouvées")
    if sum(_REGION_WEIGHTS) != 100:
        problems.append(f"la somme des poids régionaux vaut {sum(_REGION_WEIGHTS)} (100 attendu)")
    all_cities = [v for info in REGIONS.values() for v in info["villes"]]
    if len(all_cities) != len(set(all_cities)):
        problems.append("une ville apparaît dans plusieurs régions")
    for region, info in REGIONS.items():
        if not info["villes"]:
            problems.append(f"la région {region} n'a aucune ville")
    for label, names in (("prénoms masculins", PRENOMS_MASCULINS),
                         ("prénoms féminins", PRENOMS_FEMININS),
                         ("noms", NOMS_DE_FAMILLE)):
        if len(names) != len(set(names)):
            problems.append(f"doublons dans les {label}")
    return problems
