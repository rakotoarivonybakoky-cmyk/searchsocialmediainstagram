"""
Module de génération des rapports et de restitution console.
Enregistre les résultats en CSV et JSON locaux dans le dossier reports/
sans jamais exposer d'identifiants MongoDB ou de données sensibles.
"""

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import AppConfig

logger = logging.getLogger("instagram_automation.reports")


class ReportManager:
    """Gère l'écriture des fichiers de rapport et l'affichage des bilans."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.reports_dir = config.reports_dir
        self.timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Fichiers de rapport pour cette session
        self.added_csv_path = self.reports_dir / f"high_confidence_added_{self.timestamp}.csv"
        self.uncertain_csv_path = self.reports_dir / f"uncertain_to_review_{self.timestamp}.csv"
        self.errors_csv_path = self.reports_dir / f"errors_{self.timestamp}.csv"
        self.summary_json_path = self.reports_dir / f"summary_{self.timestamp}.json"

        self._init_csv_files()

    def _init_csv_files(self) -> None:
        """Initialise les en-têtes des fichiers CSV."""
        with open(self.added_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["company_id", "company_name", "instagram_url", "confidence", "reason", "timestamp"])

        with open(self.uncertain_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["company_id", "company_name", "candidate_url", "confidence", "reason", "timestamp"])

        with open(self.errors_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["company_id", "company_name", "error_type", "message", "timestamp"])

    def record_added(
        self,
        company_id: str,
        company_name: str,
        instagram_url: str,
        confidence: str,
        reason: str
    ) -> None:
        """Enregistre un lien ajouté dans le rapport CSV."""
        now = datetime.now(timezone.utc).isoformat()
        with open(self.added_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([company_id, company_name, instagram_url, confidence, reason, now])

    def record_uncertain(
        self,
        company_id: str,
        company_name: str,
        candidate_url: str,
        confidence: str,
        reason: str
    ) -> None:
        """Enregistre un lien incertain à vérifier manuellement."""
        now = datetime.now(timezone.utc).isoformat()
        with open(self.uncertain_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([company_id, company_name, candidate_url, confidence, reason, now])

    def record_error(
        self,
        company_id: str,
        company_name: str,
        error_type: str,
        message: str
    ) -> None:
        """Enregistre une erreur d'exécution dans le rapport."""
        now = datetime.now(timezone.utc).isoformat()
        with open(self.errors_csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([company_id, company_name, error_type, message, now])

    def save_final_summary(self, summary_data: Dict[str, Any]) -> None:
        """Exporte le bilan complet au format JSON."""
        with open(self.summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Bilan exporté dans {self.summary_json_path}")

    def print_terminal_summary(
        self,
        stats: Dict[str, Any],
        remaining_in_db: Optional[int] = None
    ) -> None:
        """
        Affiche le bilan final exhaustif et élégant dans le terminal PowerShell.
        """
        total_examined = stats.get("total_examined", 0)
        already_had_ig = stats.get("already_had_ig", 0)
        searches_performed = stats.get("searches_performed", 0)
        links_found = stats.get("links_found", 0)
        links_saved = stats.get("links_saved", 0)
        duplicates_avoided = stats.get("duplicates_avoided", 0)
        no_results = stats.get("no_results", 0)
        uncertain_results = stats.get("uncertain_results", 0)
        errors = stats.get("errors", 0)
        remaining = remaining_in_db if remaining_in_db is not None else "Non calculé"

        separator = "=" * 68
        line = "-" * 68

        print("\n" + separator)
        print("          BILAN FINAL DE L'AUTOMATISATION DES LIENS INSTAGRAM       ")
        print(separator)
        print(f"  1. Nombre total d'entreprises examinées       : {total_examined:>8}")
        print(f"  2. Entreprises déjà pourvues d'un compte IG   : {already_had_ig:>8}")
        print(f"  3. Nombre de recherches web/site effectuées   : {searches_performed:>8}")
        print(f"  4. Liens Instagram découverts                 : {links_found:>8}")
        print(f"  5. Liens Instagram ENREGISTRÉS en base        : {links_saved:>8}")
        print(f"  6. Doublons détectés et évités                : {duplicates_avoided:>8}")
        print(f"  7. Entreprises sans résultat trouvé           : {no_results:>8}")
        print(f"  8. Résultats incertains (mis en revue)        : {uncertain_results:>8}")
        print(f"  9. Erreurs techniques rencontrées             : {errors:>8}")
        print(f" 10. Entreprises restantes à traiter en base    : {str(remaining):>8}")
        print(line)
        print("  Rapports détaillés enregistrés :")
        print(f"   -> Enregistrés  : {self.added_csv_path.name}")
        print(f"   -> À vérifier   : {self.uncertain_csv_path.name}")
        print(f"   -> Erreurs      : {self.errors_csv_path.name}")
        print(f"   -> Bilan JSON   : {self.summary_json_path.name}")
        print(separator + "\n")
