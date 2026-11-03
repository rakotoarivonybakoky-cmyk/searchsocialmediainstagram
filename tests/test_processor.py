"""
Tests d'intégration et simulation de boucle de traitement (Processor).
Vérifie le respect du seuil de confiance, le mode dry-run,
les limites d'exécution et la génération des rapports.
"""

from unittest.mock import MagicMock
from bson import ObjectId
import pytest

from processor import AutomationProcessor
from config import AppConfig
from instagram_validator import ValidationResult


@pytest.fixture
def mock_dependencies(tmp_path):
    """Création d'un ensemble de dépendances mockées avec répertoires isolés."""
    config = AppConfig(
        mongodb_uri="mongodb://dummy:dummy@localhost:27017/test",
        mongodb_db_name="leadfeeder-social-accounts",
        mongodb_collection_name="adding_social_accounts",
        search_provider="hybrid",
        google_api_key=None,
        google_cse_id=None,
        serpapi_key=None,
        rate_limit_delay=0.0,
        request_timeout=1,
        max_retries=1,
        confidence_threshold="HIGH",
        log_level="INFO",
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
        progress_file=tmp_path / "logs" / "progress.json"
    )
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    db_service = MagicMock()
    search_service = MagicMock()
    progress_manager = MagicMock()
    report_manager = MagicMock()

    progress_manager.get_summary.return_value = {
        "total_examined": 0,
        "already_had_ig": 0,
        "searches_performed": 0,
        "links_found": 0,
        "links_saved": 0,
        "duplicates_avoided": 0,
        "no_results": 0,
        "uncertain_results": 0,
        "errors": 0
    }

    return config, db_service, search_service, progress_manager, report_manager


def _make_candidate(url, username, confidence, similarity=80.0, reason="Test"):
    """Helper : crée un ValidationResult complet pour les tests."""
    return ValidationResult(
        is_valid=True,
        clean_url=url,
        username=username,
        confidence=confidence,
        reason=reason,
        similarity=similarity
    )


class TestAutomationProcessor:
    """Tests du comportement de la boucle de traitement."""

    def test_high_confidence_is_saved_to_db(self, mock_dependencies):
        config, db_service, search_service, progress_manager, report_manager = mock_dependencies

        doc_id = ObjectId()
        sample_doc = {
            "_id": doc_id,
            "companyName": "Acme Tools",
            "url": "https://acmetools.com",
            "socialAccounts": {}
        }

        db_service.stream_companies_without_instagram.return_value = [sample_doc]
        db_service.verify_document_structure.return_value = (True, "OK")
        db_service.has_existing_instagram.return_value = False

        # 3 candidats classés par similarité décroissante
        candidates = [
            _make_candidate("https://www.instagram.com/acmetools/", "acmetools", "HIGH", 95.0, "Site officiel"),
            _make_candidate("https://www.instagram.com/acme_tools_fr/", "acme_tools_fr", "MEDIUM", 55.0),
            _make_candidate("https://www.instagram.com/acme_other/", "acme_other", "LOW", 20.0),
        ]
        search_service.find_top_instagram_candidates.return_value = candidates

        db_service.update_instagram_candidates.return_value = {"status": "updated", "success": True}

        processor = AutomationProcessor(
            config=config,
            mongodb_service=db_service,
            search_service=search_service,
            progress_manager=progress_manager,
            report_manager=report_manager,
            dry_run=False,
            confidence_threshold="HIGH"
        )

        processor.run()

        # Doit avoir appelé update_instagram_candidates avec tous les candidats
        db_service.update_instagram_candidates.assert_called_once_with(
            doc_id=doc_id,
            candidates=candidates,
            company_name="Acme Tools",
            dry_run=False
        )
        progress_manager.record_saved.assert_called_once()
        report_manager.record_added.assert_called_once()

    def test_medium_confidence_is_sent_to_review_not_db(self, mock_dependencies):
        config, db_service, search_service, progress_manager, report_manager = mock_dependencies

        doc_id = ObjectId()
        sample_doc = {
            "_id": doc_id,
            "companyName": "Acme Global",
            "socialAccounts": {}
        }

        db_service.stream_companies_without_instagram.return_value = [sample_doc]
        db_service.verify_document_structure.return_value = (True, "OK")
        db_service.has_existing_instagram.return_value = False

        # Meilleur candidat MEDIUM seulement
        candidates = [
            _make_candidate(
                "https://www.instagram.com/acme_unverified/",
                "acme_unverified",
                "MEDIUM",
                45.0,
                "Correspondance partielle"
            )
        ]
        search_service.find_top_instagram_candidates.return_value = candidates

        processor = AutomationProcessor(
            config=config,
            mongodb_service=db_service,
            search_service=search_service,
            progress_manager=progress_manager,
            report_manager=report_manager,
            dry_run=False,
            confidence_threshold="HIGH"  # Seuil strict
        )

        processor.run()

        # Ne doit JAMAIS toucher la base MongoDB
        db_service.update_instagram_candidates.assert_not_called()
        progress_manager.record_uncertain.assert_called_once()
        report_manager.record_uncertain.assert_called_once()

    def test_no_candidates_records_no_result(self, mock_dependencies):
        config, db_service, search_service, progress_manager, report_manager = mock_dependencies

        doc_id = ObjectId()
        sample_doc = {
            "_id": doc_id,
            "companyName": "Ghost Corp",
            "socialAccounts": {}
        }

        db_service.stream_companies_without_instagram.return_value = [sample_doc]
        db_service.verify_document_structure.return_value = (True, "OK")
        db_service.has_existing_instagram.return_value = False
        search_service.find_top_instagram_candidates.return_value = []

        processor = AutomationProcessor(
            config=config,
            mongodb_service=db_service,
            search_service=search_service,
            progress_manager=progress_manager,
            report_manager=report_manager,
        )

        processor.run()

        db_service.update_instagram_candidates.assert_not_called()
        progress_manager.record_no_result.assert_called_once()

    def test_respect_limit(self, mock_dependencies):
        config, db_service, search_service, progress_manager, report_manager = mock_dependencies

        docs = [
            {"_id": ObjectId(), "companyName": f"Corp {i}", "socialAccounts": {}}
            for i in range(10)
        ]

        db_service.stream_companies_without_instagram.return_value = iter(docs)
        db_service.verify_document_structure.return_value = (True, "OK")
        db_service.has_existing_instagram.return_value = False
        search_service.find_top_instagram_candidates.return_value = []

        processor = AutomationProcessor(
            config=config,
            mongodb_service=db_service,
            search_service=search_service,
            progress_manager=progress_manager,
            report_manager=report_manager,
            limit=3
        )

        processor.run()

        assert progress_manager.record_examined.call_count == 3

    def test_dry_run_calls_update_with_dry_run_flag(self, mock_dependencies):
        config, db_service, search_service, progress_manager, report_manager = mock_dependencies

        doc_id = ObjectId()
        sample_doc = {
            "_id": doc_id,
            "companyName": "Dry Corp",
            "url": "https://drycorp.com",
            "socialAccounts": {}
        }

        db_service.stream_companies_without_instagram.return_value = [sample_doc]
        db_service.verify_document_structure.return_value = (True, "OK")
        db_service.has_existing_instagram.return_value = False

        candidates = [
            _make_candidate("https://www.instagram.com/drycorp/", "drycorp", "HIGH", 90.0)
        ]
        search_service.find_top_instagram_candidates.return_value = candidates
        db_service.update_instagram_candidates.return_value = {"status": "simulated", "success": True}

        processor = AutomationProcessor(
            config=config,
            mongodb_service=db_service,
            search_service=search_service,
            progress_manager=progress_manager,
            report_manager=report_manager,
            dry_run=True,
            confidence_threshold="HIGH"
        )

        processor.run()

        # Doit appeler update_instagram_candidates avec dry_run=True
        db_service.update_instagram_candidates.assert_called_once_with(
            doc_id=doc_id,
            candidates=candidates,
            company_name="Dry Corp",
            dry_run=True
        )
        progress_manager.record_saved.assert_called_once()
