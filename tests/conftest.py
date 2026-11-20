import sys
from pathlib import Path

# Ensure .venv site-packages are accessible even when pytest is invoked from global Python
venv_site = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages"
if venv_site.is_dir() and str(venv_site) not in sys.path:
    sys.path.insert(0, str(venv_site))
