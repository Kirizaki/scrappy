from scrapers.base import BaseScraper
from playwright.async_api import Page, Locator
import logging
import re

class DomiportaScraper(BaseScraper):
    def __init__(self, config):
        super().__init__("domiporta", config)

    async def scrape(self, page: Page, url: str, max_pages: int = 0) -> list:
        offers = []
        current_url = url
        page_num = 1
        
        while True:
            self.logger.info(f"Scraping page {page_num}: {current_url}")
            try:
                # Domiporta can be slow or use client-side rendering
                await page.goto(current_url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                self.logger.error(f"Failed to load page {current_url}: {e}")
                break

            # Cookie consent - Try to close it if it exists
            try:
                # Common cookie selectors
                await page.locator("button#onetrust-accept-btn-handler, button[class*='audit-allow-all']").click(timeout=2000)
            except:
                pass

            # Wait for articles to appear
            try:
                await page.wait_for_selector("article.sneakpeak", timeout=5000)
            except:
                self.logger.warning("No offers found on page (selector timeout).")
                break

            articles = await page.locator("article.sneakpeak").all()
            self.logger.info(f"Found {len(articles)} articles on page {page_num}")
            
            if not articles:
                break

            for article in articles:
                try:
                    offer = await self.parse_offer(article)
                    if offer:
                        offers.append(offer)
                except Exception as e:
                    self.logger.error(f"Error parsing offer: {e}")
            
            if max_pages > 0 and page_num >= max_pages:
                break
            
            # Pagination
            # Look for button "Następna" or class `pagination__next`
            next_btn = page.locator("li.pagination__item--next a")
            if await next_btn.count() > 0:
                 if await next_btn.first.is_enabled():
                    href = await next_btn.first.get_attribute("href")
                    if href:
                        current_url = href if href.startswith("http") else "https://www.domiporta.pl" + href
                        page_num += 1
                        continue
            
            break
                 
        return offers

    async def parse_offer(self, article: Locator):
        id_val = await article.get_attribute("data-detail-id")
        
        # Title
        title_el = article.locator(".sneakpeak__title--bold").first
        title = await title_el.inner_text() if await title_el.count() > 0 else ""
        
        # Link
        link_el = article.locator("a.sneakpeak__picture_container").first
        relative_url = await link_el.get_attribute("href") if await link_el.count() > 0 else ""
        full_url = relative_url
        if relative_url and not relative_url.startswith("http"):
            full_url = "https://www.domiporta.pl" + relative_url
            
        # Price
        price_el = article.locator(".sneakpeak__price_value").first
        price_text = await price_el.inner_text() if await price_el.count() > 0 else "0"
        price = self.normalize_price(price_text)
        
        # Details
        area = None
        floor = None
        
        # Area from selector
        area_el = article.locator(".sneakpeak__details_item--area").first
        if await area_el.count() > 0:
            area_text = await area_el.inner_text()
            area = self.normalize_area(area_text)

        # Fallback Area from Title
        if not area and title:
             m = re.search(r'(\d+(?:[.,]\d+)?)\s*m2', title, re.IGNORECASE)
             if m:
                 area = float(m.group(1).replace(",", "."))

        # Floor detection
        all_details = await article.locator(".sneakpeak__details_item").all_inner_texts()
        for txt in all_details:
             # Check for explicit floor
             if "piętro" in txt.lower() or "parter" in txt.lower():
                 floor = self.parse_floor(txt)
                 if floor is not None: break
        
        # Description fallback for floor and area
        desc_text = ""
        desc_el = article.locator(".sneakpeak__description").first
        if await desc_el.count() > 0:
             desc_text = await desc_el.inner_text()
             if floor is None:
                 floor = self.parse_floor(desc_text)
             # Fallback area from description
             if not area:
                 m = re.search(r'(\d+(?:[.,]\d+)?)\s*m2', desc_text, re.IGNORECASE)
                 if m:
                     area = float(m.group(1).replace(",", "."))

        # Location
        location = ""
        loc_el = article.locator(".sneakpeak__title--inblock").first
        if await loc_el.count() > 0:
            raw_loc = await loc_el.inner_text()
            # Remove "mieszkanie", "na sprzedaż" case insensitive
            cleaned = re.sub(r'(?i)(mieszkanie|na sprzedaż|dom|lokal)', '', raw_loc)
            location = " ".join(cleaned.split()).replace(" ,", ",").strip(", ")
            
        # Image
        img_el = article.locator("img.sneakpeak__picture_cover").first
        img_src = ""
        if await img_el.count() > 0:
            img_src = await img_el.get_attribute("src") or await img_el.get_attribute("data-src") or ""

        # Price per m2
        price_per_m2 = 0
        if price and area:
            price_per_m2 = price / area

        # Garden
        garden = self.check_garden(title) or self.check_garden(location)
        if not garden and desc_text:
             garden = self.check_garden(desc_text)
                 
        # Infer ground floor if garden
        if garden and floor is None:
            floor = 0

        return {
            "id": id_val,
            "url": full_url,
            "title": self.safe_text(title),
            "price": price,
            "price_per_m2": price_per_m2,
            "area": area,
            "floor": floor,
            "location": self.safe_text(location),
            "image_url": img_src,
            "garden": garden
        }
