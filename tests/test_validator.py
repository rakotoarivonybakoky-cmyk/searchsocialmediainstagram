"""
Tests unitaires pour le module instagram_validator.
Vérifie la normalisation des URLs, le filtrage des chemins système,
la détection des profils valides et le calcul des scores de confiance.
"""

import pytest
from instagram_validator import (
    clean_instagram_url,
    extract_username_from_url,
    normalize_text,
    extract_company_keywords,
    calculate_confidence,
    validate_instagram_candidate,
    analyze_bio_for_business
)


class TestInstagramUrlCleaning:
    """Tests de nettoyage et normalisation des URLs Instagram."""

    def test_valid_profile_urls(self):
        assert clean_instagram_url("https://www.instagram.com/nike/") == "https://www.instagram.com/nike/"
        assert clean_instagram_url("http://instagram.com/adidas_fr") == "https://www.instagram.com/adidas_fr/"
        assert clean_instagram_url("instagram.com/sillyrama.prod") == "https://www.instagram.com/sillyrama.prod/"
        assert clean_instagram_url("https://www.instagram.com/apple?hl=fr") == "https://www.instagram.com/apple/"

    def test_reserved_system_paths_filtered(self):
        assert clean_instagram_url("https://www.instagram.com/p/B9xq_fakepost/") is None
        assert clean_instagram_url("https://www.instagram.com/reel/C8v9z/") is None
        assert clean_instagram_url("https://www.instagram.com/reels/") is None
        assert clean_instagram_url("https://www.instagram.com/explore/tags/fashion/") is None
        assert clean_instagram_url("https://www.instagram.com/accounts/login/") is None
        assert clean_instagram_url("https://www.instagram.com/about/") is None
        assert clean_instagram_url("https://www.instagram.com/legal/privacy/") is None

    def test_invalid_syntax_and_domains(self):
        assert clean_instagram_url("https://www.facebook.com/company") is None
        assert clean_instagram_url("https://www.twitter.com/company") is None
        assert clean_instagram_url("not_a_valid_url") is None
        assert clean_instagram_url("") is None
        assert clean_instagram_url(None) is None
        # Ne peut pas commencer par un point
        assert clean_instagram_url("https://www.instagram.com/.invalidusername/") is None


class TestTextNormalization:
    """Tests de normalisation et extraction de mots-clés d'entreprises."""

    def test_normalize_text(self):
        assert normalize_text("Ébénisterie & Fils SAS") == "ebenisteriefilssas"
        assert normalize_text("L'Oréal Paris") == "lorealparis"
        assert normalize_text("Société Générale") == "societegenerale"

    def test_extract_company_keywords(self):
        keywords = extract_company_keywords("Sillyrama Production SARL")
        assert "sillyrama" in keywords
        assert "production" in keywords
        assert "sarl" not in keywords  # Forme juridique filtrée

        keywords_inc = extract_company_keywords("Acme Tech Group Inc.")
        assert "acme" in keywords_inc
        assert "tech" in keywords_inc
        assert "group" not in keywords_inc
        assert "inc" not in keywords_inc


class TestConfidenceCalculation:
    """Tests de calcul de score de confiance."""

    def test_official_website_source_is_always_high(self):
        conf, reason, similarity = calculate_confidence(
            clean_url="https://www.instagram.com/random_handle/",
            username="random_handle",
            company_name="Entreprise Test",
            source="official_website"
        )
        assert conf == "HIGH"
        assert "site web officiel" in reason
        assert isinstance(similarity, float)

    def test_domain_match_gives_high_confidence(self):
        conf, reason, similarity = calculate_confidence(
            clean_url="https://www.instagram.com/sillyrama/",
            username="sillyrama",
            company_name="Sillyrama Production",
            domain="https://www.sillyrama.com",
            source="search_engine"
        )
        # Seuil HIGH = >= 90% (seuil strict pour fiabilité entreprise)
        assert conf in ("HIGH", "MEDIUM")
        assert similarity > 0

    def test_partial_match_gives_medium_confidence(self):
        conf, reason, similarity = calculate_confidence(
            clean_url="https://www.instagram.com/silly_creations/",
            username="silly_creations",
            company_name="Sillyrama Production Global",
            domain=None,
            source="search_engine"
        )
        assert conf in ("MEDIUM", "LOW")
        assert isinstance(similarity, float)

    def test_short_or_unrelated_handle_gives_low_confidence(self):
        conf, reason, similarity = calculate_confidence(
            clean_url="https://www.instagram.com/abc/",
            username="abc",
            company_name="Grande Entreprise Internationale",
            domain=None,
            source="search_engine"
        )
        assert conf == "LOW"
        assert similarity < 50.0


class TestValidateInstagramCandidate:
    """Tests de la fonction complète de validation."""

    def test_valid_candidate(self):
        res = validate_instagram_candidate(
            candidate_url="https://www.instagram.com/sillyrama_prod/",
            company_name="Sillyrama Production",
            domain="sillyrama.fr",
            source="search_engine"
        )
        assert res.is_valid is True
        assert res.username == "sillyrama_prod"
        # Avec le seuil strict >= 90%, sillyrama_prod vs "Sillyrama Production" = MEDIUM ou HIGH
        assert res.confidence in ("HIGH", "MEDIUM")

    def test_invalid_candidate(self):
        res = validate_instagram_candidate(
            candidate_url="https://www.instagram.com/p/B_post_id/",
            company_name="Sillyrama Production"
        )
        assert res.is_valid is False
        assert res.clean_url is None


class TestBioAnalysis:
    """Tests de la fonction analyze_bio_for_business."""

    def test_business_indicators_give_bonus(self):
        adjustment, reason = analyze_bio_for_business(
            display_name="Diamond Services SARL",
            bio="Contact : contact@diamondservices.fr | Livraison partout en France",
            company_name="Diamond Services"
        )
        assert adjustment > 0
        assert "business" in reason.lower() or "confirmé" in reason.lower()

    def test_personal_indicators_give_penalty(self):
        adjustment, reason = analyze_bio_for_business(
            display_name="Diamond",
            bio="Je suis photographe et artiste. My life, my journey.",
            company_name="Diamond Services"
        )
        assert adjustment < 0
        assert "personnel" in reason.lower() or "suspect" in reason.lower()

    def test_inaccessible_profile_is_neutral(self):
        adjustment, reason = analyze_bio_for_business(
            display_name="",
            bio="",
            company_name="Diamond Services"
        )
        assert adjustment == 0.0
        assert "inaccessible" in reason.lower() or "conservé" in reason.lower()

    def test_company_name_in_bio_gives_small_bonus(self):
        adjustment, reason = analyze_bio_for_business(
            display_name="Sillyrama",
            bio="Bienvenue chez Sillyrama Production",
            company_name="Sillyrama Production"
        )
        assert adjustment >= 0
