# Rizline Lookup — security audit

Last updated: 2026-11-03. The first review was 2026-10-20, against `rizline_login.py` before it was split into `rizline/client.py` and `rizline/login.py`.

This update re-reads the current bot, login client, and socket client. No live login was performed. No real Rizline credentials or session tokens were used. Passing the tests in `tests/` does not mean this program is safe.

## How to read this report

- **Verified:** observed in the current source, or covered by a test that uses fake secrets and a local mock.
- **Fixed:** true of the October client, and the current source does something else.
- **Suspicious:** looks risky, but this review did not prove exploitation.
- **Could not verify:** not checked, or cannot be checked without a live service, the original process, or another machine.

## 1. Login client

The Discord bot calls `rizline/client.py` only through `bot/services/rizline_api.py`, with `require_pinned_host=True` and `https://service.rhyths.net`. `bot/` does not pass `allow_http_localhost`.

| Path | When | Body fields | Extra headers |
| --- | --- | --- | --- |
| `account/login` | Password | `email`, `password` | `device_id` |
| `account/send_email` | Email-code login | `email`, `transaction=login` | `device_id` |
| `account/login` | Email code | `email`, `code` | `device_id` |
| `game/rn_login` | Score cache after login or `/refresh` | `{}` | `device_id`, `email`, `token` |
| `game/async_battle/rank_info` and three alternate paths | `/asyncombat`, tried in order | `{}` | `device_id`, `email`, `token` |
| `game/get_weekly_tasks` and `get_weekly_tasks` | `/weekly`, tried in order | `{}` | `device_id`, `email`, `token` |
| `game/rn_login` | `/rizcard` (equipped card only; not the exchange list) | `{}` | `device_id`, `email`, `token` |

If every HTTP path for `/asyncombat` or `/weekly` returns 404, the bot opens a Socket.IO connection to the same pinned host (`rizline/socket.py`). `/rizcard` uses `rn_login` only. The handshake URL puts `email`, `token`, and `device_id` in the query string. TLS verification is on (`ssl_verify=True`). The socket URL is the constant `https://service.rhyths.net`.

`/rizcard` calls `fetch_equipped_rizcard` (a fresh `rn_login`) for the card you have equipped. It does not use `SyncOwnRizcards` / `fetch_own_rizcard`, which is the exchange inbox of other players’ cards. The image is sent through Discord and is not written into the score cache.

The CLI (`rizline/login.py`) still accepts `--base-url` after an HTTPS check. The bot does not expose that option.

This review did not connect to `service.rhyths.net`, so it does not establish who operates that host or what happens to credentials after a real login.

### Fixed since October 2026

1. **Redirects are refused.** `api_request` installs a redirect handler that raises `RizlineNetworkError` instead of following `Location`. The October client followed 301/302/303 and would have copied `device_id`, and on `game/rn_login` also `email` and `token`, to the new URL.
2. **Environment proxies are ignored** on the game client. The opener uses `ProxyHandler({})`.
3. **The bot pins the host.** Non-443 ports, userinfo, query strings, and fragments are rejected when `require_pinned_host=True`. `allow_http_localhost` exists so tests can use `http://127.0.0.1`.
4. **The bot does not write a full save.** `derive_minimal_cache` keeps the fields in section 3 and drops the rest of the decrypted save, including mail and purchases. The October CLI issue remains for `rizline/login.py` only.

### Still true

1. **Medium — CLI host override.** `--base-url` accepts any HTTPS origin. Redirects are no longer followed, so a redirect cannot carry the credential headers onward. A person who runs the CLI against the wrong host still sends the password to that host.
2. **Medium — decrypted save written to disk.** `rizline/login.py` writes `<player>_gameData.json`. It blanks `_id`, `userId`, and `mailSyncId` only. Mail, purchases, and the rest of the save remain. The pattern is gitignored. This update did not search the workspace or other disks for copies.
3. **Low — free-text secrets can survive `--debug`.** `redact()` replaces sensitive JSON keys and email-shaped strings. `scrub()` removes exact secret strings of length 4 or more. A server error that echoes a shorter secret, or a secret that is not an exact substring, can still be printed. Save responses are not JSON-logged.
4. **Game AES keys are hardcoded** in `rizline/client.py`. They are protocol keys shared by the game client, not a user password. Anyone with the ciphertext and these keys can decrypt a save. That is a property of the game format.

### Could not verify

- That `service.rhyths.net` is operated by the game publisher, or what that server does with credentials after a real login.
- Whether a password was exposed by an older copy of the script. The current client’s only game destination, when the bot calls it, is the pinned host. That is not proof an account is safe.
- The `Crypto.Cipher._raw_ctr` failure reported before October. `tests/test_api_client_mock.py` still covers a GCM round trip with `pycryptodome`. Reinstall only from PyPI.

## 2. Credential and token exposure

`/bind` collects the email and password, or the word `code` and then the email verification code, in a Discord modal. The modal submission is an interaction payload. It is not posted as a chat message. The bot’s reply is ephemeral and the account cog schedules that reply for deletion. Discord still processes the interaction under Discord’s own policies.

Verified by reading the current source, and by the tests named:

- Structured logging redacts emails, passwords, verification codes, tokens, and device ids (`tests/test_redaction.py`).
- `Session.__repr__` does not include the token or email.
- Passwords and email codes are not written by `Database`. The session token is written only as Fernet ciphertext in `sessions`. A copy also lives in `bot/services/sessions.py` until `/unbind`, expiry, auth failure, or process exit.
- Sessions last 14 days from the last successful `/bind`, `/refresh`, `/asyncombat`, `/weekly`, or `/rizcard` call. HTTP 401/403 clears the row. `/unbind` deletes it with the binding.
- There is no `on_message` handler. The process still requests the Message Content intent. Nothing in `bot/` reads message text.

Residual: a secret shorter than 4 characters is not scrubbed out of free text, because that would corrupt unrelated log lines. The password field is still replaced by `redact()`.

## 3. Local data protection

| Data | Where | Protection |
| --- | --- | --- |
| CLI decrypted save | `<player>_gameData.json` in the working directory | Gitignored (`*gameData*.json`). Not encrypted. |
| Bot score cache | `var/bot.db` table `score_cache.ciphertext` | Fernet. Gitignored via `/var/`. TTL default 24h. |
| Sharing flag | `var/bot.db` table `bindings` | Not secret. Discord id and a boolean. |
| Language preference | `var/bot.db` table `user_prefs` | Not secret. Survives `/unbind`. |
| Session token, email, and generated device id | `var/bot.db` table `sessions.ciphertext`, plus process memory while loaded | Fernet. TTL 14 days, refreshed on a successful live call. Cleared on `/unbind` or auth failure. |
| Encryption key | `BOT_ENCRYPTION_KEY` environment / `.env` | `.env` is gitignored. `.env.example` has no secret. The key is not written next to the database. |
| Song index | `bot/static/songs_index.json` | Public chart metadata. No account data. |
| GitHub token | `GITHUB_TOKEN` in `.env` | Used only by the owner command `/refresh-game-data`. Not a player credential. |

The score cache built by `derive_minimal_cache` contains:

- username, total RKS, `myBest`, `levelsRks`
- profile-card ids and avatar position
- achievement ids and unlock times
- owned `bio.`, `layout.`, `illustration.`, and `altIllustration.` ids
- a tutorial `challenge` / `challengeProgress` blob

The challenge blob is copied with a denylist of credential-like key names, not an allowlist of known fields. Asyncombat match history is not part of this cache. `/asyncombat`, `/weekly`, and `/rizcard` results are sent back through Discord and are not written into `score_cache`.

`tests/fixtures/sanitized_save.json` is a cache-shaped fixture. A search of that file found no `mails`, `email`, `password`, or `token` keys. It does contain a username and chart results.

Fernet (`cryptography.fernet`) detects tampering when the key is unknown (`InvalidToken`). It does not hide data from someone who has both `var/bot.db` and `BOT_ENCRYPTION_KEY`.

Compromise cases:

- **Database only:** ciphertext and Discord ids. Chart results are not readable without the key. Language and the sharing flag are readable.
- **Key only:** useless without the database (or another copy of the ciphertext).
- **Bot process or the host:** encryption at rest does not apply. The process holds the key, the plaintext cache, and any loaded session. `/bind` says this before the form opens.

Key loss: the cache cannot be decrypted. `/unbind` or deleting `var/bot.db` and running `/bind` again is the recovery. `Database.reencrypt_all(new_key)` decrypts with the current key and writes ciphertext for a new Fernet key. There is no Discord command for rotation. After rotating, restart the process with the new key. Losing the old key before rotation means the old rows are unreadable; delete them.

`/unbind` deletes the binding (SQLite `ON DELETE CASCADE` removes the cache and the encrypted session), runs `VACUUM`, and drops the in-memory session. The language row stays. The delete does not erase backups, editor swap files, crash dumps, or SSD spare blocks. The command text says so.

`.gitignore` covers `.env`, `*_gameData.json`, `/var/`, `/output/`, `/download/`, `/charts_info/`, and `/dist/`.

## 4. Discord authorization

Implemented in `bot/security/authz.py`. `dm_only` is an allowlist check. It does not require a DM.

- Commands are global. There is no `GUILD_ID`. Slash commands are allowed in servers, DMs, and group chats. A public invite is in `README.md` and `/help`: `https://discord.com/oauth2/authorize?client_id=1562086860988223568`.
- `ALLOWED_USER_IDS` is optional. Empty means anyone who can run the bot can use commands and bind their own Rizline account. A non-empty list restricts those commands to those Discord ids. `/help` does not use the check, so it still runs for everyone else. Help text has no score data.
- Open access lets a stranger spend Rizline API calls on this host through `/bind` and `/refresh`, and store an encrypted session here. The in-process rate limits below are the control. They reset when the process restarts. With a public invite, an empty allowlist is a public login proxy for the game API, not a private bot.
- `/profile` for another user succeeds only when that user has a live cache and `/share on`. Otherwise the reply is exactly `That result is not available.` The same string is used when the target is unbound, expired, or sharing off (`tests/test_authz.py`). Bound status is not stated in that text.
- Looking up yourself while unbound is a different message.
- `/b40`, `/recommend`, `/achievements`, `/asyncombat`, `/weekly`, and `/rizcard` always use the caller’s own session or cache. Sharing does not grant them.
- `/reload-data` and `/refresh-game-data` require `OWNER_ID` when set, otherwise the application owner when that owner is a user. A team-owned app must set `OWNER_ID`.
- `/bind` opens a modal in the channel where it was invoked. The modal accepts a submit only from that interaction. Allowlist failures are rejected in the modal handler when a list is set.

Residual side channel: `/profile` looks up the target row before choosing the message, so response timing can differ. The text does not. This was not closed with an artificial delay.

**Channel visibility.** `private` defaults to off. `/song`, `/random`, `/profile`, `/b40`, `/recommend`, `/achievements`, `/collection`, `/asyncombat`, `/weekly`, `/rizcard`, and `/refresh` post in the channel unless the caller sets `private`. A bound user’s `/song` or `/random` card includes their chart results. `/bind`, `/unbind`, and `/help` are always ephemeral. `/share` and `/language` post their confirmation in the channel. Error replies are ephemeral.

The October note that “`/song` is ephemeral when the caller has a cache” is no longer what the source does.

Rate limits (in-process, per Discord user, reset on restart):

| Action | Limit |
| --- | --- |
| `/bind` starts | 3 per 10 minutes |
| `/refresh` | 1 per 30 seconds |
| Song, score, and collection lookups | 10 per 30 seconds |
| `/asyncombat`, `/weekly`, and `/rizcard` | 4 per 30 seconds, shared |

There is no separate limit for modal submits.

## 5. Other network clients

**Game HTTP client:** redirects refused, environment proxy ignored, default TLS context. Tests look for `CERT_NONE`, `_create_unverified_context`, and `verify=False` without embedding those needles as contiguous strings in the assertion source.

**Socket client:** used only as the fallback for live rank and weekly-task calls. Same pinned host. Session email and token travel in the URL query string, so anything that logs that URL on the path to the host can record them. This review did not check the engine.io or websocket-client implementations beyond `ssl_verify=True` at the call site.

**GitHub dispatch** (`bot/services/github_actions.py`): owner-only `/refresh-game-data`, and only when the local pipeline cannot run. It POSTs to `https://api.github.com` with `urllib.request.urlopen` and a bearer token. That call uses the default opener, so it honors environment proxies and can follow redirects. The October redirect issue on the game client was closed; this path was not given the same handler. A redirect or an intercepting proxy can expose `GITHUB_TOKEN`. The workflow body is `{"ref": ...}` and does not include a player save.

**Not called by the running bot:** hosts in `tools/pipelines/Riz_bundle.py` and `index.html` (`rizserver.pigeongames.net`, `rizlineasset.pigeongames.net`, `rizastcdn.pigeongames.cn`, `dragonred.cn`, `riz.wiki`). Altare’s panel API is used by GitHub Actions, not by the bot process.

**Tests:** `http://127.0.0.1` only when the test passes `allow_http_localhost=True`.

## 6. Dependency integrity

| Package | Pinned in |
| --- | --- |
| `pycryptodome==4.1.0` | `requirements.txt` and `requirements-bot.txt` |
| `discord.py==2.7.1`, `cryptography==50.0.0`, `pillow==12.3.0`, `pytest==9.1.1`, `python-socketio==5.16.1`, `websocket-client==1.9.0`, and their dependencies | `requirements-bot.txt` |

`requirements-bot.txt` carries PyPI artifact hashes. Hashes detect a swapped file on a later install. They do not prove an older install on a machine was clean, and they do not review the upstream code.

## 7. Tests

| Test module | What it covers |
| --- | --- |
| `tests/test_redaction.py` | Fake email, password, code, and token in structured and debug output |
| `tests/test_api_client_mock.py` | Redirect not followed, malformed body, oversized body, non-JSON save, GCM round trip, pinned host, no TLS opt-out in source |
| `tests/test_storage_crypto.py` | Fernet round trip, tamper, missing key, wrong key, corrupt DB, TTL, canaries absent from the DB file, rotation |
| `tests/test_authz.py` | Cross-user denial, identical unavailable text, allowlist, registered command names |
| `tests/test_account_bind_modal.py` | Bind modal flow |
| `tests/test_rizline_socket.py` | Socket host check |
| `tests/test_github_actions.py` | Workflow dispatch helper |
| `tests/test_help.py` | Help text, including the public invite, and the private `/help` reply |

This update did not re-run the suite.

## 8. What this audit does not say

Do not bind a main account until you have read this file and decided the residual risks are acceptable: Discord’s copy of interactions, score cards posted in a channel when `private` is left off, a compromised host, the unverified game API operator, the socket URL query string, and `GITHUB_TOKEN` on the dispatch path. Prefer a test account for the first `/bind`.

If the bot is reachable through the public invite, set `ALLOWED_USER_IDS` unless you intend for every Discord user to be able to store a session on this host. If a main-account password was entered into a copy of the script you do not trust, changing it at the official service is a precaution, not a conclusion that it was stolen.
