"""Configure sys.path so tests can import script30 modules."""
import sys
from pathlib import Path

# Add the script30 root to sys.path so `from net.retry_handler import ...` works.
_script30_root = str(Path(__file__).resolve().parent)
if _script30_root not in sys.path:
    sys.path.insert(0, _script30_root)
