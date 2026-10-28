"""Bind-flow copy."""

from __future__ import annotations


BIND_PUBLIC_REPLY = (
    "Bind your Rizline account in this DM.\n"
    "Use the email on your Rizline account. Enter your password, or type `code` to get a verification email.\n"
    "The form is private to this DM. Your passeord or verification code is sent to the bot host once to fetch your save, then discarded. "
    "The session token stays in memory until /unbind or a restart. "
    "An encrypted cache of your username, RKS, chart results, and profile card is stored until it expires. "
    "Encryption does not protect that data if the bot host is compromised."
)

BIND_CONTINUE = "Continue"
BIND_MODAL_TITLE = "Bind Rizline account"
BIND_EMAIL_LABEL = "Rizline email"
BIND_PASSCODE_LABEL = "Password or code"
BIND_PASSCODE_HINT = "Password, or type code for email verification"
BIND_CODE_TITLE = "Email verification code"
BIND_CODE_LABEL = "Code from your email"
BIND_ENTER_CODE = "Enter code"
BIND_CODE_READY = (
    "A verification code was requested for that Rizline email. "
    "Check your inbox, press Enter code, and submit it in the form. The code is not posted in this DM."
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
