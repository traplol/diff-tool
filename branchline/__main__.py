import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Review Git branches and stacks in a native desktop window.")
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Git working directory (default: current directory)",
    )
    args = parser.parse_args()
    try:
        import tkinter as tk

        from .app import App
    except ImportError as error:
        parser.exit(1, f"Branchline needs Python with Tk support. {error}\n")
    try:
        root = tk.Tk(className="Branchline")
    except tk.TclError as error:
        parser.exit(
            1, f"Could not open a desktop window: {error}\nOn WSL, start Branchline in a WSLg session.\n"
        )
    App(root, args.directory)
    root.mainloop()


if __name__ == "__main__":
    sys.exit(main())
