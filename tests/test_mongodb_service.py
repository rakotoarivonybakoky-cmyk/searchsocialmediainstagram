"""
Tests unitaires pour le service MongoDB.
Vérifie les règles d'intégrité, la prévention des doublons, la détection des structures
inattendues et la préservation absolue des autres plateformes et champs.
"""

from unittest.mock import MagicMock
from bson import ObjectId
import pytest

from mongodb_service import MongoDBService
from config import AppConfig, mask_mongodb_uri


@pytest.fixture
def dummy_config(tmp_path):
    """Configuration fictive isolée pour les tests."""
    return AppConfig(
        mongodb_uri="mongodb://fake_user:secret_password@57.129.18.234:27017/leadfeeder-social-accounts?authSource=leadfeeder-social-accounts",
        mongodb_db_name="leadfeeder-social-accounts",
        mongodb_collection_name="adding_social_accounts",
        search_provider="hybrid",
        google_api_key=None,
        google_cse_id=None,
        serpapi_key=None,
        rate_limit_delay=0.0,
        request_timeout=5,
        max_retries=1,
        confidence_threshold="HIGH",
        log_level="INFO",
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
        progress_file=tmp_path / "progress.json"
    )


class TestMongoDBProtectionRules:
    """Vérification des protections et de l'intégrité des données."""

    def test_mask_mongodb_uri(self):
        uri = "mongodb://adding_social_accounts_user:45dfgd454gf26zeerf@57.129.18.234:27017/leadfeeder"
        masked = mask_mongodb_uri(uri)
        assert "45dfgd454gf26zeerf" not in masked
        assert "adding_social_accounts_user" not in masked
        assert "***:***" in masked
        assert "57.129.18.234" in masked

    def test_has_existing_instagram_cases(self, dummy_config):
        service = MongoDBService(dummy_config)

        # 1. Document sans socialAccounts
        doc1 = {"_id": ObjectId(), "companyName": "Test 1"}
        assert service.has_existing_instagram(doc1) is False

        # 2. Document avec socialAccounts vide
        doc2 = {"_id": ObjectId(), "companyName": "Test 2", "socialAccounts": {}}
        assert service.has_existing_instagram(doc2) is False

        # 3. Document avec tableau instagram vide
        doc3 = {"_id": ObjectId(), "companyName": "Test 3", "socialAccounts": {"instagram": []}}
        assert service.has_existing_instagram(doc3) is False

        # 4. Document avec un autre réseau social (facebook) mais sans instagram
        doc4 = {
            "_id": ObjectId(),
            "companyName": "Test 4",
            "socialAccounts": {
                "facebook": [{"link": "https://facebook.com/test", "name": "Test"}]
            }
        }
        assert service.has_existing_instagram(doc4) is False

        # 5. Document avec instagram déjà présent
        doc5 = {
            "_id": ObjectId(),
            "companyName": "Test 5",
            "socialAccounts": {
                "instagram": [{"link": "https://instagram.com/test/", "name": "Test"}]
            }
        }
        assert service.has_existing_instagram(doc5) is True

    def test_verify_document_structure(self, dummy_config):
        service = MongoDBService(dummy_config)

        # Structure valide standard
        valid_doc = {
            "_id": ObjectId(),
            "companyName": "Valid Corp",
            "socialAccounts": {"facebook": []}
        }
        is_val, reason = service.verify_document_structure(valid_doc)
        assert is_val is True

        # Structure sans _id
        invalid_id = {"companyName": "No ID"}
        is_val, reason = service.verify_document_structure(invalid_id)
        assert is_val is False

        # socialAccounts n'est pas un dict (ex: chaîne de caractères)
        corrupted_social = {
            "_id": ObjectId(),
            "companyName": "Corrupted",
            "socialAccounts": "invalid_string_type"
        }
        is_val, reason = service.verify_document_structure(corrupted_social)
        assert is_val is False
        assert "inattendu" in reason

        # socialAccounts.instagram n'est pas une liste
        corrupted_ig = {
            "_id": ObjectId(),
            "companyName": "Corrupted IG",
            "socialAccounts": {"instagram": "https://instagram.com/bad_format"}
        }
        is_val, reason = service.verify_document_structure(corrupted_ig)
        assert is_val is False

    def test_atomic_update_preserves_other_platforms_and_prevents_duplicates(self, dummy_config):
        service = MongoDBService(dummy_config)

        # Simulation d'un document existant avec Facebook
        mock_collection = MagicMock()
        service._collection = mock_collection

        doc_id = ObjectId()
        initial_doc = {
            "_id": doc_id,
            "companyName": "Sillyrama Production",
            "socialAccounts": {
                "facebook": [{"link": "https://facebook.com/silly", "name": "Sillyrama"}]
            }
        }

        mock_collection.find_one.return_value = initial_doc
        mock_result = MagicMock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1
        mock_collection.update_one.return_value = mock_result

        # Tentative d'ajout
        res = service.update_instagram_link(
            doc_id=doc_id,
            instagram_link="https://www.instagram.com/sillyrama/",
            company_name="Sillyrama Production",
            dry_run=False
        )

        assert res["success"] is True
        assert res["status"] == "updated"

        # Vérification des arguments d'appel update_one
        call_args = mock_collection.update_one.call_args
        filter_arg = call_args[0][0]
        update_arg = call_args[0][1]

        # 1. Vérification que l'update est ciblé par _id
        assert filter_arg["_id"] == doc_id
        # 2. Vérification que la clause anti-doublon est active
        assert filter_arg["socialAccounts.instagram.link"] == {"$ne": "https://www.instagram.com/sillyrama/"}
        # 3. Vérification que $addToSet est utilisé (ne remplace pas socialAccounts)
        assert "$addToSet" in update_arg
        assert "socialAccounts.instagram" in update_arg["$addToSet"]

    def test_update_duplicate_detection(self, dummy_config):
        service = MongoDBService(dummy_config)
        mock_collection = MagicMock()
        service._collection = mock_collection

        doc_id = ObjectId()
        # Le lien existe déjà dans le document
        existing_doc = {
            "_id": doc_id,
            "socialAccounts": {
                "instagram": [{"link": "https://www.instagram.com/sillyrama/", "name": "Silly"}]
            }
        }
        mock_collection.find_one.return_value = existing_doc

        res = service.update_instagram_link(
            doc_id=doc_id,
            instagram_link="https://www.instagram.com/sillyrama/",
            company_name="Sillyrama",
            dry_run=False
        )

        # Doit refuser sans appeler update_one
        assert res["success"] is True
        assert res["modified"] is False
        assert res["status"] == "already_exists"
        mock_collection.update_one.assert_not_called()

    def test_dry_run_mode_does_not_call_database_update(self, dummy_config):
        service = MongoDBService(dummy_config)
        mock_collection = MagicMock()
        service._collection = mock_collection

        res = service.update_instagram_link(
            doc_id=ObjectId(),
            instagram_link="https://www.instagram.com/test/",
            company_name="Test Corp",
            dry_run=True
        )

        assert res["success"] is True
        assert res["status"] == "simulated"
        mock_collection.update_one.assert_not_called()
        mock_collection.find_one.assert_not_called()

    def test_update_instagram_candidates_stores_sorted_by_similarity(self, dummy_config):
        """update_instagram_candidates doit stocker jusqu'à 3 entrées triées par similarité décroissante."""
        from instagram_validator import ValidationResult

        service = MongoDBService(dummy_config)
        mock_collection = MagicMock()
        service._collection = mock_collection

        doc_id = ObjectId()
        mock_collection.find_one.return_value = {
            "_id": doc_id,
            "socialAccounts": {"facebook": [{"link": "https://facebook.com/test", "name": "Test"}]}
        }
        mock_result = MagicMock()
        mock_result.modified_count = 1
        mock_collection.update_one.return_value = mock_result

        candidates = [
            ValidationResult(is_valid=True, clean_url="https://instagram.com/best/", username="best", confidence="HIGH", reason="Site officiel", similarity=90.0),
            ValidationResult(is_valid=True, clean_url="https://instagram.com/second/", username="second", confidence="MEDIUM", reason="DuckDuckGo", similarity=55.0),
            ValidationResult(is_valid=True, clean_url="https://instagram.com/third/", username="third", confidence="LOW", reason="Faible", similarity=20.0),
        ]

        res = service.update_instagram_candidates(
            doc_id=doc_id,
            candidates=candidates,
            company_name="Test Corp",
            dry_run=False
        )

        assert res["success"] is True
        assert res["status"] == "updated"

        # Vérification de l'opération $set sur socialAccounts.instagram
        call_args = mock_collection.update_one.call_args[0]
        update_arg = call_args[1]
        assert "$set" in update_arg
        stored = update_arg["$set"]["socialAccounts.instagram"]

        # Doit avoir 3 entrées avec match_percentage
        assert len(stored) == 3
        assert stored[0]["match_percentage"] == 90.0
        assert stored[1]["match_percentage"] == 55.0
        assert stored[2]["match_percentage"] == 20.0
        assert stored[0]["link"] == "https://instagram.com/best/"
        assert "match_percentage" in stored[0]

    def test_update_instagram_candidates_dry_run(self, dummy_config):
        """En dry-run, update_instagram_candidates ne doit pas toucher la base."""
        from instagram_validator import ValidationResult

        service = MongoDBService(dummy_config)
        mock_collection = MagicMock()
        service._collection = mock_collection

        candidates = [
            ValidationResult(is_valid=True, clean_url="https://instagram.com/test/", username="test", confidence="HIGH", reason="ok", similarity=80.0)
        ]

        res = service.update_instagram_candidates(
            doc_id=ObjectId(),
            candidates=candidates,
            company_name="Test Corp",
            dry_run=True
        )

        assert res["status"] == "simulated"
        mock_collection.update_one.assert_not_called()
        mock_collection.find_one.assert_not_called()

    def test_has_existing_instagram_ignores_empty_links(self, dummy_config):
        """Les liens vides (https://instagram.com/ sans username) doivent être considérés comme absents."""
        service = MongoDBService(dummy_config)

        doc = {
            "_id": ObjectId(),
            "socialAccounts": {
                "instagram": [{"link": "https://instagram.com/", "name": ""}]
            }
        }
        # Lien vide = pas de compte valide
        assert service.has_existing_instagram(doc) is False

        doc_valid = {
            "_id": ObjectId(),
            "socialAccounts": {
                "instagram": [{"link": "https://instagram.com/realcompany", "name": "realcompany"}]
            }
        }
        assert service.has_existing_instagram(doc_valid) is True
