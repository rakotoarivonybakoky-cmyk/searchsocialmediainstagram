"""
Module de validation, fiabilisation et calcul de similarité des profils Instagram.
Vérifie la syntaxe des URLs, filtre les pages système/posts/stories,
calcule le score de confiance et le pourcentage de similarité avec l'entreprise.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Optional, List, Set, Dict, Any

# Mots réservés et chemins système d'Instagram (ne sont pas des profils d'entreprises)
RESERVED_INSTAGRAM_PATHS: Set[str] = {
    "p", "reel", "reels", "tv", "stories", "explore", "accounts",
    "about", "legal", "direct", "developer", "help", "directory",
    "privacy", "terms", "channel", "graphql", "ar", "business",
    "creators", "session", "challenge", "login", "emails", "support",
    "static", "web", "api", "download", "oauth", "press"
}

# Formes juridiques et termes d'entreprises courants à nettoyer pour la comparaison
LEGAL_EXTENSIONS: Set[str] = {
    "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "sarl", "sas", "sasu", "sa", "gmbh", "ag", "llc", "co", "company",
    "cie", "group", "groupe", "holding", "holdings", "srl", "sl", "bv",
    "nv", "sp", "spa", "z", "oo", "pte", "plc"
}

# Indicateurs caractéristiques d'un profil personnel (personne physique)
PERSONAL_INDICATORS: Set[str] = {
    "photographer", "photographe", "model", "modele", "influencer", "influenceur",
    "blogger", "vlogger", "artist", "artiste", "musician", "musicien",
    "singer", "chanteur", "chanteuse", "dancer", "danseur", "danseuse",
    "actor", "acteur", "actrice", "i am", "je suis", "my life", "ma vie",
    "personal", "personnel", "lifestyle", "my journey", "mon parcours",
    "etudiant", "student", "passionnee", "passionné", "freelancer",
    "content creator", "createur de contenu", "maman", "papa", "family",
    "famille", "amoureux", "amoureuse", "fan de", "love",
}

# Indicateurs caractéristiques d'un compte professionnel / entreprise
BUSINESS_INDICATORS: Set[str] = {
    "official", "officiel", "contact", "services", "solutions", "entreprise",
    "company", "shop", "store", "boutique", "www.", ".com", ".fr", ".net",
    "email", "tel:", "tél:", "horaires", "hours", "menu", "devis",
    "livraison", "delivery", "wholesale", "retail", "commande", "order",
    "pro", "professionnel", "professional", "commerce", "commercial",
    "agence", "agency", "cabinet", "bureau", "office", "siege",
    "siège", "marque", "brand", "founded", "fondée", "fondé", "since",
    "depuis", "@", "site:", "rdv", "rendez-vous", "appointment",
}


@dataclass
class ValidationResult:
    """Résultat de l'analyse d'un lien Instagram."""
    is_valid: bool
    clean_url: Optional[str]
    username: Optional[str]
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    reason: str
    similarity: float = 0.0  # Pourcentage de similarité (0.0% à 100.0%)


def normalize_text(text: str) -> str:
    """Nettoie une chaîne de texte (suppression des accents, minuscules, alphanumérique)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ASCII", "ignore").decode("utf-8")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def extract_company_keywords(company_name: str) -> List[str]:
    """Découpe le nom d'entreprise en mots-clés significatifs sans la forme juridique."""
    if not company_name:
        return []
    cleaned = unicodedata.normalize("NFKD", company_name).encode("ASCII", "ignore").decode("utf-8").lower()
    tokens = re.findall(r"[a-z0-9]+", cleaned)
    filtered = [t for t in tokens if t not in LEGAL_EXTENSIONS and len(t) > 1]
    return filtered


def clean_instagram_url(url: str) -> Optional[str]:
    """
    Normalise une URL Instagram en format canonique : https://www.instagram.com/<username>/
    Retourne None si l'URL ne pointe pas vers un profil utilisateur valide
    (ex: https://instagram.com/ sans nom d'utilisateur, /p/, /reels/, etc.).
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    domain = parsed.netloc.lower()
    if "instagram.com" not in domain:
        return None

    path = parsed.path.strip("/")
    parts = path.split("/")
    # Si le chemin est vide (ex: https://instagram.com/) -> profil INVALIDE
    if not parts or not parts[0]:
        return None

    username = parts[0].strip()

    if username.lower() in RESERVED_INSTAGRAM_PATHS:
        return None

    if not re.match(r"^[A-Za-z0-9._]{1,30}$", username):
        return None

    if username.startswith(".") or username.endswith("."):
        return None

    return f"https://www.instagram.com/{username.lower()}/"


def extract_username_from_url(clean_url: str) -> Optional[str]:
    """Extrait le nom d'utilisateur d'une URL canonique."""
    if not clean_url:
        return None
    match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)", clean_url)
    return match.group(1).lower() if match else None

def calculate_similarity(
    company_name: str,
    username: str,
    domain: Optional[str] = None,
    source: str = "search_engine"
) -> float:
    """
    Calcule un pourcentage de similarité réaliste et différencié (0.0% à 100.0%)
    entre le nom d'entreprise et le compte Instagram.
    Chaque variation (ex: ajout de chiffres, de pays, de mots) produit un score distinct.
    """
    raw_c = normalize_text(company_name)
    raw_u = normalize_text(username)

    if not raw_c or not raw_u:
        return 0.0

    # 1. Correspondance exacte parfaite
    if raw_c == raw_u:
        return 100.0

    # 2. Nettoyage des termes légaux / suffixes d'entreprise
    keywords_c = extract_company_keywords(company_name)
    clean_c = "".join(keywords_c)
    clean_u = re.sub(r"[._0-9]", "", raw_u)

    if clean_c and clean_u and clean_c == clean_u:
        # Correspondance exacte après retrait des formes juridiques et séparateurs
        score = 95.0
    else:
        # 3. Ratio de Levenshtein (caractère par caractère)
        ratio_raw = SequenceMatcher(None, raw_c, raw_u).ratio()
        ratio_clean = SequenceMatcher(None, clean_c, clean_u).ratio() if clean_c and clean_u else 0.0
        base_ratio = max(ratio_raw, ratio_clean)

        # 4. Pénalité de longueur proportionnelle si le handle a des caractères en trop ou en moins
        len_factor = min(len(raw_c), len(raw_u)) / max(len(raw_c), len(raw_u))

        # 5. Score combiné pondéré
        score = (base_ratio * 0.70 + len_factor * 0.30) * 100.0

        # Prise en compte du nom de domaine si pertinent
        if domain:
            clean_dom = re.sub(r"^https?://", "", domain.lower()).split("/")[0].replace("www.", "")
            dom_slug = normalize_text(clean_dom.split(".")[0])
            if dom_slug and dom_slug in raw_u:
                dom_ratio = SequenceMatcher(None, dom_slug, raw_u).ratio()
                score = max(score, (dom_ratio * 0.75 + 0.20) * 100.0)

    # Si le lien est extrait du site web officiel, léger bonus de légitimité sans masquer les différences
    if source == "official_website":
        score = min(100.0, score + 8.0)

    return round(max(0.0, min(score, 100.0)), 1)


def calculate_confidence(
    clean_url: str,
    username: str,
    company_name: str,
    domain: Optional[str] = None,
    source: str = "search_engine"
) -> tuple[str, str, float]:
    """
    Détermine le niveau de confiance (HIGH, MEDIUM, LOW), la raison et la similarité.
    """
    similarity = calculate_similarity(company_name, username, domain, source)

    if source == "official_website":
        return "HIGH", f"Lien extrait du site web officiel (similarité: {similarity}%).", similarity

    if similarity >= 90.0:
        return "HIGH", f"Forte concordance ({similarity}%) entre l'entreprise et le compte '{username}'.", similarity
    elif similarity >= 60.0:
        return "MEDIUM", f"Concordance modérée ({similarity}%) avec le compte '{username}'.", similarity
    else:
        return "LOW", f"Faible ressemblance ({similarity}%) entre l'entreprise et le compte '{username}'.", similarity


def analyze_bio_for_business(
    display_name: str,
    bio: str,
    company_name: str
) -> tuple:
    """
    Analyse la biographie et le nom affiché d'un profil Instagram pour déterminer
    s'il s'agit d'un compte d'entreprise ou d'un profil personnel.

    Retourne un tuple (score_adjustment: float, raison: str) :
      - score_adjustment > 0 : bonus (compte business confirmé)
      - score_adjustment < 0 : pénalité (profil personnel suspect)
      - score_adjustment == 0 : neutre (inaccessible ou indéterminé)

    Si Instagram est inaccessible (bio et display_name vides), retourne (0.0, neutre)
    pour ne pas pénaliser injustement le score textuel existant.
    """
    if not bio and not display_name:
        return 0.0, "Profil inaccessible ou bio vide — score textuel conservé."

    bio_raw = (bio or "").lower()
    display_raw = (display_name or "").lower()
    combined_raw = bio_raw + " " + display_raw

    bio_normalized = normalize_text(bio or "")
    display_normalized = normalize_text(display_name or "")

    # Détection des indicateurs personnels et business
    personal_hits = [ind for ind in PERSONAL_INDICATORS if ind in combined_raw]
    business_hits = [ind for ind in BUSINESS_INDICATORS if ind in combined_raw]

    # Vérification si le nom affiché ou la bio contient les mots-clés de l'entreprise
    company_keywords = extract_company_keywords(company_name)
    name_match = any(kw in display_normalized for kw in company_keywords if len(kw) > 2)
    bio_match = any(kw in bio_normalized for kw in company_keywords if len(kw) > 2)

    if personal_hits and not business_hits:
        # Profil clairement personnel, aucun indicateur business
        return -35.0, (
            f"Profil personnel suspect — indicateurs détectés : "
            f"{', '.join(personal_hits[:3])}. Rejeté."
        )
    elif business_hits:
        # Compte avec indicateurs business
        bonus = min(12.0, len(business_hits) * 3.0)
        hits_str = ", ".join(business_hits[:3])
        raison = f"Compte business confirmé (indicateurs : {hits_str})."
        if name_match or bio_match:
            bonus += 5.0
            raison += " Nom/bio cohérent avec l'entreprise."
        return bonus, raison
    elif name_match or bio_match:
        # Pas d'indicateurs clairs mais le nom ou la bio mentionne l'entreprise
        return 5.0, "Nom affiché ou bio contient des mots-clés de l'entreprise."
    elif personal_hits:
        # Quelques indicateurs personnels mais aussi ambiguïté
        return -15.0, (
            f"Profil ambigu — indicateurs personnels : {', '.join(personal_hits[:2])}. "
            "Confiance réduite."
        )
    else:
        return 0.0, "Aucun indicateur business ou personnel détecté — score textuel conservé."


def validate_instagram_candidate(
    candidate_url: str,
    company_name: str,
    domain: Optional[str] = None,
    source: str = "search_engine"
) -> ValidationResult:
    """
    Fonction de validation d'un candidat Instagram avec calcul du pourcentage de similarité.
    """
    clean_url = clean_instagram_url(candidate_url)
    if not clean_url:
        return ValidationResult(
            is_valid=False,
            clean_url=None,
            username=None,
            confidence="LOW",
            reason="L'URL n'est pas un profil Instagram valide ou correspond à une page système.",
            similarity=0.0
        )

    username = extract_username_from_url(clean_url)
    confidence, reason, similarity = calculate_confidence(
        clean_url=clean_url,
        username=username,
        company_name=company_name,
        domain=domain,
        source=source
    )

    return ValidationResult(
        is_valid=True,
        clean_url=clean_url,
        username=username,
        confidence=confidence,
        reason=reason,
        similarity=similarity
    )
