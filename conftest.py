import sys
from pathlib import Path

# Ensure the project root is on sys.path when tests are executed
# via the `pytest` entry script.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
