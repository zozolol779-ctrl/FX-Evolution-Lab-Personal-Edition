from pathlib import Path
import sys

package_root = Path(__file__).resolve().parent / "fx-evolution-lab"
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))
