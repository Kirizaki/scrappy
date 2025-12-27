import re
from playwright.async_api import Page
from abc import ABC, abstractmethod

class BaseScraper(ABC):
    def __init__(self, portal_name: str, config: dict):
        self.portal_name = portal_name
        self.config = config
        
    @abstractmethod
    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        pass

    def safe_text(self, text: str) -> str:
        if not text:
            return ""
        # Replace newlines and tabs with space, strip whitespace
        return " ".join(text.split())

    def normalize_price(self, price_str):
        if not price_str: return None
        # Remove 'zł', spaces, replace ',' with '.'
        clean = re.sub(r'[^\d,.]', '', str(price_str))
        clean = clean.replace(" ", "").replace(",", ".")
        try:
            val = float(clean)
            # If value is 1-2 digits (e.g. 50), it likely means thousands (50,000)
            if 0 < val < 100:
                val *= 1000
            return val
        except:
            return None

    def normalize_area(self, area_str):
        if not area_str: return None
        clean = str(area_str).lower().replace("m2", "").replace("m²", "").replace(" ", "").replace(",", ".")
        try:
            return float(clean)
        except:
            return None

    def parse_floor(self, text):
        if not text: return None
        text_lower = text.lower()
        
        # Word-based mapping for Polish floors
        word_map = {
            "parter": 0,
            "pierwsze": 1, "drugie": 2, "trzecie": 3, "czwarte": 4,
            "piąte": 5, "piate": 5, "szóste": 6, "szoste": 6,
            "siódme": 7, "siodme": 7, "ósme": 8, "osme": 8,
            "dziewiąte": 9, "dziewiate": 9, "dziesiąte": 10, "dziesiate": 10
        }
        
        for word, val in word_map.items():
            if word == "parter":
                # Check for "parter" as a whole word
                if re.search(r'\bparter\b', text_lower):
                    return val
            else:
                if re.search(fr'\b{word}\b', text_lower):
                    return val

        if "poziom 0" in text_lower:
            return 0
            
        # Slash format: "1/4", "3/10"
        m_slash = re.search(r'(\d{1,2})[ \t]*/[ \t]*(\d{1,2})(?![ \t]*pok)', text_lower)
        if m_slash:
            val = int(m_slash.group(1))
            # Verify context to avoid photo counts (e.g. 1/20)
            context = text_lower[max(0, m_slash.start()-5) : min(len(text_lower), m_slash.end()+15)]
            if any(x in context for x in ["p.", "piętro", "p\b", "p ", "poziom"]):
                return val

        # Standard format: "1 piętro", "3 p."
        m = re.search(r'(\d{1,2})\s*(?:piętro|p\.|p\b|poziom)', text_lower)
        if m: return int(m.group(1))
        
        # Prefix format: "piętro 1", "p. 4"
        m2 = re.search(r'(?:piętro|p\.|p\b|poziom)\s*(\d{1,2})', text_lower)
        if m2: return int(m2.group(1))
        
        # Roman numerals
        roman_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
        roman_m = re.search(r'\b(i{1,3}|iv|v|vi{1,3}|ix|x)\b[ \t]*(?:piętro|p\.|p\b)', text_lower)
        if roman_m:
            return roman_map.get(roman_m.group(1))

        # Garden inference -> Ground floor
        if self.check_garden(text_lower):
             # Only if no other floor detected? 
             # For now, let's assume if it says garden but no floor info, it's ground.
             # But if it says "4th floor with winter garden", check_garden returns true.
             # Caller logic usually prioritizes explicit floor. 
             # We return None here so caller can decide default? 
             # The original code returned 0.
             return 0

        return None

    def check_garden(self, text):
        if not text: return False
        t = text.lower()
        return any(x in t for x in ["ogród", "ogródek", "garden", "działka", "ogrod", "ogrodek", "dzialka"])
