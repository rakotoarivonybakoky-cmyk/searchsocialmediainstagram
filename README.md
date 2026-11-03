# 🚀 Automatisation de l'enrichissement des liens Instagram dans MongoDB

Projet Python professionnel conçu pour enrichir automatiquement et en toute sécurité une base de données de plusieurs centaines de milliers d'entreprises (environ 500 000 documents) avec leurs profils Instagram officiels vérifiés.

---

## 📋 Table des matières

1. [Architecture et Principes de Sécurité](#-architecture-et-principes-de-sécurité)
2. [Structure du Projet](#-structure-du-projet)
3. [Prérequis](#-prérequis)
4. [Installation sous Windows (PowerShell / VS Code)](#-installation-sous-windows-powershell--vs-code)
5. [Configuration du fichier `.env`](#-configuration-du-fichier-env)
6. [Fournisseurs de Recherche (Gratuit & APIs)](#-fournisseurs-de-recherche-gratuit--apis)
7. [Guide des Commandes d'Exécution](#-guide-des-commandes-dexécution)
   - [7.1. Test de connexion en lecture seule](#71-test-de-connexion-en-lecture-seule)
   - [7.2. Simulation sans écriture (`--dry-run`)](#72-simulation-sans-écriture---dry-run)
   - [7.3. Traitement d'un petit lot de test](#73-traitement-dun-petit-lot-de-test)
   - [7.4. Reprise après interruption (`--resume`)](#74-reprise-après-interruption---resume)
   - [7.5. Consultation de l'état d'avancement (`--status`)](#75-consultation-de-létat-davancement---status)
   - [7.6. Lancement du traitement à grande échelle](#76-lancement-du-traitement-à-grande-échelle)
8. [Gestion des Niveaux de Confiance et Rapports](#-gestion-des-niveaux-de-confiance-et-rapports)
9. [Exécution des Tests Unitaires](#-exécution-des-tests-unitaires)

---

## 🔒 Architecture et Principes de Sécurité

> [!IMPORTANT]
> **Respect absolu de la base de données partagée de l'encadreur :**
> - **Aucune création** de nouvelle base de données ou de nouvelle collection.
> - **Aucune suppression** de documents, de collections ou de champs existants.
> - **Modification exclusive et ciblée** : seul le champ `socialAccounts.instagram` est enrichi.
> - **Préservation intégrale** des autres réseaux sociaux (`facebook`, `linkedin`, `twitter`, etc.) et de tous les champs métier.
> - **Mise à jour atomique** avec `$addToSet` et clause d'exclusion (`$ne`) pour éliminer tout risque de doublon.
> - **Masquage systématique des secrets** : l'URI et les mots de passe ne sont jamais affichés dans les logs ou les rapports.
> - **Gestion du volume (500 000+ docs)** : streaming par curseur paginé et projection limitée pour éviter toute saturation mémoire.

---

## 📁 Structure du Projet

```text
F:\instagram_social_accounts_automation\
│
├── .env                              # Identifiants réels (exclus de git)
├── .env.example                      # Modèle de configuration avec explications
├── .gitignore                        # Protection contre les fuites de secrets/fichiers temporaires
├── config.py                         # Validation de configuration & masquage sécurisé
├── instagram_validator.py            # Normalisation des URLs, regex, filtrage & scoring de confiance
├── mongodb_service.py                # Accès sécurisé, streaming par lots & mises à jour atomiques
├── search_service.py                 # Extraction site officiel + DuckDuckGo / Google CSE / SerpApi
├── progress_manager.py               # Sauvegarde atomique locale et reprise sur incident
├── report_manager.py                 # Génération des CSV/JSON de suivi et bilans finaux
├── processor.py                      # Orchestration du flux, gestion de Ctrl+C et seuils
├── main.py                           # Interface en ligne de commande (CLI)
├── requirements.txt                  # Dépendances Python requises
├── README.md                         # Documentation complète
│
├── reports/                          # Rapports générés (CSV des liens ajoutés, incertains, erreurs)
├── logs/                             # Fichiers de logs (app.log) et état (progress.json)
└── tests/                            # Suite de tests unitaires avec données mockées
    ├── test_validator.py             # Validation URL, handles, mots réservés, scores
    ├── test_mongodb_service.py       # Sécurité des requêtes, préservation des champs, anti-doublon
    ├── test_progress_manager.py      # Persistance atomique et reprise
    └── test_processor.py             # Intégration globale, dry-run et seuils de confiance
```

---

## 💻 Prérequis

- **Système** : Windows 10 ou 11
- **Python** : Python 3.10 ou supérieur (testé avec Python 3.12)
- **Éditeur recommandé** : Visual Studio Code avec terminal PowerShell

---

## 🛠️ Installation sous Windows (PowerShell / VS Code)

### Étape 1 : Ouvrir le projet dans VS Code

1. Lancez **VS Code**.
2. Allez dans le menu `Fichier` > `Ouvrir le dossier...` (ou `Ctrl+K Ctrl+O`).
3. Sélectionnez le dossier : `F:\instagram_social_accounts_automation`.
4. Ouvrez un terminal intégré PowerShell (`Terminal` > `Nouveau terminal` ou `Ctrl+Shift+ù`).

### Étape 2 : Créer et activer l'environnement virtuel Python

Dans le terminal PowerShell :

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

*(Si PowerShell bloque l'exécution des scripts avec une erreur d'autorisation, tapez : `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` puis réessayez).*

### Étape 3 : Installer les dépendances

```powershell
pip install -r requirements.txt
```

---

## ⚙️ Configuration du fichier `.env`

Le fichier `.env` est déjà configuré dans le projet avec l'URI fournie par l'encadreur :

```env
MONGODB_URI=mongodb://adding_social_accounts_user:45dfgd454gf26zeerf@57.129.18.234:27017/leadfeeder-social-accounts?authSource=leadfeeder-social-accounts
MONGODB_DB_NAME=leadfeeder-social-accounts
MONGODB_COLLECTION_NAME=adding_social_accounts

# Fournisseur de recherche : hybrid (site officiel + DuckDuckGo)
SEARCH_PROVIDER=hybrid
GOOGLE_API_KEY=
GOOGLE_CSE_ID=
SERPAPI_KEY=

# Performances & Prudence
RATE_LIMIT_DELAY=1.0
REQUEST_TIMEOUT=8
MAX_RETRIES=2
CONFIDENCE_THRESHOLD=HIGH
LOG_LEVEL=INFO
```

---

## 🔍 Fournisseurs de Recherche (Gratuit & APIs)

Le système propose plusieurs modes configurables via `SEARCH_PROVIDER` ou via l'option `--provider` :

| Fournisseur | Coût / Clé API requise | Fonctionnement & Avantages |
| :--- | :--- | :--- |
| **`hybrid`** *(Recommandé)* | **100% Gratuit** / Aucune clé requise | 1. Analyse d'abord le site web officiel de l'entreprise (`url`/`domains`) pour extraire le lien Instagram officiel publié par l'entreprise (Confiance maximale `HIGH`).<br>2. Si absent du site web, effectue une recherche DuckDuckGo. |
| **`website_scraper`** | **100% Gratuit** / Aucune clé requise | Analyse **uniquement** le site web de l'entreprise. 0% de faux positifs, très rapide et totalement sécurisé. |
| **`duckduckgo`** | **100% Gratuit** / Aucune clé requise | Recherche automatisée sur le moteur DuckDuckGo. |
| **`google`** | Clé API payante ou quota gratuit | Nécessite `GOOGLE_API_KEY` et `GOOGLE_CSE_ID`. Obtenable sur la [console Google Cloud](https://developers.google.com/custom-search/v1/overview). |
| **`serpapi`** | Clé API payante ou quota gratuit | Nécessite `SERPAPI_KEY`. Obtenable sur [SerpApi.com](https://serpapi.com/). |

---

## 🎯 Guide des Commandes d'Exécution

> Toutes les commandes ci-dessous doivent être exécutées dans PowerShell avec le venv activé (`.\venv\Scripts\Activate.ps1`).

### 7.1. Test de connexion en lecture seule

Vérifie la liaison réseau avec MongoDB, l'existence de la base et de la collection, et compte les documents sans effectuer la moindre modification :

```powershell
python main.py --test-connection
```

*Exemple de sortie :*
```text
[TEST CONNEXION MONGODB]
Serveur ciblé : mongodb://***:***@57.129.18.234:27017/...
Connexion RÉUSSIE !
 - Nombre total d'entreprises        : 504,120
 - Entreprises avec compte Instagram : 82,340
 - Entreprises SANS compte Instagram : 421,780
```

### 7.2. Simulation sans écriture (`--dry-run`)

Effectue la recherche complète pour 10 entreprises, calcule la confiance, affiche les résultats mais **n'écrit absolument rien dans MongoDB** :

```powershell
python main.py --dry-run --limit 10
```

### 7.3. Traitement d'un petit lot de test

Après validation de la simulation, enrichissez un premier lot réel de 20 entreprises :

```powershell
python main.py --limit 20
```

Seuls les profils dont le score de confiance est **HIGH** (certifiés) seront ajoutés dans `socialAccounts.instagram`.

### 7.4. Reprise après interruption (`--resume`)

Si vous interrompez le traitement (`Ctrl+C`, arrêt machine ou incident réseau), l'avancement est sauvegardé en continu dans `logs/progress.json`. Pour reprendre exactement là où vous vous étiez arrêté :

```powershell
python main.py --resume
```

Vous pouvez combiner `--resume` et `--limit` (par exemple pour traiter 100 nouvelles entreprises à la suite de la dernière exécution) :

```powershell
python main.py --resume --limit 100
```

### 7.5. Consultation de l'état d'avancement (`--status`)

Pour inspecter l'historique et les statistiques à tout moment :

```powershell
python main.py --status
```

### 7.6. Lancement du traitement à grande échelle

Lorsque vous êtes prêt à laisser tourner le programme sur un volume plus important :

```powershell
python main.py --resume --batch-size 150
```

---

## 📊 Gestion des Niveaux de Confiance et Rapports

Chaque profil découvert est évalué selon des critères stricts :

- **`HIGH`** :
  - Lien extrait directement depuis le code source du site officiel de l'entreprise (`url` ou `domains`).
  - Ou correspondance forte et indiscutable entre le nom de domaine officiel, le nom de l'entreprise et le handle Instagram.
  - **Action : Ajout automatique dans `socialAccounts.instagram`.**

- **`MEDIUM`** :
  - Mots-clés concordants trouvés par moteur de recherche mais sans confirmation par le site officiel.
  - **Action : Non ajouté à la base MongoDB.** Enregistré dans `reports/uncertain_to_review_<date>.csv` pour revue humaine.

- **`LOW`** :
  - Profil ambigu, nom trop court ou risque d'homonyme.
  - **Action : Rejeté.** Enregistré dans `reports/uncertain_to_review_<date>.csv`.

### Fichiers de rapports générés dans `reports/` :

1. `high_confidence_added_<date>.csv` : Liste des profils certifiés effectivement ajoutés dans MongoDB.
2. `uncertain_to_review_<date>.csv` : Liste des profils ambigus écartés par sécurité avec le motif de rejet.
3. `errors_<date>.csv` : Journal des anomalies de structure ou incidents réseau par entreprise.
4. `summary_<date>.json` : Bilan statistique complet (vitesses, compteurs, horodatages).

---

## 🧪 Exécution des Tests Unitaires

Le projet inclut une suite complète de tests unitaires mockés protégeant la base contre toute manipulation erronée.

Pour lancer tous les tests :

```powershell
pytest -v
```

Les tests valident automatiquement :
- ✅ La conformité syntaxique des URLs Instagram et le rejet des URLs système (`/p/`, `/reels/`, etc.).
- ✅ Le calcul des scores de confiance.
- ✅ La non-altération des autres comptes sociaux (`facebook`, etc.).
- ✅ L'application du filtre anti-doublon (`$ne`).
- ✅ La détection des documents corrompus ou sans `_id`.
- ✅ Le bon fonctionnement du mode `--dry-run`.
- ✅ La persistance atomique de `progress.json`.
