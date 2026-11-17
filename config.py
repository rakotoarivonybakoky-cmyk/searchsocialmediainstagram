"""
Module de configuration centralisée de l'application.
Charge les variables d'environnement depuis le fichier .env et expose
des paramètres validés et sécurisés.
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Détermination des répertoires de base
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# Chargement du fichier .env
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    load_dotenv()  # Recherche par défaut

REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
PROGRESS_FILE = LOGS_DIR / "progress.json"

# Création assurée des répertoires locaux
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def mask_mongodb_uri(uri: str) -> str:
    """
    Masque les identifiants (nom d'utilisateur et mot de passe) dans une URI MongoDB.
    Empêche toute fuite de secret dans les logs ou messages d'erreur.
    """
    if not uri:
        return "<vide>"
    # Format standard : mongodb://user:pass@host:port/...
    pattern = r"(mongodb(?:\+srv)?:\/\/)([^:@\s]+):([^@\s]+)@"
    return re.sub(pattern, r"\1***:***@", uri)


@dataclass(frozen=True)
class AppConfig:
    """Classe immuable contenant l'ensemble de la configuration active."""
    # MongoDB
    mongodb_uri: str
    mongodb_db_name: str
    mongodb_collection_name: str

    # Recherche
    search_provider: str
    google_api_key: Optional[str]
    google_cse_id: Optional[str]
    serpapi_key: Optional[str]

    # Débit et temporisations
    rate_limit_delay: float
    request_timeout: int
    max_retries: int
    confidence_threshold: str
    log_level: str

    # Chemins
    reports_dir: Path
    logs_dir: Path
    progress_file: Path

    # Configuration SMTP & Notifications
    smtp_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    admin_email: Optional[str] = None

    def get_masked_uri(self) -> str:
        """Retourne l'URI avec identifiants masqués."""
        return mask_mongodb_uri(self.mongodb_uri)

    def validate(self) -> None:
        """Valide la présence des configurations obligatoires."""
        if not self.mongodb_uri:
            raise ValueError(
                "L'URI MongoDB (MONGODB_URI) est manquante dans le fichier .env. "
                "Veuillez configurer .env avant de lancer le programme."
            )
        if self.mongodb_db_name != "leadfeeder-social-accounts":
            raise ValueError(
                f"Sécurité : la base doit être 'leadfeeder-social-accounts', or '{self.mongodb_db_name}' est configuré."
            )
        if self.mongodb_collection_name != "adding_social_accounts":
            raise ValueError(
                f"Sécurité : la collection doit être 'adding_social_accounts', or '{self.mongodb_collection_name}' est configuré."
            )


def load_config() -> AppConfig:
    """Instancie et valide la configuration de l'application."""
    uri = os.getenv("MONGODB_URI", "").strip()
    db_name = os.getenv("MONGODB_DB_NAME", "leadfeeder-social-accounts").strip()
    collection_name = os.getenv("MONGODB_COLLECTION_NAME", "adding_social_accounts").strip()

    search_provider = os.getenv("SEARCH_PROVIDER", "hybrid").strip().lower()
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip() or None
    google_cse_id = os.getenv("GOOGLE_CSE_ID", "").strip() or None
    serpapi_key = os.getenv("SERPAPI_KEY", "").strip() or None

    try:
        rate_limit_delay = float(os.getenv("RATE_LIMIT_DELAY", "1.0"))
    except ValueError:
        rate_limit_delay = 1.0

    try:
        request_timeout = int(os.getenv("REQUEST_TIMEOUT", "8"))
    except ValueError:
        request_timeout = 8

    try:
        max_retries = int(os.getenv("MAX_RETRIES", "2"))
    except ValueError:
        max_retries = 2

    confidence_threshold = os.getenv("CONFIDENCE_THRESHOLD", "HIGH").strip().upper()
    if confidence_threshold not in ("HIGH", "MEDIUM", "LOW"):
        confidence_threshold = "HIGH"

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    # Configuration SMTP
    smtp_enabled = os.getenv("SMTP_ENABLED", "false").strip().lower() in ("true", "1", "yes")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("true", "1", "yes")
    smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() in ("true", "1", "yes")
    smtp_user = os.getenv("SMTP_USER", "").strip() or None
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip() or None
    smtp_from = os.getenv("SMTP_FROM", "").strip() or None
    admin_email = os.getenv("ADMIN_EMAIL", "").strip() or None

    cfg = AppConfig(
        mongodb_uri=uri,
        mongodb_db_name=db_name,
        mongodb_collection_name=collection_name,
        search_provider=search_provider,
        google_api_key=google_api_key,
        google_cse_id=google_cse_id,
        serpapi_key=serpapi_key,
        rate_limit_delay=rate_limit_delay,
        request_timeout=request_timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        log_level=log_level,
        reports_dir=REPORTS_DIR,
        logs_dir=LOGS_DIR,
        progress_file=PROGRESS_FILE,
        smtp_enabled=smtp_enabled,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_use_tls=smtp_use_tls,
        smtp_use_ssl=smtp_use_ssl,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        admin_email=admin_email,
    )
    return cfg
