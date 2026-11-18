"""
Module de recherche automatisée des liens Instagram.
Fournit plusieurs stratégies complémentaires :
1. Extraction directe depuis le site officiel de l'entreprise (domains / url).
2. Recherche par moteur de recherche (DuckDuckGo, Google CSE, SerpApi).
3. Mode hybride combinant les deux pour maximiser la gratuité et la précision.
Permet d'extraire jusqu'à 3 profils classés par similarité décroissante.
"""

import time
import logging
import re
from typing import Optional, List, Dict, Any, Set
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from instagram_validator import (
    clean_instagram_url,
    validate_instagram_candidate,
    calculate_similarity,
    ValidationResult,
    analyze_bio_for_business
)
from config import AppConfig

logger = logging.getLogger("instagram_automation.search")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr,fr-FR;q=0.9,en;q=0.8",
}


class SearchService:
    """Service centralisant la découverte et l'extraction de liens Instagram."""

    def __init__(self, config: AppConfig, provider: Optional[str] = None):
        self.config = config
        self.provider = (provider or config.search_provider).lower()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def extract_from_official_website(
        self,
        urls: List[str],
        company_name: str
    ) -> List[ValidationResult]:
        """
        Extrait tous les profils Instagram trouvés sur le site web officiel de l'entreprise.
        """
        results: List[ValidationResult] = []
        seen_urls: Set[str] = set()

        for raw_url in urls:
            if not raw_url or not isinstance(raw_url, str):
                continue

            raw_url = raw_url.strip()
            if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
                target_url = f"https://{raw_url}"
            else:
                target_url = raw_url

            try:
                logger.debug(f"Inspection du site web de l'entreprise : {target_url}")
                response = self.session.get(
                    target_url,
                    timeout=self.config.request_timeout,
                    verify=False,
                    allow_redirects=True
                )

                if response.status_code != 200 or not response.text:
                    continue

                soup = BeautifulSoup(response.text, "html.parser")

                # 1. Balises <a> contenant instagram.com
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    if "instagram.com" in href.lower():
                        cleaned = clean_instagram_url(href)
                        if cleaned and cleaned not in seen_urls:
                            seen_urls.add(cleaned)
                            val_res = validate_instagram_candidate(
                                candidate_url=cleaned,
                                company_name=company_name,
                                domain=target_url,
                                source="official_website"
                            )
                            if val_res.is_valid:
                                results.append(val_res)

                # 2. Recherche textuelle / regex
                instagram_regex = r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.-]+/?(?=['\"\s,])"
                matches = re.findall(instagram_regex, response.text)
                for match in matches:
                    cleaned = clean_instagram_url(match)
                    if cleaned and cleaned not in seen_urls:
                        seen_urls.add(cleaned)
                        val_res = validate_instagram_candidate(
                            candidate_url=cleaned,
                            company_name=company_name,
                            domain=target_url,
                            source="official_website"
                        )
                        if val_res.is_valid:
                            results.append(val_res)

            except Exception as e:
                logger.debug(f"Impossible d'analyser le site '{target_url}': {e}")
                continue

        return results

    def _fetch_instagram_profile_meta(self, instagram_url: str) -> dict:
        """
        Tente de récupérer les métadonnées publiques d'un profil Instagram
        via les balises <meta> de sa page HTML publique (sans connexion requise).

        Extrait :
          - 'display_name' : nom affiché sur le profil (og:title)
          - 'bio'          : biographie du compte (og:description)

        Retourne un dict non vide si la page est accessible, sinon {} (neutre).
        Le score textuel est conservé intact si Instagram est inaccessible.
        """
        try:
            resp = self.session.get(
                instagram_url,
                timeout=6,
                verify=False,
                allow_redirects=True
            )
            if resp.status_code != 200 or not resp.text:
                return {}

            soup = BeautifulSoup(resp.text, "html.parser")
            display_name = ""
            bio = ""

            # og:title → "Nom Affiché (@username) • Instagram photos et vidéos"
            title_tag = soup.find("meta", property="og:title")
            if title_tag and title_tag.get("content"):
                title_content = title_tag["content"]
                name_match = re.match(r"^(.+?)\s*\(@", title_content)
                if name_match:
                    display_name = name_match.group(1).strip()
                else:
                    display_name = title_content.split("•")[0].strip()

            # og:description → contient généralement la biographie du compte
            desc_tag = soup.find("meta", property="og:description")
            if desc_tag and desc_tag.get("content"):
                bio = desc_tag["content"]

            if not display_name and not bio:
                return {}

            logger.debug(
                f"Meta Instagram récupérées pour {instagram_url} : "
                f"nom='{display_name}', bio='{bio[:60]}...'"
            )
            return {"display_name": display_name, "bio": bio}

        except Exception as e:
            logger.debug(f"Profil Instagram inaccessible '{instagram_url}': {e}")
            return {}

    def search_duckduckgo_candidates(
        self,
        company_name: str,
        location: Optional[str] = None,
        country_code: Optional[str] = None,
        max_results: int = 5
    ) -> List[str]:
        """
        Recherche plusieurs profils candidats via DuckDuckGo.
        Effectue deux requêtes :
        1. Une requête précise avec mots-clés business (officiel, entreprise, company)
        2. Une requête générale en fallback si la première ne donne pas de résultats
        """
        candidates: List[str] = []
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    from ddgs import DDGS
                except ImportError:
                    from duckduckgo_search import DDGS

            geo = location or country_code or ""

            # Requête 1 : précise avec mots-clés business pour éviter les profils personnels
            business_keywords = "officiel OR official OR entreprise OR company OR business"
            query_parts_precise = [f'"{company_name}"', "site:instagram.com", business_keywords]
            if geo:
                query_parts_precise.append(geo)
            query_precise = " ".join(query_parts_precise)
            logger.debug(f"Requête DuckDuckGo précise : {query_precise}")

            seen: set = set()
            with DDGS() as ddgs:
                results_precise = list(ddgs.text(query_precise, max_results=max_results))

            for r in results_precise:
                href = r.get("href") or r.get("link", "")
                if "instagram.com" in href.lower():
                    cleaned = clean_instagram_url(href)
                    if cleaned and cleaned not in seen:
                        seen.add(cleaned)
                        candidates.append(cleaned)

            # Requête 2 : générale en fallback si la requête précise n'a rien trouvé
            if not candidates:
                query_parts_general = [f'"{company_name}"', "site:instagram.com"]
                if geo:
                    query_parts_general.append(geo)
                query_general = " ".join(query_parts_general)
                logger.debug(f"Requête DuckDuckGo générale (fallback) : {query_general}")

                with DDGS() as ddgs:
                    results_general = list(ddgs.text(query_general, max_results=max_results))

                for r in results_general:
                    href = r.get("href") or r.get("link", "")
                    if "instagram.com" in href.lower():
                        cleaned = clean_instagram_url(href)
                        if cleaned and cleaned not in seen:
                            seen.add(cleaned)
                            candidates.append(cleaned)

        except Exception as e:
            logger.warning(f"Erreur lors de la recherche DuckDuckGo pour '{company_name}': {e}")

        return candidates

    def search_google_custom_search_candidates(
        self,
        company_name: str,
        location: Optional[str] = None,
        country_code: Optional[str] = None
    ) -> List[str]:
        """Recherche via l'API Google Custom Search."""
        if not self.config.google_api_key or not self.config.google_cse_id:
            return []

        candidates: List[str] = []
        query = f'"{company_name}" site:instagram.com'
        if location:
            query += f" {location}"

        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": self.config.google_api_key,
            "cx": self.config.google_cse_id,
            "q": query,
            "num": 5
        }

        try:
            resp = self.session.get(url, params=params, timeout=self.config.request_timeout)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    link = item.get("link", "")
                    cleaned = clean_instagram_url(link)
                    if cleaned and cleaned not in candidates:
                        candidates.append(cleaned)
        except Exception as e:
            logger.warning(f"Erreur Google CSE: {e}")

        return candidates

    def search_serpapi_candidates(
        self,
        company_name: str,
        location: Optional[str] = None,
        country_code: Optional[str] = None
    ) -> List[str]:
        """Recherche via SerpApi."""
        if not self.config.serpapi_key:
            return []

        candidates: List[str] = []
        query = f'"{company_name}" site:instagram.com'
        if location:
            query += f" {location}"

        url = "https://serpapi.com/search.json"
        params = {
            "engine": "google",
            "q": query,
            "api_key": self.config.serpapi_key,
            "num": 5
        }

        try:
            resp = self.session.get(url, params=params, timeout=self.config.request_timeout)
            if resp.status_code == 200:
                data = resp.json()
                for res in data.get("organic_results", []):
                    link = res.get("link", "")
                    cleaned = clean_instagram_url(link)
                    if cleaned and cleaned not in candidates:
                        candidates.append(cleaned)
        except Exception as e:
            logger.warning(f"Erreur SerpApi: {e}")

        return candidates

    def find_top_instagram_candidates(
        self,
        company_data: Dict[str, Any],
        max_candidates: int = 3
    ) -> List[ValidationResult]:
        """
        Trouve jusqu'à 3 profils Instagram candidats et les trie par pourcentage
        de similarité multi-rubriques décroissant (du plus pertinent au moins pertinent).
        Prend en compte : companyName, url, domains, location, countryCode, description, keywords.
        """
        company_name = (company_data.get("companyName") or company_data.get("tradeName") or "").strip()
        if not company_name:
            return []

        location = company_data.get("location") or None
        country_code = company_data.get("countryCode") or None
        description = company_data.get("description") or None
        keywords_raw = company_data.get("keywords")
        keywords: Optional[List[str]] = keywords_raw if isinstance(keywords_raw, list) else None

        urls_to_check: List[str] = []
        raw_url = company_data.get("url")
        if raw_url and isinstance(raw_url, str):
            urls_to_check.append(raw_url)

        domains = company_data.get("domains")
        if isinstance(domains, list):
            urls_to_check.extend([d for d in domains if isinstance(d, str)])
        elif isinstance(domains, str):
            urls_to_check.append(domains)

        provider = self.provider
        candidates_map: Dict[str, ValidationResult] = {}
        primary_domain = urls_to_check[0] if urls_to_check else None

        # 1. Extraction depuis le site officiel
        if provider in ("hybrid", "website_scraper"):
            if urls_to_check:
                site_results = self.extract_from_official_website(urls_to_check, company_name)
                for res in site_results:
                    if res.clean_url:
                        candidates_map[res.clean_url] = res

        # 2. Recherche moteur si nécessaire
        if provider != "website_scraper" and len(candidates_map) < max_candidates:
            search_urls: List[str] = []
            if provider in ("hybrid", "duckduckgo"):
                search_urls = self.search_duckduckgo_candidates(company_name, location, country_code)
            elif provider == "google":
                search_urls = self.search_google_custom_search_candidates(company_name, location, country_code)
            elif provider == "serpapi":
                search_urls = self.search_serpapi_candidates(company_name, location, country_code)

            for url in search_urls:
                if url not in candidates_map:
                    val_res = validate_instagram_candidate(
                        candidate_url=url,
                        company_name=company_name,
                        domain=primary_domain,
                        source="search_engine",
                        location=location,
                        country_code=country_code,
                        description=description,
                        keywords=keywords
                    )
                    if val_res.is_valid and val_res.clean_url:
                        candidates_map[val_res.clean_url] = val_res

            time.sleep(self.config.rate_limit_delay)

        if not candidates_map:
            return []

        # Tri décroissant selon le pourcentage de similarité multi-rubriques
        sorted_candidates = sorted(
            candidates_map.values(),
            key=lambda x: x.similarity,
            reverse=True
        )

        # --- Vérification de la biographie Instagram ---
        # Pour chaque candidat, on tente de récupérer les métadonnées publiques
        # (nom affiché + bio) afin de recalculer le score multi-rubriques complet.
        top_to_verify = sorted_candidates[:max_candidates]
        for res in top_to_verify:
            if res.clean_url and "official_website" not in res.reason:
                meta = self._fetch_instagram_profile_meta(res.clean_url)
                if meta:
                    display_name = meta.get("display_name", "")
                    bio = meta.get("bio", "")

                    # Recalcul complet du score avec toutes les rubriques MongoDB + bio Instagram
                    new_sim = calculate_similarity(
                        company_name=company_name,
                        username=res.username or "",
                        domain=primary_domain,
                        source="search_engine",
                        location=location,
                        country_code=country_code,
                        description=description,
                        keywords=keywords,
                        display_name=display_name,
                        bio=bio
                    )
                    new_conf = (
                        "HIGH" if new_sim >= 90.0
                        else ("MEDIUM" if new_sim >= 60.0 else "LOW")
                    )
                    res.similarity = new_sim
                    res.confidence = new_conf
                    res.reason = (
                        f"Score multi-rubriques {new_sim:.1f}% "
                        f"[Nom:{company_name} | Domaine:{primary_domain or 'N/A'} | "
                        f"Pays:{country_code or 'N/A'} | Bio: {'oui' if bio else 'non'}]"
                    )
                    logger.debug(
                        f"Score multi-rubriques pour @{res.username} : {new_sim:.1f}% ({new_conf})"
                    )
                time.sleep(1.0)

        # Re-tri après vérification des bios (scores peuvent avoir changé)
        sorted_candidates = sorted(
            top_to_verify,
            key=lambda x: x.similarity,
            reverse=True
        )

        return sorted_candidates[:max_candidates]

    def find_instagram_for_company(
        self,
        company_data: Dict[str, Any]
    ) -> Optional[ValidationResult]:
        """
        Rétro-compatibilité : retourne le meilleur candidat unique.
        """
        top_candidates = self.find_top_instagram_candidates(company_data, max_candidates=1)
        return top_candidates[0] if top_candidates else None
