"""Bind-flow copy."""

from __future__ import annotations


BIND_PUBLIC_REPLY = (
    "Bind a Rizline account in this DM.\n"
    "Use a test account. The email and passcode go into a form and are not posted in this DM.\n"
    "Your passcode is sent to the computer running the bot, used once to fetch your save, and then discarded. "
    "The session token stays in memory until /unbind or a restart. "
    "An encrypted cache of your username, RKS, chart results, and profile card is stored until it expires. "
    "Encryption does not protect that data if the computer running the bot is compromised."
)

BIND_CONTINUE = "Continue"
BIND_MODAL_TITLE = "Bind Rizline account"
BIND_EMAIL_LABEL = "Email"
BIND_PASSCODE_LABEL = "Passcode"
BIND_PASSCODE_HINT = "Type code to request an email code"
BIND_CODE_TITLE = "Verification code"
BIND_CODE_LABEL = "Code"
BIND_ENTER_CODE = "Enter code"
BIND_CODE_READY = (
    "If that account can receive mail, a verification code was requested. "
    "Press Enter code and submit it in the form. The code is not posted in this DM."
)

UNBIND_REMOVED = (
    "Removed your binding, encrypted score cache, and in-memory session from this bot. "
    "SQLite delete and VACUUM do not wipe leftover copies in backups, crash dumps, or SSD spare blocks."
)

UNBIND_EMPTY = "Nothing was stored for your Discord account."

SHARE_ON = (
    "Sharing is on. Other people who use this bot can look up your scores with /profile. "
    "If your cache has expired, they still get an unavailable result until you /refresh or /bind."
)

SHARE_OFF = (
    "Sharing is off. Other people get the same unavailable response as they would for an account that is not bound."
)
