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
    ValidationResult
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

    def search_duckduckgo_candidates(
        self,
        company_name: str,
        location: Optional[str] = None,
        country_code: Optional[str] = None,
        max_results: int = 5
    ) -> List[str]:
        """
        Recherche plusieurs profils candidats via DuckDuckGo.
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

            query_parts = [f'"{company_name}"', "site:instagram.com"]
            if location:
                query_parts.append(location)
            elif country_code:
                query_parts.append(country_code)

            query = " ".join(query_parts)
            logger.debug(f"Requête DuckDuckGo : {query}")

            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

            for r in results:
                href = r.get("href") or r.get("link", "")
                if "instagram.com" in href.lower():
                    cleaned = clean_instagram_url(href)
                    if cleaned and cleaned not in candidates:
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
        de similarité décroissant (du plus pertinent au moins pertinent).
        """
        company_name = company_data.get("companyName", "").strip()
        if not company_name:
            return []

        location = company_data.get("location")
        country_code = company_data.get("countryCode")

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

            primary_domain = urls_to_check[0] if urls_to_check else None

            for url in search_urls:
                if url not in candidates_map:
                    val_res = validate_instagram_candidate(
                        candidate_url=url,
                        company_name=company_name,
                        domain=primary_domain,
                        source="search_engine"
                    )
                    if val_res.is_valid and val_res.clean_url:
                        candidates_map[val_res.clean_url] = val_res

            time.sleep(self.config.rate_limit_delay)

        if not candidates_map:
            return []

        # Tri décroissant selon le pourcentage de similarité
        sorted_candidates = sorted(
            candidates_map.values(),
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
