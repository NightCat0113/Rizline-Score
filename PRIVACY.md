# Privacy Policy — Rizline Lookup

Last updated: 2026-10-28

**Contact:** [operator email or Discord]

This document describes how **Rizline Lookup** (the “Service”) handles personal data when you use the Discord bot. It is not legal advice. The operator should have it reviewed before relying on it.

## 1. Who operates the Service

Rizline Lookup is an unofficial fan Discord bot. It is not operated by the Rizline publisher or by Discord.

**Contact:** [operator email or Discord]

## 2. What we collect and why

| Data | Why | How long |
| --- | --- | --- |
| Discord user id | Identify your binding, preferences, and command results | Until you delete the related records (see §6) |
| Language preference | Render card and UI text in your language | Until you ask for deletion; **survives `/unbind`** |
| Sharing flag (`/share`) | Decide whether other bot users may look up your scores | Until `/unbind` removes the binding |
| Encrypted score cache (username, RKS, chart results, profile-card fields such as avatar and bio ids) | Answer `/score`, `/profile`, `/b40`, and similar without logging in every time | Until the cache TTL expires (default 24 hours), you `/refresh` or `/bind` again, or you `/unbind` |
| Rizline email, session token, and device id | Keep a live session for `/refresh`, `/asyncombat`, `/weekly`, and related live calls | **In memory only**, until `/unbind` or the bot process restarts |
| Rizline passcode or email verification code | Log in once during `/bind` | Used once, then discarded; **not** written to the database |
| Command interaction metadata that Discord delivers to the bot | Run slash commands and send replies | Handled in the bot process; Discord also keeps its own copies under Discord’s policies |

Song and series lookups that do not need a bound account do not require Rizline credentials.

## 3. What we do not store

- Passcodes and email verification codes in the database
- Session tokens on disk
- Full game saves, mailbox contents, or purchase history in the bot database
- Advertising profiles or analytics SDK events

The separate local CLI tools in this repository can write decrypted save files if you run them yourself. That is outside the Discord bot path described here.

## 4. Sharing with other users

By default, other people who use this bot **cannot** see your scores.

If you turn **`/share on`**, other users of this bot can look up your scores with `/score` and `/profile` while your encrypted cache is still valid. If the cache has expired, they still get an unavailable result until you `/refresh` or `/bind` again.

Turn **`/share off`** (or leave it off) to stop that sharing. `/unbind` also removes the binding that sharing depends on.

## 5. Who else receives data

- **Discord** — delivers commands and stores messages and interactions according to Discord’s terms and privacy policy. The bot cannot erase Discord’s copies of DMs or slash-command history.
- **Game service** (`https://service.rhyths.net`) — receives login and live game requests (including email, token, and device id as required by that API). That host’s operator controls what happens to credentials after the request.

Asset download hosts used by offline maintenance scripts are **not** called by the running Discord bot.

We do **not** sell your personal data. We do not run ads in the bot.

## 6. Encryption and host compromise

The score cache is encrypted at rest with a key held by the operator (`BOT_ENCRYPTION_KEY`). Encryption does **not** protect that data if the computer running the bot is compromised, because the process then holds the key, any plaintext cache in use, and any in-memory session.

## 7. How to delete your data

1. Run **`/unbind`**. That deletes your binding, encrypted score cache, and in-memory session from this bot.
2. Language preference may remain. Contact the operator (below) and ask for that row to be deleted.
3. `/unbind` and ordinary database delete cannot erase Discord’s message history, host backups, crash dumps, or leftover disk copies.

## 8. Children

The Service is not directed at children under 13. Do not use it if you are under 13. If you believe a child under 13 has bound an account, contact the operator so the related bot data can be removed.

## 9. International users

The bot runs on infrastructure chosen by the operator. Data may be processed in the country where that host is located. Contact the operator if you need more detail about the current host.

## 10. Changes

This policy may be updated by revising this file. The “Last updated” date will change when it does. Continued use after a change means you accept the updated policy.

## 11. Contact

Privacy questions and deletion requests: **[operator email or Discord]**
