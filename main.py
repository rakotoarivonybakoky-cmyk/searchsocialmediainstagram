"""
Point d'entrée principal (CLI) du programme d'automatisation des liens Instagram.
Permet d'exécuter des tests de connexion, des simulations (--dry-run),
des traitements par lots contrôlés (--limit) et la reprise après interruption (--resume).
"""

import sys
import argparse
import logging
from typing import Optional

from config import load_config, AppConfig, mask_mongodb_uri
from mongodb_service import MongoDBService
from search_service import SearchService
from progress_manager import ProgressManager
from report_manager import ReportManager
from processor import AutomationProcessor
from email_service import EmailService


def setup_logging(config: AppConfig) -> None:
    """Configure les gestionnaires de logs (console et fichier local)."""
    log_file = config.logs_dir / "app.log"
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Handler fichier
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Nettoyage des handlers existants
    root_logger.handlers = []
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Réduction de la verbosité des bibliothèques tierces
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)


def handle_test_connection(config: AppConfig) -> int:
    """Vérifie la connexion en lecture seule à MongoDB."""
    print("\n[TEST CONNEXION MONGODB]")
    print(f"Serveur ciblé : {config.get_masked_uri()}")
    print(f"Base ciblée   : {config.mongodb_db_name}")
    print(f"Collection    : {config.mongodb_collection_name}")
    print("-" * 50)

    db_service = MongoDBService(config)
    try:
        db_service.connect()
        total = db_service.count_total_companies()
        missing = db_service.count_missing_instagram()
        with_ig = db_service.count_already_has_instagram()

        print("Connexion RÉUSSIE !")
        print(f" - Nombre total d'entreprises        : {total:,}")
        print(f" - Entreprises avec compte Instagram  : {with_ig:,}")
        print(f" - Entreprises SANS compte Instagram : {missing:,}")
        print("-" * 50)
        print("La base et la collection sont conformes et prêtes.\n")
        return 0
    except Exception as e:
        print(f"ÉCHEC DE CONNEXION : {e}")
        return 1
    finally:
        db_service.close()


def handle_status(config: AppConfig) -> int:
    """Affiche l'état d'avancement actuel enregistré localement."""
    print("\n[STATUT DU TRAITEMENT]")
    progress_mgr = ProgressManager(config.progress_file)
    state = progress_mgr.load_progress()

    if not state:
        print("Aucun fichier de progression local trouvé (aucun traitement démarré).")
    else:
        print(f"Dernier _id traité : {state.get('last_processed_id')}")
        print(f"Total examinés     : {state.get('total_examined')}")
        print(f"Déjà avec IG       : {state.get('already_had_ig')}")
        print(f"Recherches faites  : {state.get('searches_performed')}")
        print(f"Liens trouvés      : {state.get('links_found')}")
        print(f"Liens enregistrés  : {state.get('links_saved')}")
        print(f"Doublons évités    : {state.get('duplicates_avoided')}")
        print(f"Sans résultat      : {state.get('no_results')}")
        print(f"Incertains (revue) : {state.get('uncertain_results')}")
        print(f"Erreurs            : {state.get('errors')}")
        print(f"Terminé            : {state.get('completed')}")
        print(f"Dernière maj       : {state.get('last_update_time')}")

    print("\nInterrogation de l'état actuel dans MongoDB...")
    db_service = MongoDBService(config)
    try:
        db_service.connect()
        missing = db_service.count_missing_instagram()
        print(f"Nombre d'entreprises nécessitant encore une recherche : {missing:,}\n")
    except Exception as e:
        print(f"Impossible de vérifier MongoDB : {e}\n")
    finally:
        db_service.close()

    return 0


def handle_test_smtp(config: AppConfig) -> int:
    """Envoie un email de test pour valider la configuration SMTP sans toucher à MongoDB."""
    print("\n" + "=" * 50)
    print("      TEST DE LA CONFIGURATION SMTP (GMAIL)      ")
    print("=" * 50)
    print(f"  SMTP Activé      : {'OUI' if config.smtp_enabled else 'NON (SMTP_ENABLED=false)'}")
    print(f"  Serveur Hôte     : {config.smtp_host}")
    print(f"  Port             : {config.smtp_port}")
    print(f"  Chiffrement      : {'TLS (STARTTLS)' if config.smtp_use_tls else ('SSL direct' if config.smtp_use_ssl else 'Aucun')}")
    print(f"  Expéditeur       : {config.smtp_user or '<Non configuré>'}")
    print(f"  Destinataire     : {config.admin_email or '<Non configuré>'}")
    print("-" * 50)

    if not config.smtp_enabled:
        print("[INFO] SMTP est désactivé dans votre .env (SMTP_ENABLED=false).")
        print("Pour l'activer, configurez SMTP_ENABLED=true dans votre fichier .env.\n")
        return 0

    if not config.smtp_user or not config.smtp_password or not config.admin_email:
        print("[ERREUR] Paramètres manquants dans .env (SMTP_USER, SMTP_PASSWORD ou ADMIN_EMAIL).")
        print("Veuillez renseigner vos identifiants Gmail dans le fichier .env avant de tester.\n")
        return 1

    print("Tentative de connexion et d'envoi d'un email de test...")
    email_service = EmailService(config)
    success = email_service.send_email(
        subject="[TEST SMTP] Pipeline Automatisation Instagram",
        text_body=(
            "Bonjour,\n\n"
            "Ceci est un email de test confirmant que la configuration SMTP de votre "
            "projet d'automatisation des liens Instagram est 100% opérationnelle.\n\n"
            "Les futurs rapports d'automatisation et alertes d'erreurs seront correctement reçus.\n"
        ),
        html_body=(
            "<div style='font-family: Arial, sans-serif; padding: 20px; border: 1px solid #2ea44f; border-radius: 8px;'>"
            "<h2 style='color: #2ea44f; margin-top: 0;'>✔ Test SMTP Réussi</h2>"
            "<p>Ce message confirme que la connexion SMTP vers Gmail fonctionne parfaitement.</p>"
            "<p>Votre pipeline d'automatisation Instagram est prêt pour l'envoi automatique de rapports.</p>"
            "</div>"
        )
    )

    if success:
        print(f"SUCCÈS : L'email de test a été envoyé avec succès à '{config.admin_email}'.\n")
        return 0
    else:
        print("ÉCHEC : L'envoi de l'email de test a échoué. Vérifiez vos identifiants ou les logs.\n")
        return 1


def main() -> int:
    """Fonction principale du programme."""
    parser = argparse.ArgumentParser(
        description="Automatisation de la recherche et de l'ajout des liens Instagram officiels dans MongoDB.",
        formatter_class=argparse.RawTextHelpFormatter
    )

    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Teste la connexion MongoDB en lecture seule et affiche les compteurs."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Affiche l'état actuel de progression et les statistiques."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation : recherche et valide les profils SANS modifier MongoDB."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limite le nombre d'entreprises à traiter durant cette exécution (ex: --limit 50)."
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reprend le traitement là où il s'était arrêté lors de la session précédente."
    )
    parser.add_argument(
        "--only-with-website",
        action="store_true",
        help="Cible exclusivement les entreprises qui ont un site web déclaré dans MongoDB."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Taille du lot curseur MongoDB (défaut : 100)."
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["hybrid", "website_scraper", "duckduckgo", "google", "serpapi"],
        help="Force le fournisseur de recherche (écrase la valeur de .env)."
    )
    parser.add_argument(
        "--confidence-threshold",
        type=str,
        choices=["HIGH", "MEDIUM", "LOW"],
        help="Seuil de confiance minimum pour écrire dans MongoDB (défaut : HIGH)."
    )
    parser.add_argument(
        "--test-smtp",
        action="store_true",
        help="Teste la configuration et l'envoi d'un email SMTP sans modifier MongoDB."
    )

    args = parser.parse_args()

    # Chargement de la configuration
    try:
        config = load_config()
        config.validate()
    except Exception as e:
        print(f"\n[ERREUR DE CONFIGURATION] : {e}\n")
        return 1

    setup_logging(config)
    logger = logging.getLogger("instagram_automation.main")

    # Commandes utilitaires isolées
    if args.test_connection:
        return handle_test_connection(config)

    if args.status:
        return handle_status(config)

    if args.test_smtp:
        return handle_test_smtp(config)

    # Initialisation des services pour le traitement
    provider = args.provider or config.search_provider
    confidence = args.confidence_threshold or config.confidence_threshold
    email_service = EmailService(config)

    print("\n" + "=" * 68)
    print("  LANCEMENT DU TRAITEMENT D'ENRICHISSEMENT INSTAGRAM DANS MONGODB   ")
    print("=" * 68)
    print(f"  Mode Dry-Run (Simulation) : {'OUI (Aucune écriture en base)' if args.dry_run else 'NON (Écriture réelle autorisée)'}")
    print(f"  Limite d'entreprises      : {args.limit if args.limit else 'Aucune (traitement continu)'}")
    print(f"  Reprise après arrêt       : {'OUI' if args.resume else 'NON (départ depuis le début)'}")
    print(f"  Fournisseur de recherche  : {provider}")
    print(f"  Seuil de confiance        : {confidence}")
    print(f"  Notifications SMTP        : {'ACTIVÉES (' + config.admin_email + ')' if config.smtp_enabled and config.admin_email else ('DÉSACTIVÉES' if not config.smtp_enabled else 'INCOMPLÈTES')}")
    print("=" * 68 + "\n")

    db_service = MongoDBService(config)
    try:
        db_service.connect()
    except Exception as e:
        logger.error(f"Arrêt immédiat : impossible de se connecter à la base : {e}")
        email_service.send_error_alert(
            error_title="Échec de connexion MongoDB",
            error_details=f"Impossible d'établir la connexion à la base MongoDB '{config.mongodb_db_name}' ({config.get_masked_uri()}).\nErreur : {e}",
            context="Initialisation de db_service.connect() dans main.py"
        )
        return 1

    search_service = SearchService(config, provider=provider)
    progress_manager = ProgressManager(config.progress_file)
    report_manager = ReportManager(config)

    only_with_web = args.only_with_website if args.only_with_website else (provider == "website_scraper")

    processor = AutomationProcessor(
        config=config,
        mongodb_service=db_service,
        search_service=search_service,
        progress_manager=progress_manager,
        report_manager=report_manager,
        dry_run=args.dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
        resume=args.resume,
        confidence_threshold=confidence,
        only_with_website=only_with_web,
        email_service=email_service
    )

    try:
        processor.run()
        return 0
    except Exception as e:
        logger.exception(f"Erreur fatale d'exécution : {e}")
        email_service.send_error_alert(
            error_title="Erreur fatale du pipeline d'automatisation",
            error_details=f"Une exception inattendue a interrompu le traitement : {e}",
            context="Boucle principale processor.run() dans main.py"
        )
        return 1
    finally:
        db_service.close()


if __name__ == "__main__":
    sys.exit(main())
