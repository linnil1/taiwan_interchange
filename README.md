# Taiwan Interchange Explorer

This project provides comprehensive organization and visualization of all Taiwan highway interchanges with detailed ramp-level annotations. The data is processed from OpenStreetMap and offers classification, visualization, and search capabilities through an interactive web interface.

## Project Architecture (main file)

```
taiwan-interchange/
├── backend/                 # Python data processing engine
│   ├── data.py             # Main data processing and generation
│   ├── models.py           # Pydantic data models
│   ├── interchanges.json   # Generated interchange data
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
- **Data Processing**: Python backend processes OpenStreetMap data and generates JSON
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
   This will process OpenStreetMap data and save `interchanges.json` to both `backend/` and `frontend/static/`

### Frontend Development  
1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install Node.js dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm run dev
   ```
   Frontend will be available at `http://localhost:5173`

The frontend always reads data from `/interchanges.json` (static asset) in both development and production.

## Production Deployment

### Deploy to Cloudflare
1. Build and deploy:
   ```bash
   cd frontend
   npm run deploy
   ```

## Live Website

The production site is available at: **taiwan-interchanges.linnil1.me**

Github Page: **https://github.com/linnil1/taiwan-interchange**

## License & Citation

When using this data or codebase, please cite this project and acknowledge the underlying OpenStreetMap data contributors.