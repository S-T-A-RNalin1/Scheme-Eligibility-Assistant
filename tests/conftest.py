import os
import sys
from pathlib import Path

# Tests use their own database so they never touch demo data.
os.environ.setdefault("DB_NAME", "scheme_assistant_test")
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
