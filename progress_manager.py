"""
Module de persistance et de reprise d'exécution.
Enregistre l'état du traitement dans un fichier JSON local de manière atomique
pour garantir la reprise sans perte après interruption (Ctrl+C, crash, coupure réseau).
"""

import json
import os
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("instagram_automation.progress")


class ProgressManager:
    """Gère l'enregistrement et le chargement de l'état d'avancement."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = self._default_state()

    def _default_state(self) -> Dict[str, Any]:
        """Retourne un dictionnaire d'état initial vierge."""
        return {
            "last_processed_id": None,
            "total_examined": 0,
            "already_had_ig": 0,
            "searches_performed": 0,
            "links_found": 0,
            "links_saved": 0,
            "duplicates_avoided": 0,
            "no_results": 0,
            "uncertain_results": 0,
            "errors": 0,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "last_update_time": datetime.now(timezone.utc).isoformat(),
            "completed": False
        }

    def load_progress(self) -> Optional[Dict[str, Any]]:
        """
        Charge l'état depuis le fichier JSON s'il existe.
        Retourne None si aucun fichier valide n'est trouvé.
        """
        if not self.file_path.exists():
            return None

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    self.state.update(data)
                    logger.info(
                        f"Progression chargée depuis {self.file_path} "
                        f"(Dernier _id: {self.state.get('last_processed_id')}, Traités: {self.state.get('total_examined')})"
                    )
                    return self.state
        except Exception as e:
            logger.warning(f"Impossible de lire le fichier de progression {self.file_path} : {e}")

        return None

    def save_progress(self, last_id: Optional[str] = None) -> None:
        """
        Sauvegarde atomique de l'état (écriture temporaire puis renommage).
        """
        if last_id:
            self.state["last_processed_id"] = str(last_id)
        self.state["last_update_time"] = datetime.now(timezone.utc).isoformat()

        temp_path = self.file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            temp_path.replace(self.file_path)
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de progression dans {self.file_path} : {e}")
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def record_examined(self, last_id: Any) -> None:
        """Incrémente le nombre total de documents examinés."""
        self.state["total_examined"] += 1
        self.state["last_processed_id"] = str(last_id)

    def record_already_has(self) -> None:
        """Incrémente le compteur de documents déjà équipés."""
        self.state["already_had_ig"] += 1

    def record_search(self) -> None:
        """Incrémente le compteur de recherches web/site effectuées."""
        self.state["searches_performed"] += 1

    def record_found(self) -> None:
        """Incrémente le compteur de profils trouvés."""
        self.state["links_found"] += 1

    def record_saved(self) -> None:
        """Incrémente le compteur de liens enregistrés en base."""
        self.state["links_saved"] += 1

    def record_duplicate_avoided(self) -> None:
        """Incrémente le compteur de doublons évités."""
        self.state["duplicates_avoided"] += 1

    def record_no_result(self) -> None:
        """Incrémente le compteur de recherches sans aucun résultat."""
        self.state["no_results"] += 1

    def record_uncertain(self) -> None:
        """Incrémente le compteur de résultats incertains (MEDIUM / LOW)."""
        self.state["uncertain_results"] += 1

    def record_error(self) -> None:
        """Incrémente le compteur d'erreurs techniques."""
        self.state["errors"] += 1

    def mark_completed(self) -> None:
        """Marque le traitement comme entièrement achevé."""
        self.state["completed"] = True
        self.save_progress()

    def get_last_processed_id(self) -> Optional[str]:
        """Retourne le dernier _id traité."""
        return self.state.get("last_processed_id")

    def get_summary(self) -> Dict[str, Any]:
        """Retourne une copie des métriques de progression."""
        return dict(self.state)
