"""Entry point: `.venv\Scripts\pythonw.exe main.py [files…]`, or just run.bat."""

import sys

from cover_editor.app import main

if __name__ == "__main__":
    sys.exit(main())
