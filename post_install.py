"""Post-install hook — runs after pip install."""
from src.funding import show, is_dismissed

if not is_dismissed():
    show()
