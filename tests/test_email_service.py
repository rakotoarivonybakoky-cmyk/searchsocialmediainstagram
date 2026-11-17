"""
Tests unitaires pour le module email_service (SMTP).
Vérifie l'assemblage des emails, le respect du statut activé/désactivé,
la résilience face aux pannes réseau et l'absence totale d'exception vers l'application.
"""

from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from config import AppConfig
from email_service import EmailService


@pytest.fixture
def base_config(tmp_path):
    """Fixture retournant une configuration de test sûre avec SMTP désactivé."""
    return AppConfig(
        mongodb_uri="mongodb://fake_user:fake_pass@127.0.0.1:27017/leadfeeder-social-accounts",
        mongodb_db_name="leadfeeder-social-accounts",
        mongodb_collection_name="adding_social_accounts",
        search_provider="hybrid",
        google_api_key=None,
        google_cse_id=None,
        serpapi_key=None,
        rate_limit_delay=0.1,
        request_timeout=2,
        max_retries=1,
        confidence_threshold="HIGH",
        log_level="INFO",
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
        progress_file=tmp_path / "logs" / "progress.json",
        smtp_enabled=False,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_use_ssl=False,
        smtp_user=None,
        smtp_password=None,
        smtp_from=None,
        admin_email=None,
    )


@pytest.fixture
def enabled_config(tmp_path):
    """Fixture avec SMTP activé et paramètres définis."""
    return AppConfig(
        mongodb_uri="mongodb://fake_user:fake_pass@127.0.0.1:27017/leadfeeder-social-accounts",
        mongodb_db_name="leadfeeder-social-accounts",
        mongodb_collection_name="adding_social_accounts",
        search_provider="hybrid",
        google_api_key=None,
        google_cse_id=None,
        serpapi_key=None,
        rate_limit_delay=0.1,
        request_timeout=2,
        max_retries=1,
        confidence_threshold="HIGH",
        log_level="INFO",
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
        progress_file=tmp_path / "logs" / "progress.json",
        smtp_enabled=True,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_use_ssl=False,
        smtp_user="sender@gmail.com",
        smtp_password="app_password_16char",
        smtp_from="sender@gmail.com",
        admin_email="admin@example.com",
    )


class TestEmailServiceDisabled:
    """Vérifie le comportement lorsque SMTP est désactivé."""

    def test_disabled_smtp_does_not_connect(self, base_config):
        service = EmailService(base_config)
        with patch("smtplib.SMTP") as mock_smtp:
            result = service.send_email(
                subject="Test",
                text_body="Corps de test"
            )
            assert result is False
            mock_smtp.assert_not_called()

    def test_disabled_summary_report_returns_false(self, base_config):
        service = EmailService(base_config)
        result = service.send_summary_report({"total_examined": 10})
        assert result is False

    def test_disabled_error_alert_returns_false(self, base_config):
        service = EmailService(base_config)
        result = service.send_error_alert("Titre erreur", "Détail technique")
        assert result is False


class TestEmailServiceEnabled:
    """Vérifie le bon fonctionnement de l'envoi d'email avec mock SMTP."""

    @patch("smtplib.SMTP")
    def test_successful_email_send(self, mock_smtp_class, enabled_config):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        service = EmailService(enabled_config)
        success = service.send_email(
            subject="Test Sujet",
            text_body="Contenu texte",
            html_body="<p>Contenu HTML</p>"
        )

        assert success is True
        mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=7)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@gmail.com", "app_password_16char")
        mock_server.sendmail.assert_called_once()

        # Vérification du destinataire
        args, kwargs = mock_server.sendmail.call_args
        assert args[0] == "sender@gmail.com"
        assert args[1] == ["admin@example.com"]

    @patch("smtplib.SMTP")
    def test_smtp_network_failure_is_caught_gracefully(self, mock_smtp_class, enabled_config):
        """Une erreur de connexion SMTP ne doit JAMAIS lever d'exception."""
        mock_smtp_class.side_effect = ConnectionRefusedError("Connexion refusée")

        service = EmailService(enabled_config)
        # L'appel ne doit pas planter l'application
        success = service.send_email(
            subject="Alerte",
            text_body="Test d'erreur réseau"
        )
        assert success is False

    @patch("smtplib.SMTP")
    def test_send_summary_report_formats_metrics(self, mock_smtp_class, enabled_config):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        service = EmailService(enabled_config)
        summary = {
            "total_examined": 120,
            "already_had_ig": 5,
            "searches_performed": 115,
            "links_found": 35,
            "links_saved": 28,
            "no_results": 70,
            "uncertain_results": 12,
            "errors": 0,
            "session_processed": 120,
            "session_duration_seconds": 65.4,
            "speed_docs_per_minute": 110.0,
            "remaining_missing_instagram_in_db": 520000
        }

        success = service.send_summary_report(summary, status="SUCCÈS")
        assert success is True
        mock_server.sendmail.assert_called_once()

        import email
        from email.header import decode_header
        sent_raw = mock_server.sendmail.call_args[0][2]
        parsed = email.message_from_string(sent_raw)
        decoded_parts = decode_header(parsed["Subject"])
        full_subject = "".join(
            part.decode(enc or "utf-8") if isinstance(part, bytes) else part
            for part, enc in decoded_parts
        )
        assert "RAPPORT INSTAGRAM" in full_subject
        assert "28" in full_subject

    @patch("smtplib.SMTP")
    def test_send_error_alert_deduplication(self, mock_smtp_class, enabled_config):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        service = EmailService(enabled_config)
        # Premier envoi
        res1 = service.send_error_alert("Erreur Connexion", "Host introuvable", "main.py")
        assert res1 is True
        assert mock_server.sendmail.call_count == 1

        # Deuxième envoi identique consécutif -> dédupliqué pour éviter le spam
        res2 = service.send_error_alert("Erreur Connexion", "Host introuvable", "main.py")
        assert res2 is False
        assert mock_server.sendmail.call_count == 1
