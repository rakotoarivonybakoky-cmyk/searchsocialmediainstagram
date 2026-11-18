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
    source: str = "search_engine",
    location: Optional[str] = None,
    country_code: Optional[str] = None,
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    display_name: Optional[str] = None,
    bio: Optional[str] = None
) -> float:
    """
    Calcule un pourcentage de similarité multi-rubriques (0.0% à 100.0%)
    prenant en compte l'ensemble des informations de l'entreprise dans MongoDB :
      1. Nom de l'entreprise (companyName / tradeName vs username / display_name) : 40%
      2. Site web et domaines (url / domains vs Instagram / bio)                   : 30%
      3. Localisation géographique (location / countryCode vs bio / profil)        : 15%
      4. Secteur d'activité et description (description / keywords vs bio)         : 15%
    Lorsque toutes les rubriques concordent parfaitement, le score atteint 100.0%.
    """
    raw_c = normalize_text(company_name)
    raw_u = normalize_text(username)

    if not raw_c or not raw_u:
        return 0.0

    bio_lower = (bio or "").lower()
    display_lower = (display_name or "").lower()
    combined_bio = f"{bio_lower} {display_lower}"

    # =========================================================================
    # 1. RUBRIQUE NOM D'ENTREPRISE (40 POINTS MAX)
    # =========================================================================
    keywords_c = extract_company_keywords(company_name)
    clean_c = "".join(keywords_c)
    clean_u = re.sub(r"[._0-9]", "", raw_u)

    if raw_c == raw_u:
        name_ratio = 1.0
    elif clean_c and clean_u and clean_c == clean_u:
        name_ratio = 0.95
    else:
        ratio_raw = SequenceMatcher(None, raw_c, raw_u).ratio()
        ratio_clean = SequenceMatcher(None, clean_c, clean_u).ratio() if clean_c and clean_u else 0.0
        base_ratio = max(ratio_raw, ratio_clean)
        len_factor = min(len(raw_c), len(raw_u)) / max(len(raw_c), len(raw_u))
        name_ratio = base_ratio * 0.70 + len_factor * 0.30

    # Prise en compte du nom affiché (display_name) s'il valide l'entreprise
    if display_name:
        dn_norm = normalize_text(display_name)
        if raw_c in dn_norm or (clean_c and clean_c in dn_norm):
            name_ratio = min(1.0, name_ratio + 0.08)

    name_score = name_ratio * 40.0

    # =========================================================================
    # 2. RUBRIQUE SITE WEB ET DOMAINE (30 POINTS MAX)
    # =========================================================================
    if source == "official_website":
        # Le lien a été extrait directement du site officiel de l'entreprise
        domain_score = 30.0
    elif domain:
        clean_dom = re.sub(r"^https?://", "", domain.lower()).split("/")[0].replace("www.", "")
        dom_slug = normalize_text(clean_dom.split(".")[0])

        if clean_dom and clean_dom in bio_lower:
            # Le nom de domaine exact apparaît dans la bio Instagram
            domain_score = 30.0
        elif dom_slug and dom_slug in raw_u:
            # Le slug du domaine apparaît dans le pseudo Instagram
            dom_ratio = SequenceMatcher(None, dom_slug, raw_u).ratio()
            domain_score = max(20.0, (dom_ratio * 0.8 + 0.2) * 30.0)
        elif dom_slug and dom_slug in bio_lower:
            domain_score = 25.0
        else:
            domain_score = 15.0 * name_ratio
    else:
        # Aucun site web renseigné dans MongoDB : score pondéré selon le nom
        domain_score = 30.0 * name_ratio

    # =========================================================================
    # 3. RUBRIQUE GÉOGRAPHIE ET LOCALISATION (15 POINTS MAX)
    # =========================================================================
    country_names_map = {
        "fr": ["france", "fr"],
        "be": ["belgique", "belgium"],
        "ch": ["suisse", "switzerland"],
        "ca": ["canada", "quebec"],
        "mg": ["madagascar", "mada"],
        "us": ["usa", "united states", "etats-unis"],
        "uk": ["uk", "united kingdom", "royaume-uni"],
        "de": ["germany", "deutschland", "allemagne"],
        "es": ["espana", "spain", "espagne"],
        "it": ["italia", "italy", "italie"]
    }

    geo_tokens: Set[str] = set()
    if country_code:
        cc_lower = country_code.lower().strip()
        geo_tokens.add(cc_lower)
        for alias in country_names_map.get(cc_lower, []):
            geo_tokens.add(alias)

    if location:
        cleaned_loc = unicodedata.normalize("NFKD", location).encode("ASCII", "ignore").decode("utf-8").lower()
        for token in re.findall(r"[a-z]{3,}", cleaned_loc):
            geo_tokens.add(token)

    if geo_tokens and combined_bio:
        if any(re.search(rf"\b{re.escape(token)}\b", combined_bio) for token in geo_tokens):
            geo_score = 15.0
        else:
            geo_score = 10.0 * name_ratio
    else:
        geo_score = 15.0 * name_ratio

    # =========================================================================
    # 4. RUBRIQUE SECTEUR D'ACTIVITÉ ET DESCRIPTION (15 POINTS MAX)
    # =========================================================================
    sector_tokens: Set[str] = set()
    if keywords:
        for kw in keywords:
            if isinstance(kw, str) and len(kw) > 2:
                sector_tokens.add(kw.lower().strip())

    if description:
        cleaned_desc = unicodedata.normalize("NFKD", description).encode("ASCII", "ignore").decode("utf-8").lower()
        stopwords = {"pour", "dans", "avec", "cette", "notre", "votre", "nous", "vous", "societe", "entreprise"}
        desc_words = [w for w in re.findall(r"[a-z]{4,}", cleaned_desc) if w not in stopwords]
        sector_tokens.update(desc_words[:8])

    has_sector_match = False
    if sector_tokens and combined_bio:
        has_sector_match = any(re.search(rf"\b{re.escape(t)}\b", combined_bio) for t in sector_tokens)

    # Détection des indicateurs professionnels vs personnels
    has_business_ind = any(ind in combined_bio for ind in BUSINESS_INDICATORS)
    has_personal_ind = any(ind in combined_bio for ind in PERSONAL_INDICATORS)

    if has_sector_match:
        sector_score = 15.0
    elif has_business_ind:
        sector_score = 12.0
    elif has_personal_ind and not has_business_ind:
        # Pénalité forte si le compte est clairement personnel (mannequin, gamer, etc.)
        sector_score = -20.0
    else:
        sector_score = 15.0 * name_ratio

    # =========================================================================
    # SCORE FINAL PONDÉRÉ MULTI-CRITÈRES (100% QUAND TOUT CORRESPOND)
    # =========================================================================
    total_score = name_score + domain_score + geo_score + sector_score

    # Bonus de source officielle si applicable
    if source == "official_website" and name_ratio >= 0.85:
        total_score = max(total_score, 95.0 if name_ratio < 1.0 else 100.0)

    final_score = round(max(0.0, min(total_score, 100.0)), 1)
    return final_score


def calculate_confidence(
    clean_url: str,
    username: str,
    company_name: str,
    domain: Optional[str] = None,
    source: str = "search_engine",
    location: Optional[str] = None,
    country_code: Optional[str] = None,
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    display_name: Optional[str] = None,
    bio: Optional[str] = None
) -> tuple[str, str, float]:
    """
    Détermine le niveau de confiance (HIGH, MEDIUM, LOW), la raison et la similarité multi-rubriques.
    """
    similarity = calculate_similarity(
        company_name=company_name,
        username=username,
        domain=domain,
        source=source,
        location=location,
        country_code=country_code,
        description=description,
        keywords=keywords,
        display_name=display_name,
        bio=bio
    )

    if source == "official_website":
        return "HIGH", f"Lien extrait du site web officiel (similarité: {similarity}%).", similarity

    if similarity >= 90.0:
        return "HIGH", f"Forte concordance multi-rubriques ({similarity}%) avec le compte '{username}'.", similarity
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
    source: str = "search_engine",
    location: Optional[str] = None,
    country_code: Optional[str] = None,
    description: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    display_name: Optional[str] = None,
    bio: Optional[str] = None
) -> ValidationResult:
    """
    Fonction de validation d'un candidat Instagram avec calcul du pourcentage de similarité multi-rubriques.
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
        source=source,
        location=location,
        country_code=country_code,
        description=description,
        keywords=keywords,
        display_name=display_name,
        bio=bio
    )

    return ValidationResult(
        is_valid=True,
        clean_url=clean_url,
        username=username,
        confidence=confidence,
        reason=reason,
        similarity=similarity
    )
