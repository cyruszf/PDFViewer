# config.py

from typing import Dict, Any

# --- Embedded Icons Data ---
# Note: You can keep ICON_DATA here, but if the Base64 strings are extremely long,
# you might consider putting them in a separate data file (e.g., icons.py)
# and importing them here. For now, this is fine.
ICON_DATA: Dict[str, Any] = {
    "open": b"...",
    "zoom_in": b"...",
    "zoom_out": b"...",
    "rotate": b"...",
    "search": b"...",
    "up": b"...",
    "down": b"..."
}

# --- Theme Configuration ---
THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg": "#2E2E2E",
        "fg": "#FFFFFF",
        "canvas_bg": "#3A3A3A",
        "highlight": "#007ACC",
        "entry_bg": "#3A3A3A",
        "btn_bg": "#4A4A4A"
    },
}

# --- Application Constants ---
# Limit for how many rendered pages to keep in memory cache
CACHE_SIZE_LIMIT: int = 20

# Number of pages to render immediately above/below the visible viewport
RENDER_BUFFER_PAGES: int = 2