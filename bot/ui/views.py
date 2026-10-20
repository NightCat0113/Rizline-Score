"""Bind-flow copy."""

from __future__ import annotations


BIND_PUBLIC_REPLY = (
    "Bind a Rizline account in this DM.\n"
    "Use a test account. Discord keeps this conversation, and the bot cannot delete your messages.\n"
    "Your passcode is sent to the computer running the bot, used once to fetch your save, and then discarded. "
    "The session token stays in memory until /unbind or a restart. "
    "An encrypted cache of your username, RKS, and chart results is stored until it expires. "
    "Encryption does not protect that data if the computer running the bot is compromised.\n\n"
    "Reply with your account email, or send `cancel`."
)

BIND_DM_INTRO = (
    "Bind a Rizline account to this bot.\n"
    "Use a test account. Discord keeps this conversation, and the bot cannot delete your messages.\n"
    "Your passcode is sent to the computer running the bot, used once to fetch your save, and then discarded. "
    "The session token stays in memory until /unbind or a restart. "
    "An encrypted cache of your username, RKS, and chart results is stored until it expires. "
    "Encryption does not protect that data if the computer running the bot is compromised.\n\n"
    "Reply with your account email, or send `cancel`."
)

BIND_ASK_SECRET = (
    "Reply with the passcode, or send `code` to request an email verification code. "
    "The passcode is not saved. Send `cancel` to stop."
)

BIND_ASK_CODE = (
    "If that account can receive mail, a verification code was requested. "
    "Reply with the code, or send `cancel`."
)

UNBIND_REMOVED = (
    "Removed your binding, encrypted score cache, and in-memory session from this bot. "
    "SQLite delete and VACUUM do not wipe leftover copies in backups, crash dumps, or SSD spare blocks."
)

UNBIND_EMPTY = "Nothing was stored for your Discord account."

SHARE_ON = (
    "Sharing is on. Other people who use this bot can look up your scores with /score and /profile. "
    "If your cache has expired, they still get an unavailable result until you /refresh or /bind."
)

SHARE_OFF = (
    "Sharing is off. Other people get the same unavailable response as they would for an account that is not bound."
)
