"""
Module d'interaction sécurisé avec la base MongoDB.
RÈGLES STRICTES DE SÉCURITÉ :
- Aucune création de base ou de collection.
- Aucune suppression de document ou de champ existant.
- Modification exclusive et atomique du champ socialAccounts.instagram.
- Projection stricte pour le traitement de volumes massifs (500 000+ docs).
- Masquage intégral des identifiants dans tous les messages d'erreur.
"""

import logging
from typing import Optional, Dict, Any, Iterator, List
from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, OperationFailure, PyMongoError

from config import AppConfig, mask_mongodb_uri

logger = logging.getLogger("instagram_automation.mongodb")


class MongoDBService:
    """Service d'accès et de mise à jour sécurisé de MongoDB."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None
        self._collection: Optional[Collection] = None

    def connect(self) -> None:
        """
        Établit la connexion à MongoDB et valide la présence stricte
        de la base et de la collection requises SANS EN CRÉER DE NOUVELLE.
        """
        try:
            logger.info(f"Connexion au serveur MongoDB : {self.config.get_masked_uri()}")
            self._client = MongoClient(
                self.config.mongodb_uri,
                serverSelectionTimeoutMS=15000,
                connectTimeoutMS=15000,
                socketTimeoutMS=20000,
                appname="InstagramAutomation"
            )

            # Test de connexion via ping
            self._client.admin.command("ping")
            logger.info("Connexion MongoDB réussie.")

            # Vérification de l'existence de la base
            database_names = self._client.list_database_names()
            if self.config.mongodb_db_name not in database_names:
                raise ValueError(
                    f"La base de données '{self.config.mongodb_db_name}' n'existe pas sur le serveur. "
                    "Conformément aux consignes, aucune base de remplacement ne sera créée."
                )

            self._db = self._client[self.config.mongodb_db_name]

            # Vérification de l'existence de la collection
            collection_names = self._db.list_collection_names()
            if self.config.mongodb_collection_name not in collection_names:
                raise ValueError(
                    f"La collection '{self.config.mongodb_collection_name}' n'existe pas dans la base. "
                    "Conformément aux consignes, aucune collection ne sera créée."
                )

            self._collection = self._db[self.config.mongodb_collection_name]
            logger.info(
                f"Collection ciblée avec succès : {self.config.mongodb_db_name}.{self.config.mongodb_collection_name}"
            )

        except ConnectionFailure as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Échec de connexion réseau au serveur MongoDB : {masked_err}")
            raise ConnectionError(f"Impossible de joindre le serveur MongoDB : {masked_err}") from None
        except OperationFailure as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Échec d'authentification ou permission insuffisante : {masked_err}")
            raise PermissionError(f"Droits MongoDB insuffisants : {masked_err}") from None
        except Exception as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Erreur d'initialisation MongoDB : {masked_err}")
            raise

    @property
    def collection(self) -> Collection:
        """Retourne la collection active ou lève une exception si non connectée."""
        if self._collection is None:
            raise RuntimeError("Le service MongoDB n'est pas connecté. Appelez connect() d'abord.")
        return self._collection

    def count_total_companies(self) -> int:
        """Retourne le nombre total de documents dans la collection."""
        return self.collection.estimated_document_count()

    def count_missing_instagram(self) -> int:
        """
        Compte le nombre de documents n'ayant pas de compte Instagram renseigné.
        """
        query = {
            "$or": [
                {"socialAccounts": {"$exists": False}},
                {"socialAccounts.instagram": {"$exists": False}},
                {"socialAccounts.instagram": None},
                {"socialAccounts.instagram": {"$size": 0}}
            ]
        }
        return self.collection.count_documents(query)

    def count_already_has_instagram(self) -> int:
        """Compte le nombre de documents ayant déjà un lien Instagram."""
        query = {
            "socialAccounts.instagram.0": {"$exists": True}
        }
        return self.collection.count_documents(query)

    def stream_companies_without_instagram(
        self,
        resume_from_id: Optional[str] = None,
        batch_size: int = 100,
        only_with_website: bool = False
    ) -> Iterator[Dict[str, Any]]:
        """
        Parcourt efficacement les documents sans charger la collection en mémoire.
        Utilise un curseur paginé par _id pour supporter des centaines de milliers de documents.
        """
        missing_ig_condition = {
            "$or": [
                {"socialAccounts": {"$exists": False}},
                {"socialAccounts.instagram": {"$exists": False}},
                {"socialAccounts.instagram": None},
                {"socialAccounts.instagram": {"$size": 0}}
            ]
        }

        query_conditions = [missing_ig_condition]

        if only_with_website:
            query_conditions.append({
                "$or": [
                    {"url": {"$regex": r"^https?://", "$options": "i"}},
                    {"domains.0": {"$exists": True}}
                ]
            })

        if resume_from_id:
            try:
                last_oid = ObjectId(resume_from_id)
                query_conditions.append({"_id": {"$gt": last_oid}})
                logger.info(f"Reprise du streaming à partir de _id > {resume_from_id}")
            except Exception as e:
                logger.warning(f"Identifiant de reprise invalide '{resume_from_id}': {e}")

        query: Dict[str, Any] = {"$and": query_conditions} if len(query_conditions) > 1 else query_conditions[0]

        # Projection ciblée : récupération STRICTEMENT des champs nécessaires
        projection = {
            "_id": 1,
            "companyName": 1,
            "domains": 1,
            "url": 1,
            "location": 1,
            "countryCode": 1,
            "socialAccounts": 1
        }

        cursor = (
            self.collection.find(query, projection=projection, no_cursor_timeout=True)
            .sort("_id", 1)
            .batch_size(batch_size)
        )

        try:
            for doc in cursor:
                yield doc
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def verify_document_structure(self, doc: Dict[str, Any]) -> tuple[bool, str]:
        """
        Vérifie que la structure du document est conforme aux attentes
        avant toute mise à jour.
        """
        if not doc or "_id" not in doc:
            return False, "Document invalide ou sans _id"

        social_accounts = doc.get("socialAccounts")
        if social_accounts is not None and not isinstance(social_accounts, dict):
            return False, f"Champ 'socialAccounts' inattendu (type: {type(social_accounts).__name__})"

        if isinstance(social_accounts, dict):
            ig = social_accounts.get("instagram")
            if ig is not None and not isinstance(ig, list):
                return False, f"Champ 'socialAccounts.instagram' inattendu (type: {type(ig).__name__})"

        return True, "Structure valide"

    def has_existing_instagram(self, doc: Dict[str, Any]) -> bool:
        """
        Vérifie si le document possède déjà au moins un lien Instagram valide.
        Ignore les liens vides ou non renseignés (ex: 'https://instagram.com/').
        """
        social_accounts = doc.get("socialAccounts")
        if not isinstance(social_accounts, dict):
            return False
        ig_list = social_accounts.get("instagram")
        if isinstance(ig_list, list) and len(ig_list) > 0:
            for item in ig_list:
                link = item.get("link", "") if isinstance(item, dict) else str(item)
                clean = link.strip().rstrip("/")
                if clean and clean not in ("https://instagram.com", "http://instagram.com", "https://www.instagram.com", "http://www.instagram.com", "instagram.com"):
                    return True
        return False

    def update_instagram_candidates(
        self,
        doc_id: Any,
        candidates: List[Any],
        company_name: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Met à jour de manière ATOMIQUE et CIBLÉE le champ socialAccounts.instagram
        avec jusqu'à 3 profils Instagram classés par similarité décroissante.
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Simulation d'ajout pour {doc_id} ({len(candidates)} liens)")
            return {
                "success": True,
                "modified": True,
                "status": "simulated",
                "reason": "Mode simulation activé (--dry-run)"
            }

        if not candidates:
            return {"success": False, "modified": False, "status": "no_candidates", "reason": "Aucun candidat fourni"}

        # Préparation des objets avec link, name et match_percentage
        # Les liens vides (sans nom d'utilisateur) sont ignorés
        INVALID_LINKS = {
            "https://instagram.com", "http://instagram.com",
            "https://www.instagram.com", "http://www.instagram.com",
            "instagram.com"
        }

        formatted_entries = []
        for c in candidates:
            url = getattr(c, "clean_url", None) or (c.get("link") if isinstance(c, dict) else None)
            user = getattr(c, "username", None) or (c.get("name") if isinstance(c, dict) else None) or company_name
            sim = getattr(c, "similarity", 0.0) if hasattr(c, "similarity") else (c.get("match_percentage", c.get("similarity", 0.0)) if isinstance(c, dict) else 0.0)

            # Ignorer les liens invalides (sans nom d'utilisateur Instagram)
            clean_url = (url or "").strip().rstrip("/")
            if not clean_url or clean_url in INVALID_LINKS:
                logger.debug(f"Lien Instagram vide ou invalide ignoré : '{url}'")
                continue

            formatted_entries.append({
                "link": url,
                "name": user,
                "match_percentage": round(float(sim), 1)
            })

        # Tri par match_percentage décroissant (meilleur match en premier)
        formatted_entries.sort(key=lambda x: x["match_percentage"], reverse=True)
        top_entries = formatted_entries[:3]

        try:
            # 1. Vérification du document existant
            fresh_doc = self.collection.find_one({"_id": doc_id}, {"socialAccounts": 1})
            if not fresh_doc:
                return {"success": False, "modified": False, "status": "not_found", "reason": "Document introuvable"}

            valid_struct, reason = self.verify_document_structure(fresh_doc)
            if not valid_struct:
                return {"success": False, "modified": False, "status": "invalid_structure", "reason": reason}

            # 2. Mise à jour atomique ciblée sur socialAccounts.instagram uniquement
            update_op = {
                "$set": {
                    "socialAccounts.instagram": top_entries
                }
            }

            result = self.collection.update_one({"_id": doc_id}, update_op)

            return {
                "success": True,
                "modified": result.modified_count > 0,
                "status": "updated",
                "reason": f"{len(top_entries)} lien(s) Instagram enregistré(s) avec match_percentage"
            }

        except OperationFailure as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Erreur d'écriture MongoDB sur {doc_id}: {masked_err}")
            return {"success": False, "modified": False, "status": "permission_error", "reason": masked_err}
        except PyMongoError as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Erreur PyMongo sur {doc_id}: {masked_err}")
            return {"success": False, "modified": False, "status": "db_error", "reason": masked_err}

    def update_instagram_link(
        self,
        doc_id: Any,
        instagram_link: str,
        company_name: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Met à jour de manière ATOMIQUE et CIBLÉE le champ socialAccounts.instagram.
        
        Règles :
        - Ciblage strict par _id.
        - Empêche l'ajout de doublons (vérification link $ne).
        - Ne touche à aucune autre clé de socialAccounts (facebook, linkedin, etc.).
        - Ne modifie aucun champ calculé.
        """
        if dry_run:
            logger.info(f"[DRY-RUN] Simulation d'ajout pour {doc_id}: {instagram_link}")
            return {
                "success": True,
                "modified": True,
                "status": "simulated",
                "reason": "Mode simulation activé (--dry-run)"
            }

        new_entry = {
            "link": instagram_link,
            "name": company_name
        }

        try:
            # 1. Vérification en lecture fraîche pour éviter toute condition de concurrence
            fresh_doc = self.collection.find_one({"_id": doc_id}, {"socialAccounts": 1})
            if not fresh_doc:
                return {
                    "success": False,
                    "modified": False,
                    "status": "not_found",
                    "reason": "Document introuvable lors de la relecture"
                }

            valid_struct, reason = self.verify_document_structure(fresh_doc)
            if not valid_struct:
                return {
                    "success": False,
                    "modified": False,
                    "status": "invalid_structure",
                    "reason": reason
                }

            social_accounts = fresh_doc.get("socialAccounts") or {}
            existing_ig = social_accounts.get("instagram") or []

            # Vérification de doublon
            for item in existing_ig:
                if isinstance(item, dict) and item.get("link") == instagram_link:
                    return {
                        "success": True,
                        "modified": False,
                        "status": "already_exists",
                        "reason": "Lien déjà présent dans le document"
                    }

            # 2. Mise à jour atomique avec filtre d'exclusion de doublon
            filter_query = {
                "_id": doc_id,
                "socialAccounts.instagram.link": {"$ne": instagram_link}
            }

            update_operation = {
                "$addToSet": {
                    "socialAccounts.instagram": new_entry
                }
            }

            result = self.collection.update_one(filter_query, update_operation)

            if result.matched_count == 0:
                # Si non matché, revérifions si c'était parce que le lien était déjà présent
                check = self.collection.find_one(
                    {"_id": doc_id, "socialAccounts.instagram.link": instagram_link},
                    {"_id": 1}
                )
                if check:
                    return {
                        "success": True,
                        "modified": False,
                        "status": "already_exists",
                        "reason": "Lien déjà présent"
                    }
                return {
                    "success": False,
                    "modified": False,
                    "status": "update_rejected",
                    "reason": "Le document n'a pas pu être mis à jour (concurrence ou condition non remplie)"
                }

            return {
                "success": True,
                "modified": result.modified_count > 0,
                "status": "updated",
                "reason": "Mise à jour réussie"
            }

        except OperationFailure as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Erreur d'écriture MongoDB sur document {doc_id}: {masked_err}")
            return {
                "success": False,
                "modified": False,
                "status": "permission_error",
                "reason": f"Erreur de permission ou d'opération MongoDB : {masked_err}"
            }
        except PyMongoError as e:
            masked_err = mask_mongodb_uri(str(e))
            logger.error(f"Erreur PyMongo sur document {doc_id}: {masked_err}")
            return {
                "success": False,
                "modified": False,
                "status": "db_error",
                "reason": f"Erreur base de données : {masked_err}"
            }

    def close(self) -> None:
        """Ferme proprement la connexion MongoDB."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            self._collection = None
            logger.info("Connexion MongoDB fermée.")
