from scrapers.base import BaseScraper
from playwright.async_api import Page, Locator
import logging
import re

class AdresowoScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("adresowo", config)
        # Assuming base_url is something like "https://adresowo.pl/mieszkania/gdansk/"
        # We will dynamically build it, but config might have the city base.

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        offers = []
        current_url = url
        page_num = 1
        
        while True:
            self.logger.info(f"Scraping page {page_num}: {current_url}")
            try:
                await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                self.logger.error(f"Failed to load page {current_url}: {e}")
                break
            
            # Wait for results or empty list
            try:
                await page.wait_for_selector(".result-list, .search-no-results", timeout=5000)
            except:
                pass
            
            # Use specific offer link structure
            offer_locators = await page.locator("a[href^='/o/']").all()
            self.logger.info(f"Found {len(offer_locators)} offers on page {page_num}")
            
            if not offer_locators:
                self.logger.info("No more offers found.")
                break

            for offer_loc in offer_locators:
                try:
                    offer = await self.parse_offer(offer_loc)
                    if offer:
                        offers.append(offer)
                except Exception as e:
                    self.logger.error(f"Error parsing offer: {e}")
            
            if max_pages > 0 and page_num >= max_pages:
                break

            # Pagination: /_l2, /_l3 etc appended to base
            # Check for next page button
            next_btn = page.locator("a.search-pagination__next")
            if await next_btn.count() > 0:
                 href = await next_btn.get_attribute("href")
                 if href:
                     if not href.startswith("http"):
                         current_url = "https://adresowo.pl" + href
                     else:
                         current_url = href
                     page_num += 1
                     continue
            
            # If no next button, stop
            break
            
        return offers

    async def parse_offer(self, link_el: Locator):
        # The element itself is the <a> link
        href = await link_el.get_attribute("href")
        full_url = "https://adresowo.pl" + href if href and not href.startswith("http") else href
        
        # ID is suffix of href usually
        id_val = href.split("-")[-1] if href else ""
        
        # Title/District
        title_el = link_el.locator(".result-info__header strong").first
        title_text = await title_el.inner_text() if await title_el.count() > 0 else ""
        
        # Address
        addr_el = link_el.locator(".result-info__address").first
        addr_text = await addr_el.inner_text() if await addr_el.count() > 0 else ""
        
        # Full location string
        # Assuming URL has city, but we can combine title (district) + address
        location = f"{title_text} {addr_text}".strip()

        # Price
        # .result-info__price--total span
        price_el = link_el.locator(".result-info__price--total span").first
        price_str = await price_el.inner_text() if await price_el.count() > 0 else ""
        price = self.normalize_price(price_str)
        
        # Price per m2
        ppm2_el = link_el.locator(".result-info__price--per-sqm span").first
        ppm2_str = await ppm2_el.inner_text() if await ppm2_el.count() > 0 else ""
        price_per_m2 = self.normalize_price(ppm2_str) # normalize_price handles "13 500 zł/m2" if well written? 
        # BaseScraper.normalize_price removes non-digits, so it should be fine mostly.
        
        # Details: Area, Rooms in .result-info__basic
        # Format often: "3 pok.  64,5 m²" or similar
        basic_el = link_el.locator(".result-info__basic").first
        basic_text = await basic_el.inner_text() if await basic_el.count() > 0 else ""
        
        area = None
        # Extract area
        m_area = re.search(r'([\d,.]+)\s*m²', basic_text)
        if m_area:
            area = self.normalize_area(m_area.group(1))
            
        # Floor
        # Usually not in list view, need to visit? 
        # User requirement says "scraping", usually list view is preferred for speed.
        # Sometimes floor is in details. If not, left as None.
        floor = None
        
        # Image
        img_el = link_el.locator("img.result-photo__image").first
        img_src = ""
        if await img_el.count() > 0:
            img_src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""

        # Garden
        garden = self.check_garden(title_text) or self.check_garden(basic_text)
        
        # Infer ground floor from garden
        if garden and floor is None:
            floor = 0
            
        return {
            "id": id_val,
            "url": full_url,
            "title": self.safe_text(title_text), # Adresowo doesn't have a clear "Title" like "Nice flat", it's mostly location
            "price": price,
            "price_per_m2": price_per_m2,
            "area": area,
            "floor": floor,
            "location": self.safe_text(location),
            "image_url": img_src,
            "garden": garden
        }
