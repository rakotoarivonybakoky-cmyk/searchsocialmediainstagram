"""
Module de service SMTP pour l'envoi de rapports et de notifications d'alertes.
Utilise exclusivement la bibliothèque standard Python (smtplib, email) :
aucune dépendance externe supplémentaire n'est requise.

RÈGLES DE SÉCURITÉ ET FIABILITÉ :
- Si SMTP_ENABLED=false, l'automatisation continue normalement sans bloquer.
- En cas d'échec de connexion SMTP ou d'envoi d'email, aucune exception n'est propagée
  vers le flux principal (le traitement MongoDB ne doit JAMAIS être interrompu).
- Aucun mot de passe SMTP n'est exposé dans les logs.
"""

import smtplib
import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, Optional

from config import AppConfig

logger = logging.getLogger("instagram_automation.email")


class EmailService:
    """Gestionnaire d'envoi d'emails transactionnels et de rapports automatisés."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._last_error_sent: Optional[str] = None

    def send_email(
        self,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Envoie un email via SMTP en utilisant la configuration active.
        Retourne True si l'envoi a réussi, False sinon.
        Ne lève JAMAIS d'exception afin de préserver l'exécution du pipeline.
        """
        if not self.config.smtp_enabled:
            logger.debug("SMTP est désactivé (SMTP_ENABLED=false). Envoi ignoré.")
            return False

        # Vérification des champs requis
        host = self.config.smtp_host
        port = self.config.smtp_port
        user = self.config.smtp_user
        password = self.config.smtp_password
        sender = self.config.smtp_from or user
        recipient = self.config.admin_email

        if not host or not user or not password or not recipient:
            logger.warning(
                "SMTP activé mais configuration incomplète : "
                f"host={bool(host)}, user={bool(user)}, "
                f"password={bool(password)}, admin_email={bool(recipient)}. Email non envoyé."
            )
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = recipient

            part_text = MIMEText(text_body, "plain", "utf-8")
            msg.attach(part_text)

            if html_body:
                part_html = MIMEText(html_body, "html", "utf-8")
                msg.attach(part_html)

            logger.info(f"Connexion au serveur SMTP {host}:{port} pour envoi à '{recipient}'...")

            if self.config.smtp_use_ssl:
                smtp_client = smtplib.SMTP_SSL(host, port, timeout=self.config.request_timeout + 5)
            else:
                smtp_client = smtplib.SMTP(host, port, timeout=self.config.request_timeout + 5)

            with smtp_client as server:
                if self.config.smtp_use_tls and not self.config.smtp_use_ssl:
                    server.starttls()
                server.login(user, password)
                server.sendmail(sender, [recipient], msg.as_string())

            logger.info(f"Email envoyé avec succès à '{recipient}' (Sujet: '{subject}').")
            return True

        except Exception as e:
            # Sécurité : ne jamais faire fuiter le mot de passe dans les logs
            clean_error = str(e).replace(password, "***") if password else str(e)
            logger.error(f"Échec d'envoi de l'email SMTP vers '{recipient}': {clean_error}")
            return False

    def send_summary_report(
        self,
        summary_data: Dict[str, Any],
        status: str = "SUCCÈS"
    ) -> bool:
        """
        Formate et envoie le rapport final avec les statistiques réelles
        du traitement à l'administrateur.
        """
        if not self.config.smtp_enabled:
            return False

        total_examined = summary_data.get("total_examined", 0)
        already_had_ig = summary_data.get("already_had_ig", 0)
        searches_performed = summary_data.get("searches_performed", 0)
        links_found = summary_data.get("links_found", 0)
        links_saved = summary_data.get("links_saved", 0)
        no_results = summary_data.get("no_results", 0)
        uncertain = summary_data.get("uncertain_results", 0)
        errors = summary_data.get("errors", 0)
        remaining = summary_data.get("remaining_missing_instagram_in_db")
        remaining_str = f"{remaining:,}" if isinstance(remaining, int) else "Non calculé"
        session_processed = summary_data.get("session_processed", 0)
        duration = summary_data.get("session_duration_seconds", 0)
        speed = summary_data.get("speed_docs_per_minute", 0)

        now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M:%S UTC")

        subject = f"[RAPPORT INSTAGRAM] {status} - {links_saved} liens ajoutés ({now_str.split(' à ')[0]})"

        text_body = f"""====================================================================
  RAPPORT D'AUTOMATISATION DES LIENS INSTAGRAM DANS MONGODB
====================================================================
Date et heure d'exécution  : {now_str}
Statut final du traitement : {status}
Durée de la session        : {duration} s ({speed} docs/min)
--------------------------------------------------------------------
STATISTIQUES DE TRAITEMENT :
  1. Nombre total d'entreprises examinées       : {total_examined}
  2. Entreprises traitées cette session        : {session_processed}
  3. Entreprises déjà pourvues d'un compte IG   : {already_had_ig}
  4. Nombre de recherches web/site effectuées   : {searches_performed}
  5. Liens Instagram découverts                 : {links_found}
  6. Liens Instagram ENREGISTRÉS dans MongoDB   : {links_saved}
  7. Entreprises sans résultat trouvé           : {no_results}
  8. Résultats incertains (mis en revue)        : {uncertain}
  9. Erreurs techniques rencontrées             : {errors}
 10. Entreprises restantes à traiter en base    : {remaining_str}
====================================================================
Ce message a été généré automatiquement par le pipeline d'automatisation.
"""

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; margin: 0; padding: 20px; }}
  .card {{ max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #d0d7de; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
  .header {{ background: #0969da; color: #ffffff; padding: 20px; text-align: center; }}
  .header h2 {{ margin: 0; font-size: 20px; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 12px; background: rgba(255,255,255,0.25); margin-top: 8px; }}
  .content {{ padding: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #eaecef; }}
  th {{ background-color: #f6f8fa; color: #57606a; }}
  .highlight {{ color: #1a7f37; font-weight: bold; }}
  .warn {{ color: #9a6700; }}
  .error {{ color: #cf222e; }}
  .footer {{ background: #f6f8fa; padding: 12px 20px; font-size: 12px; color: #57606a; text-align: center; border-top: 1px solid #eaecef; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h2>Bilan d'Automatisation Instagram</h2>
    <span class="badge">Statut : {status}</span>
  </div>
  <div class="content">
    <p><strong>Date d'exécution :</strong> {now_str}</p>
    <p><strong>Durée de la session :</strong> {duration} s ({speed} docs/min)</p>
    <table>
      <thead>
        <tr>
          <th>Métrique</th>
          <th style="text-align: right;">Valeur</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>Entreprises examinées (total)</td><td style="text-align: right;"><b>{total_examined}</b></td></tr>
        <tr><td>Entreprises traitées dans cette session</td><td style="text-align: right;">{session_processed}</td></tr>
        <tr><td>Déjà pourvues d'un compte Instagram</td><td style="text-align: right;">{already_had_ig}</td></tr>
        <tr><td>Recherches web / site effectuées</td><td style="text-align: right;">{searches_performed}</td></tr>
        <tr><td>Liens Instagram découverts</td><td style="text-align: right;">{links_found}</td></tr>
        <tr style="background-color: #dafbe1;">
          <td><b class="highlight">Liens Instagram ENREGISTRÉS dans MongoDB</b></td>
          <td style="text-align: right;"><b class="highlight">{links_saved}</b></td>
        </tr>
        <tr><td>Entreprises sans résultat trouvé</td><td style="text-align: right;">{no_results}</td></tr>
        <tr><td>Résultats incertains (mis en revue)</td><td style="text-align: right;" class="warn">{uncertain}</td></tr>
        <tr><td>Erreurs techniques rencontrées</td><td style="text-align: right;" class="{ 'error' if errors > 0 else '' }">{errors}</td></tr>
        <tr><td>Entreprises restantes à traiter en base</td><td style="text-align: right;"><b>{remaining_str}</b></td></tr>
      </tbody>
    </table>
  </div>
  <div class="footer">
    Automatisation Instagram &bull; Rapport automatique &bull; Base MongoDB leadfeeder-social-accounts
  </div>
</div>
</body>
</html>
"""
        return self.send_email(subject=subject, text_body=text_body, html_body=html_body)

    def send_error_alert(
        self,
        error_title: str,
        error_details: str,
        context: Optional[str] = None
    ) -> bool:
        """
        Envoie une alerte immédiate à l'administrateur en cas d'erreur critique
        (ex : panne de connexion MongoDB, arrêt inattendu).
        Évite d'envoyer des doublons identiques consécutifs.
        """
        if not self.config.smtp_enabled:
            return False

        error_sig = f"{error_title}:{error_details}"
        if self._last_error_sent == error_sig:
            logger.debug("Notification d'erreur identique déjà envoyée. Doublon évité.")
            return False

        self._last_error_sent = error_sig
        now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M:%S UTC")

        subject = f"[ALERTE ERREUR INSTAGRAM] {error_title}"

        text_body = f"""====================================================================
  ALERTE CRITIQUE - AUTOMATISATION INSTAGRAM MONGODB
====================================================================
Date et heure de l'incident : {now_str}
Type d'erreur               : {error_title}
Contexte                    : {context or 'Non précisé'}
--------------------------------------------------------------------
DÉTAILS DE L'ERREUR :
{error_details}
====================================================================
Veuillez vérifier l'état du serveur ou la connectivité MongoDB.
"""

        html_body = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f6f8fa; margin: 0; padding: 20px; }}
  .card {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #cf222e; overflow: hidden; }}
  .header {{ background: #cf222e; color: #ffffff; padding: 18px; text-align: center; }}
  .header h2 {{ margin: 0; font-size: 18px; }}
  .content {{ padding: 20px; font-size: 14px; color: #24292f; }}
  .error-box {{ background-color: #ffebe9; border-left: 4px solid #cf222e; padding: 12px; margin: 15px 0; font-family: monospace; font-size: 13px; color: #82071e; white-space: pre-wrap; word-break: break-all; }}
  .footer {{ background: #f6f8fa; padding: 12px; font-size: 12px; color: #57606a; text-align: center; border-top: 1px solid #eaecef; }}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <h2>Alerte Critique d'Automatisation</h2>
  </div>
  <div class="content">
    <p><strong>Incident détecté :</strong> {error_title}</p>
    <p><strong>Date :</strong> {now_str}</p>
    {f"<p><strong>Contexte :</strong> {context}</p>" if context else ""}
    <p><strong>Détails techniques :</strong></p>
    <div class="error-box">{error_details}</div>
    <p>Le traitement a été interrompu ou nécessite une intervention technique.</p>
  </div>
  <div class="footer">
    Pipeline Instagram &bull; Notification automatique d'incident
  </div>
</div>
</body>
</html>
"""
        return self.send_email(subject=subject, text_body=text_body, html_body=html_body)
