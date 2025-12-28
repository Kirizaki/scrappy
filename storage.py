import pandas as pd
import os
import logging
from datetime import datetime
from logger_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

CSV_FILE = "offers.csv"
COLUMNS = ["no", "url", "title", "price", "area", "price_per_m2", "location", "floor", "garden", "source", "scraped_at", "is_favorite", "is_hidden"]

def load_offers():
    if not os.path.exists(CSV_FILE):
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(CSV_FILE)
        # Ensure all columns exist
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
                if col in ["is_favorite", "is_hidden"]:
                    df[col] = False
        return df
    except Exception as e:
        logger.error(f"Error loading CSV: {e}")
        return pd.DataFrame(columns=COLUMNS)

def save_offers(new_offers: list[dict]):
    """
    Saves new offers to the CSV file with deduplication based on URL.
    Preserves existing 'is_favorite' and 'is_hidden' flags.
    """
    existing_df = load_offers()
    
    if not new_offers:
        logger.info("No new offers to save.")
        return

    new_df = pd.DataFrame(new_offers)
    
    # Add timestamp and default flags if not present
    if "scraped_at" not in new_df.columns:
        new_df["scraped_at"] = datetime.now().isoformat()
    if "is_favorite" not in new_df.columns:
        new_df["is_favorite"] = False
    if "is_hidden" not in new_df.columns:
        new_df["is_hidden"] = False
        
    # Ensure all columns are present in new_df
    for col in COLUMNS:
        if col not in new_df.columns:
            new_df[col] = None

    # Helper to prevent duplicates in existing_df before indexing
    if "url" in existing_df.columns:
         existing_df = existing_df.drop_duplicates(subset=["url"])

    existing_dict = existing_df.set_index("url").to_dict(orient="index")
    
    merged_list = []
    
    # Process new offers
    for index, row in new_df.iterrows():
        url = row["url"]
        if url in existing_dict:
            # Update fields but preserve flags
            existing_row = existing_dict[url]
            row["is_favorite"] = existing_row.get("is_favorite", False)
            row["is_hidden"] = existing_row.get("is_hidden", False)
            # Maybe keep original scraped_at? Or update it? Let's update it to show it's still active.
            # But user might want to know when it was FIRST found. Let's keep original scraped_at.
            row["scraped_at"] = existing_row.get("scraped_at", row["scraped_at"])
        
        merged_list.append(row.to_dict())
        
    # Now valid merged_list contains Updated New offers + New offers. 
    # What about Old offers that are NOT in the new list? 
    # If we want to keep history, we should add them too. 
    # If we want to clean up sold offers, we might remove them.
    # The requirement says "gathered offers save in .csv", doesn't explicitly say "delete old".
    # Usually real estate scrapers keep history. Let's keep them attached.
    
    new_urls = set(new_df["url"])
    for url, data in existing_dict.items():
        if url not in new_urls:
            # This offer was not found in current run. 
            # We add it back as is.
            item = data.copy()
            item["url"] = url
            merged_list.append(item)

    final_df = pd.DataFrame(merged_list)
    
    # Sort by scraped_at descending to keep newest at top, then assign "no"
    if "scraped_at" in final_df.columns:
        final_df = final_df.sort_values(by="scraped_at", ascending=False)
        
    # Assign ordinal numbering (1-based)
    final_df = final_df.reset_index(drop=True)
    final_df["no"] = final_df.index + 1
    
    final_df = final_df[COLUMNS] # Reorder
    final_df.to_csv(CSV_FILE, index=False)
    logger.info(f"Saved {len(final_df)} offers to {CSV_FILE}")

def update_offer_status(url: str, field: str, value: bool):
    df = load_offers()
    if url in df["url"].values:
        df.loc[df["url"] == url, field] = value
        df.to_csv(CSV_FILE, index=False)
        return True
    return False
