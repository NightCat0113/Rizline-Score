"""Altare / process entry point. Prefer this over ``python -m bot`` on hosts
that only accept a single startup file.
"""

from bot.app import main

if __name__ == "__main__":
    main()
