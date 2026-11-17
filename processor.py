"""
Module de traitement par lots et orchestration principale.
Gère le streaming des entreprises depuis MongoDB, l'automatisation de la recherche,
la vérification de fiabilité, la mise à jour atomique et la tolérance aux pannes.
"""

import time
import logging
from typing import Optional, Dict, Any

from config import AppConfig
from mongodb_service import MongoDBService
from search_service import SearchService
from progress_manager import ProgressManager
from report_manager import ReportManager
from email_service import EmailService

logger = logging.getLogger("instagram_automation.processor")


class AutomationProcessor:
    """Orchestrateur du flux de traitement."""

    def __init__(
        self,
        config: AppConfig,
        mongodb_service: MongoDBService,
        search_service: SearchService,
        progress_manager: ProgressManager,
        report_manager: ReportManager,
        dry_run: bool = False,
        limit: Optional[int] = None,
        batch_size: int = 100,
        resume: bool = False,
        confidence_threshold: str = "HIGH",
        only_with_website: Optional[bool] = None,
        email_service: Optional[EmailService] = None
    ):
        self.config = config
        self.db_service = mongodb_service
        self.search_service = search_service
        self.progress_mgr = progress_manager
        self.report_mgr = report_manager
        self.email_service = email_service or EmailService(config)
        self.dry_run = dry_run
        self.limit = limit
        self.batch_size = batch_size
        self.resume = resume
        self.confidence_threshold = confidence_threshold.upper()
        # Si le mode est website_scraper, on filtre par défaut les entreprises avec site web
        if only_with_website is None:
            self.only_with_website = (config.search_provider == "website_scraper")
        else:
            self.only_with_website = only_with_website
        self._interrupted = False

    def run(self) -> Dict[str, Any]:
        """
        Exécute le traitement complet ou limité selon les paramètres fournis.
        """
        logger.info(
            f"Démarrage du traitement [Dry-Run: {self.dry_run}, "
            f"Limite: {self.limit or 'Aucune'}, Reprise: {self.resume}, "
            f"Seuil Confiance: {self.confidence_threshold}]"
        )

        # Reprise éventuelle
        resume_id = None
        if self.resume:
            saved_state = self.progress_mgr.load_progress()
            if saved_state:
                resume_id = self.progress_mgr.get_last_processed_id()
                logger.info(f"Reprise demandée. Dernier identifiant traité : {resume_id}")
            else:
                logger.info("Aucun état antérieur trouvé pour la reprise. Démarrage depuis le début.")

        # Récupération initiale du curseur streaming
        cursor = self.db_service.stream_companies_without_instagram(
            resume_from_id=resume_id,
            batch_size=self.batch_size,
            only_with_website=self.only_with_website
        )

        processed_in_session = 0
        start_time = time.time()

        try:
            for doc in cursor:
                if self._interrupted:
                    logger.warning("Arrêt demandé par l'utilisateur.")
                    break

                doc_id = doc.get("_id")
                raw_name = doc.get("companyName")
                company_name = raw_name.strip() if isinstance(raw_name, str) else "<Sans Nom>"

                self.progress_mgr.record_examined(doc_id)
                processed_in_session += 1

                # 1. Vérification de structure
                valid_struct, reason = self.db_service.verify_document_structure(doc)
                if not valid_struct:
                    logger.warning(f"Document {doc_id} structure invalide : {reason}")
                    self.progress_mgr.record_error()
                    self.report_mgr.record_error(str(doc_id), company_name, "INVALID_STRUCTURE", reason)
                    continue

                # 2. Vérification si Instagram est déjà présent
                if self.db_service.has_existing_instagram(doc):
                    logger.debug(f"Document {doc_id} a déjà un compte Instagram. Ignoré.")
                    self.progress_mgr.record_already_has()
                    continue

                # 3. Recherche des candidats Instagram (jusqu'à 3)
                logger.info(
                    f"[{processed_in_session}] Recherche pour '{company_name}' (ID: {doc_id})..."
                )
                self.progress_mgr.record_search()

                try:
                    candidates = self.search_service.find_top_instagram_candidates(doc, max_candidates=3)
                except Exception as e:
                    logger.error(f"Erreur durant la recherche pour '{company_name}': {e}")
                    self.progress_mgr.record_error()
                    self.report_mgr.record_error(str(doc_id), company_name, "SEARCH_ERROR", str(e))
                    candidates = []

                # 4. Traitement des résultats
                if not candidates:
                    logger.info(f"  -> Aucun profil Instagram officiel trouvé pour '{company_name}'.")
                    self.progress_mgr.record_no_result()
                else:
                    # Le meilleur candidat est toujours le premier (trié par similarité décroissante)
                    best = candidates[0]
                    self.progress_mgr.record_found()

                    # Journalisation de tous les candidats trouvés avec leurs scores
                    for i, c in enumerate(candidates, 1):
                        logger.info(
                            f"  -> Candidat #{i} : {c.clean_url} "
                            f"[Confiance: {c.confidence}, Similarité: {c.similarity:.1f}%] ({c.reason})"
                        )

                    # Évaluation du meilleur candidat par rapport au seuil de confiance
                    meets_threshold = False
                    if self.confidence_threshold == "HIGH":
                        meets_threshold = (best.confidence == "HIGH")
                    elif self.confidence_threshold == "MEDIUM":
                        meets_threshold = (best.confidence in ("HIGH", "MEDIUM"))
                    else:  # LOW
                        meets_threshold = True

                    if meets_threshold:
                        # Mise à jour dans MongoDB avec tous les candidats classés par similarité
                        res = self.db_service.update_instagram_candidates(
                            doc_id=doc_id,
                            candidates=candidates,
                            company_name=company_name,
                            dry_run=self.dry_run
                        )

                        if res["status"] in ("updated", "simulated"):
                            self.progress_mgr.record_saved()
                            self.report_mgr.record_added(
                                str(doc_id),
                                company_name,
                                best.clean_url,
                                best.confidence,
                                best.reason
                            )
                            logger.info(
                                f"  -> VALIDÉ ET ENREGISTRÉ : {len(candidates)} candidat(s) "
                                f"avec score de similarité. Meilleur : {best.clean_url} "
                                f"({best.similarity:.1f}%)"
                            )

                        elif res["status"] == "already_exists":
                            self.progress_mgr.record_duplicate_avoided()
                            logger.info(f"  -> DOUBLON ÉVITÉ : {best.clean_url} est déjà présent.")

                        else:
                            self.progress_mgr.record_error()
                            self.report_mgr.record_error(
                                str(doc_id),
                                company_name,
                                "UPDATE_FAILED",
                                res.get("reason", "Échec inconnu")
                            )
                            logger.warning(f"  -> ÉCHEC DE MISE À JOUR : {res.get('reason')}")
                    else:
                        # Confiance insuffisante -> rapport de revue manuelle, aucune écriture en base
                        self.progress_mgr.record_uncertain()
                        self.report_mgr.record_uncertain(
                            str(doc_id),
                            company_name,
                            best.clean_url,
                            best.confidence,
                            best.reason
                        )
                        logger.info(
                            f"  -> CONFIANCE INSUFFISANTE ({best.confidence}, "
                            f"similarité: {best.similarity:.1f}%). "
                            "Mis en attente dans le rapport sans toucher à la base."
                        )

                # Sauvegarde régulière de la progression
                self.progress_mgr.save_progress(last_id=str(doc_id))

                # Contrôle de la limite
                if self.limit and processed_in_session >= self.limit:
                    logger.info(f"Limite atteinte ({self.limit} documents). Arrêt du lot.")
                    break

        except KeyboardInterrupt:
            logger.warning("\nInterruption détectée (Ctrl+C). Sauvegarde de la progression...")
            self._interrupted = True
        except Exception as e:
            logger.exception(f"Erreur inattendue dans la boucle de traitement : {e}")
            self.progress_mgr.record_error()
        finally:
            # Enregistrement final de progression
            self.progress_mgr.save_progress()

        # Calcul du temps écoulé et stats finales
        elapsed = time.time() - start_time
        summary = self.progress_mgr.get_summary()
        summary["session_processed"] = processed_in_session
        summary["session_duration_seconds"] = round(elapsed, 2)
        summary["speed_docs_per_minute"] = round((processed_in_session / (elapsed or 1)) * 60, 2)
        summary["dry_run"] = self.dry_run

        # Récupération du reste en base
        try:
            remaining_in_db = self.db_service.count_missing_instagram()
        except Exception:
            remaining_in_db = None

        summary["remaining_missing_instagram_in_db"] = remaining_in_db

        # Sauvegarde du bilan JSON et affichage terminal
        self.report_mgr.save_final_summary(summary)
        self.report_mgr.print_terminal_summary(summary, remaining_in_db=remaining_in_db)

        # Envoi automatique du rapport par email à l'administrateur
        if self.email_service and self.config.smtp_enabled:
            status_label = "ARRÊTÉ PAR UTILISATEUR" if self._interrupted else "SUCCÈS"
            try:
                self.email_service.send_summary_report(summary, status=status_label)
            except Exception as e:
                logger.warning(f"Impossible d'envoyer le rapport email de synthèse : {e}")

        return summary
