# Privacy Policy — Rizline Lookup

Last updated: 2026-11-03

**Contact:** nightwind0112@gmail.com / Discord @nightwind.nightcat

This document describes how **Rizline Lookup** (the “Service”) handles personal data when you use the Discord bot. It is not legal advice. The operator should have it reviewed before relying on it.

## 1. Who operates the Service

Rizline Lookup is an unofficial fan Discord bot. It is not operated by the Rizline publisher or by Discord.

**Contact:** nightwind0112@gmail.com / Discord @nightwind.nightcat

## 2. What we collect and why

| Data | Why | How long |
| --- | --- | --- |
| Discord user id | Identify your binding, preferences, and command results | Until you delete the related records (see §8) |
| Language preference | Render card and UI text in your language | Until you ask for deletion; **survives** `/unbind` |
| Sharing flag (`/share`) | Decide whether other bot users may open your `/profile` | Until `/unbind` removes the binding |
| Encrypted score cache | Answer score commands without logging in every time. The cache holds your Rizline username, RKS, per-chart scores, profile-card ids (avatar, bio, background, layout), achievement ids and unlock times, owned bio / layout / illustration ids, and tutorial challenge progress. It does not hold Asyncombat match history | Until the cache TTL expires (default 24 hours), you `/refresh` or `/bind` again, or you `/unbind` |
| Rizline email, session token, and a device id the bot generates for that login | Keep a live session for `/refresh`, `/asyncombat`, `/weekly`, and related live calls | **Encrypted** in the bot database until `/unbind`, 14 days without a successful live call, or Rizline rejects the login. A successful `/bind`, `/refresh`, `/asyncombat`, or `/weekly` starts a new 14-day window. A copy also stays in the bot process until then |
| Rizline password or email verification code | Log in once during `/bind` | Used once, then discarded. **Not** written to the database. You enter it in a hidden form, not as a chat message |
| Command interaction metadata that Discord delivers to the bot | Run slash commands and send replies | Handled in the bot process. Discord also keeps its own copies under Discord’s policies |

Song, art, series, and catalog lookups do not require Rizline credentials. If you are already bound, `/song` and `/random` draw your chart results on the image they send.

`/asyncombat` and `/weekly` ask the game for a fresh result and send it back through Discord. Those live payloads are not written into the score cache.

## 3. What we do not store

- Passwords and email verification codes in the database
- Session tokens in plaintext (they are encrypted with the same key as the score cache)
- Full game saves, mailbox contents, or purchase history in the bot database
- Asyncombat match history
- Advertising profiles or analytics SDK events

The separate local CLI in this repository (`rizline/login.py`) can write a decrypted save file if you run it yourself. That file can contain mail and purchase data. It is outside the Discord bot path described here.

## 4. Who can see a reply

Slash-command replies appear in the channel where you ran the command, unless you set `private`.

These commands are always hidden from other people in the channel:

- `/bind`
- `/unbind`
- `/help`

`/share` and `/language` post their confirmation in the channel. That confirmation includes whether sharing is on, or which language you picked.

People who can see the channel can see a public reply, including a song card that has your scores on it. Discord keeps its own copy of that message. The bot cannot erase Discord’s history.

## 5. Sharing with other users of this bot

By default, other people who use this bot **cannot** see your scores.

If you turn `/share on`, other users of this bot can open your scores with `/profile` while your encrypted cache is still valid. If the cache has expired, they still get an unavailable result until you `/refresh` or `/bind` again. Sharing does not let them run `/b40`, `/recommend`, `/achievements`, `/asyncombat`, or `/weekly` on your account.

Turn `/share off` (or leave it off) to stop that lookup. `/unbind` also removes the binding that sharing depends on.

The bot does not tell other people whether you are bound. When a lookup is refused, the reply is the same unavailable message.

## 6. Who else receives data

- **Discord** — delivers commands and stores messages and interactions according to Discord’s terms and privacy policy. The bot cannot erase Discord’s copies of messages or slash-command history.
- **Game service** (`https://service.rhyths.net`) — receives login and live game requests (including email, token, and the device id) as required by that API. That host’s operator controls what happens to credentials after the request.

Asset download hosts used by offline maintenance scripts are **not** called by the running Discord bot. Refreshing the public song catalog does not send your Rizline account to GitHub.

We do **not** sell your personal data. We do not run ads in the bot.

## 7. Encryption and host compromise

The score cache and Rizline session are encrypted at rest with a key held by the operator (`BOT_ENCRYPTION_KEY`). Encryption does **not** protect that data if the computer running the bot is compromised, because the process then holds the key and any plaintext it has loaded.

## 8. How to delete your data

1. Run `/unbind`. That deletes your binding, encrypted score cache, and encrypted session from this bot.
2. Language preference may remain. Contact the operator (below) and ask for that row to be deleted.
3. `/unbind` and ordinary database delete cannot erase Discord’s message history, host backups, crash dumps, or leftover disk copies.

## 9. Children

The Service is not directed at children under 13. Do not use it if you are under 13. If you believe a child under 13 has bound an account, contact the operator so the related bot data can be removed.

## 10. International users

The bot runs on infrastructure chosen by the operator. Data may be processed in the country where that host is located. Contact the operator if you need more detail about the current host.

## 11. Changes

This policy may be updated by revising this file. The “Last updated” date will change when it does. Continued use after a change means you accept the updated policy.

## 12. Contact

Privacy questions and deletion requests:
Email: nightwind0112@gmail.com
Discord: @nightwind.nightcat
