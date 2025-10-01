# Taiwan Interchange Explorer

This project provides comprehensive organization and visualization of all Taiwan highway interchanges with detailed ramp-level annotations. The data is processed from OpenStreetMap, Wikipedia, and Freeway Bureau, Ministry of Transportation and Communications (交通部高速公路局) and offers classification, visualization, and search capabilities through an interactive web interface.

## Project Architecture (main file)

```
taiwan-interchange/
├── backend/                # Python data processing engine
│   ├── data.py             # Main data processing and generation
│   ├── osm.py              # OpenStreetMap extraction and parsing
│   ├── wiki.py             # Wikipedia data extraction and parsing
│   ├── gov.py              # Government data extraction (Freeway Bureau, Ministry of Transportation and Communications)
│   ├── interchanges.json   # Generated interchange data with multi-source integration
│   └── requirements.txt    # Python dependencies
├── frontend/               # SvelteKit web application
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte          # SvelteKit root page (no API routes needed)
│   │   │   └── about/+page.svelte    # About page
│   │   ├── lib/
│   │   │   ├── components/           # Shared components and utilities
│   │   │   └── types.ts              # Shared TypeScript types
│   │   └── static/         # Static assets including interchanges.json
│   ├── package.json        # Node.js dependencies
│   └── wrangler.jsonc      # Cloudflare deployment configuration
└── README.md
```

The system operates with a simple architecture:
- **Data Processing**: Python backend processes OpenStreetMap, Wikipedia, and Freeway Bureau, Ministry of Transportation and Communications (交通部高速公路局) data and generates JSON
- **Static Serving**: Both development and production serve data from static assets

## Development Setup

### Prerequisites
- Python 3.13+ 
- Node.js 18+
- npm

### Backend Development (Data Processing)
1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Generate/update interchange data:
   ```bash
   python data.py
   ```
   This will process OpenStreetMap and Wikipedia data and save `interchanges.json` to both `backend/` and `frontend/static/`

### Frontend Development  
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. (Optional) Configure Google Maps API key:

   Open `/frontend/.env` and add your Google Map API key:
   ```bash
   PUBLIC_GOOGLE_MAPS_API_KEY=your_actual_google_maps_api_key_here
   ```

4. Start the development server:
   ```bash
   npm run dev
   ```
   Frontend will be available at `http://localhost:5173`

The frontend always reads data from `/interchanges.json` (static asset) in both development and production.

## Production Deployment

### Deploy to Cloudflare

1. (Optional) Configure Google Maps API key for production:

   Add the key to `frontend/wrangler.jsonc` under the `vars` section:
   ```jsonc
   "vars": {
     "PUBLIC_GOOGLE_MAPS_API_KEY": "your_api_key_here"
   }
   ```

2. Build and deploy:
   ```bash
   cd frontend
   npm run deploy
   ```

## Live Website

The production site is available at: **taiwan-interchanges.linnil1.me**

Github Page: **https://github.com/linnil1/taiwan_interchange**

## License & Citation

### Source Code License
This project's source code is licensed under the **GNU General Public License v3.0 (GPL-3.0)**. 

See the [GPL-3.0 license](https://www.gnu.org/licenses/gpl-3.0.html) for full terms.

### Data License
The processed interchange data (`interchanges.json`) is licensed under **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**.

The underlying OpenStreetMap data is licensed under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

Wikipedia content is available under [Creative Commons Attribution-ShareAlike 3.0](https://creativecommons.org/licenses/by-sa/3.0/).

Government highway data from the Freeway Bureau, Ministry of Transportation and Communications (交通部高速公路局) is available under the [Government Website Open Data Declaration](https://www.freeway.gov.tw/Publish.aspx?cnid=1660).