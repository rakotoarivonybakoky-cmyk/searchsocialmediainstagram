"""
Tests unitaires pour le module de gestion de progression (ProgressManager).
Vérifie la sauvegarde atomique, la reprise sur interruption et l'intégrité des compteurs.
"""

from progress_manager import ProgressManager


class TestProgressManager:
    """Tests du cycle de vie du suivi de progression."""

    def test_default_state_initialization(self, tmp_path):
        progress_file = tmp_path / "progress.json"
        mgr = ProgressManager(progress_file)

        assert mgr.get_last_processed_id() is None
        summary = mgr.get_summary()
        assert summary["total_examined"] == 0
        assert summary["completed"] is False

    def test_record_and_save_progress(self, tmp_path):
        progress_file = tmp_path / "progress.json"
        mgr = ProgressManager(progress_file)

        mgr.record_examined("60d5ec49f1b2c82b8c8b4567")
        mgr.record_search()
        mgr.record_found()
        mgr.record_saved()
        mgr.record_duplicate_avoided()
        mgr.save_progress(last_id="60d5ec49f1b2c82b8c8b4567")

        assert progress_file.exists()

        # Rechargement dans une nouvelle instance (simulation de redémarrage après arrêt)
        mgr_reloaded = ProgressManager(progress_file)
        loaded = mgr_reloaded.load_progress()

        assert loaded is not None
        assert mgr_reloaded.get_last_processed_id() == "60d5ec49f1b2c82b8c8b4567"
        assert loaded["total_examined"] == 1
        assert loaded["searches_performed"] == 1
        assert loaded["links_found"] == 1
        assert loaded["links_saved"] == 1
        assert loaded["duplicates_avoided"] == 1

    def test_resume_non_existent_file(self, tmp_path):
        non_existent = tmp_path / "does_not_exist.json"
        mgr = ProgressManager(non_existent)
        assert mgr.load_progress() is None
