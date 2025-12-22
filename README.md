# SCRAPPY - Real Estate Hunter 🦦

**SCRAPPY** is a powerful, self-hosted web application designed to hunt down the best real estate offers in the Tricity area (Gdańsk, Gdynia, Sopot). It scrapes major Polish real estate portals (Otodom, OLX, Trojmiasto.pl, Morizon) and presents them in a beautiful, auto-refreshing dashboard.

![SCRAPPY Logo](static/logo.png)

## Features

-   **Multi-Portal Scraping**: Aggregates offers from Otodom, OLX, Trojmiasto.pl, and Morizon.
-   **Live Dashboard**: Real-time updates with an auto-refreshing table as the scraper works in the background.
-   **Smart Filtering**:
    -   Filter by Min Area (m²) and Max Price (PLN).
    -   **"Ground Floor Only"** detection.
    -   **"Must Have Garden"** detection.
    -   District/Location text search.
-   **Persistent Storage**: Saves scraped offers to a local CSV file (`offers.csv`) to track history.
-   **Mobile Friendly**: Responsive "Ocean Blue" UI that looks great on your phone.

## Installation

1.  Clone the repository:
    ```bash
    git clone https://github.com/your-username/scraper.git
    cd scraper
    ```

2.  Create and activate a virtual environment:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    playwright install chromium
    ```

## Usage

1.  Start the application:
    ```bash
    python app.py
    ```

2.  Open your browser and navigate to:
    -   **Local**: [http://localhost:8000](http://localhost:8000)
    -   **Network**: Find your local IP (e.g., `http://192.168.0.x:8000`) to access from your phone!

3.  Click **"HUNT OFFERS"** to start scraping.

## Cloudflare Tunnel

1.  Install Cloudflare Tunnel:
    ```bash
    brew install cloudflared
    ```

2.  Start the tunnel:
    ```bash
    cloudflared tunnel --url http://localhost:8000 --protocol http2
    ```

## Configuration

You can configure the scraper directly from the Web UI (Settings button) or by editing `config.json`.

## License

Copyright (c) 2025 Grzegorz Krajewski aka Kirizaki. See [LICENSE](LICENSE) for details.
