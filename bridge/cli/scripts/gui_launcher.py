"""PyInstaller entry. A package-aware launcher so the relative imports
in laborster_bridge.gui.app resolve (running app.py directly would not).
"""

from laborster_bridge.gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
