"""Entry point for `python -m ove_tui`."""

from ove_tui.app import OveLabManager


def main():
    app = OveLabManager()
    app.run()


if __name__ == "__main__":
    main()
