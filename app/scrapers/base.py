from abc import ABC, abstractmethod


class TrendScraper(ABC):
    """Interface scraper — bikin sumber gampang ditukar tanpa bongkar dashboard."""

    @abstractmethod
    def fetch_trends(self, vertical: str, category: str) -> list[dict]:
        """Kembalikan list tren mentah, tiap item minimal:
        {external_id, category, name, url, metrics: {...}}."""
        raise NotImplementedError
