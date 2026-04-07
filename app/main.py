from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.core.config import settings
import os
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix="/api")

# Serve static files (frontend)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard page."""
    index_file = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r") as f:
            return f.read()
    return "<h1>Frontend index.html not found!</h1>"

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting Runway on http://{settings.APP_HOST}:{settings.APP_PORT}")
    if settings.APP_HOST == "0.0.0.0":
        logger.warning("Server bound to 0.0.0.0 - accessible from all network interfaces!")
    uvicorn.run(app, host=settings.APP_HOST, port=settings.APP_PORT)
