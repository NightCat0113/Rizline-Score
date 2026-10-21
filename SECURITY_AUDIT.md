# Rizline login and Discord bot — security audit

Date: 2026-10-20. Scope: `rizline_login.py` as it existed before the client extraction (direct `urllib.request.urlopen`), plus the bot built from that review. No live login was performed. No real Rizline credentials or session tokens were used. Passing the tests in `tests/` does not mean this program is safe.

Line numbers below refer to the pre-extraction `rizline_login.py` (415 lines) unless a new file is named.

## How to read this report

- **Verified:** observed in the source that was reviewed, or reproduced with fake secrets and a local mock server.
- **Suspicious:** looks risky, but this review did not prove exploitation.
- **Could not verify:** not checked, or cannot be checked without a live service, the original process, or another machine.

## 1. Login client

`rizline_login.py` made only these outbound calls, all `POST`, all to `base_url + path`:

| Path | When | Body fields | Extra headers |
| --- | --- | --- | --- |
| `account/login` | Passcode | `email`, `password` | `device_id` |
| `account/send_email` | Email-code fallback | `email`, `transaction=login` | `device_id` |
| `account/login` | Email code | `email`, `code` | `device_id` |
| `game/rn_login` | After login | `{}` | `device_id`, `email`, `token` |

The only hardcoded host was `https://service.rhyths.net` (`DEFAULT_BASE_URL`). `--base-url` could replace it after an `https` scheme check. The reviewed run did not pass `--base-url`, so that override was not exercised. This review did not connect to the host, so it does not establish that the host is the official game service.

### Verified issues

1. **High — redirect forwards credential headers.** `urlopen` (line 168) uses the stdlib opener. In CPython 3.12 `urllib.request.HTTPRedirectHandler.redirect_request`, a `POST` that receives `301`, `302`, or `303` is followed. The new request copies the original headers except `Content-Length` and `Content-Type`, and drops the body. `307`/`308` on `POST` are not followed (the handler raises `HTTPError`). A login or save response that redirects would send `device_id`, and on `game/rn_login` also `email` and `token`, to the `Location` URL. The passcode body would not be resent for 301/302/303.
2. **Medium — ambient proxies are honored.** The default opener installs `ProxyHandler`, which reads `http_proxy` / `https_proxy`. A proxy pointed at by the environment can observe the destination host. A TLS-intercepting proxy can observe the body. Nothing in the old client disabled this.
3. **Medium — CLI host override.** `--base-url` accepted any HTTPS origin. Combined with issue 1, a mistaken or hostile base URL plus a redirect is a credential-forwarding path. The bot does not expose this option.
4. **Medium — decrypted save written to disk.** After a successful fetch the CLI wrote `<player>_gameData.json`. It blanked `_id`, `userId`, and `mailSyncId` only. `mails`, purchases, and the rest of the save remained. `NightXWind_gameData.json` in the repo root is that kind of file. It is gitignored and was not in `git ls-files` or `git log --all`. The only `*gameData*` file found in the workspace is that one. Other backups outside the workspace were not searched.
5. **Low — free-text secrets can survive `--debug`.** `redact()` replaces sensitive JSON keys (`email`, `password`, `code`, `token`, `device_id`, and the rest of `SENSITIVE_FIELDS`) and email-shaped strings. A server error string that echoes the passcode itself would still be printed. Debug also used to offer a ciphertext hex prefix (`log_binary_prefix`). Response bodies of the save request were not JSON-logged.

### Suspicious

- **Game AES keys are hardcoded** (old lines 31–33, now `rizline_client.py`). They are protocol keys shared by the game client, not this user's password. Anyone with the ciphertext and these keys can decrypt a save. That is a property of the game format, not evidence of a backdoor in this file.
- **`Riz_bundle.py` and `index.html` talk to other hosts** (`rizserver.pigeongames.net`, `rizlineasset.pigeongames.net`, `rizastcdn.pigeongames.cn`, `dragonred.cn`, `riz.wiki`). The bot does not import or call them. They matter only if you run those tools.

### Could not verify

- That `service.rhyths.net` is operated by the game publisher, or what that server does with credentials after a real login.
- That the historical run used this exact file and an unmodified interpreter.
- The `Crypto.Cipher._raw_ctr` failure reported earlier. On this machine `pycryptodome` 4.1.0 imports `Crypto.Cipher.AES` and a GCM round trip succeeds (`tests/test_api_client_mock.py`). Reinstall only from PyPI. Do not replace DLLs from other sites.
- Whether a passcode was previously exposed. This audit found no destination in the login file other than the configured API host. That is not proof the account is safe.

### Remediation in `rizline_client.py`

- Redirects raise `RizlineNetworkError` and are not followed.
- The opener uses `ProxyHandler({})` so environment proxies are ignored.
- TLS uses `ssl.create_default_context()`. There is no `CERT_NONE`, `_create_unverified_context`, or `verify=False` in the project sources (tests construct those needles without embedding them as contiguous strings).
- The bot calls the client with `require_pinned_host=True` and `https://service.rhyths.net` only. Non-443 ports, userinfo, query strings, and fragments are rejected. `allow_http_localhost` exists only so tests can bind `127.0.0.1`; `bot/` does not reference it.
- The CLI still accepts `--base-url` for the old HTTPS-only workflow, and now uses the same redirect and proxy rules.
- Save responses are not debug-logged. Debug text is passed through `redact()` and `scrub()` for exact secret strings of length 4 or more.
- The bot never writes `*_gameData.json`. It derives `username`, `totalRks`, `myBest`, `levelsRks`, and the profile-card fields `avatarId`, `avatarPos`, `bioId1`, `bioId2`, `backgroundId`, and `layoutId`, then drops the rest.

## 2. Credential and token exposure

Verified with fake values in `tests/test_redaction.py` and `tests/test_api_client_mock.py`:

- Structured logging redacts emails, passcodes, verification codes, tokens, and device ids.
- `Session.__repr__` does not include the token or email.
- The bot's DM handler does not echo the reply, does not put the reply in the log message, and sends a generic failure string to Discord.
- Passcodes and email codes are not written by `Database`. The session token is not written to SQLite (asserted with a canary). Tokens live in `bot/services/sessions.py` until `/unbind` or process exit.

The audit does **not** approve storing session tokens at rest. Opt-in token persistence from the plan is not implemented.

Residual: Discord stores the DM the user sends. The bot cannot delete another person's DM. `/bind` says that before asking for the email. Very short secrets (under 4 characters) are not scrubbed out of free text, because that would corrupt unrelated log lines; the password field is still replaced by `redact()`.

## 3. Local data protection

| Data | Where | Protection |
| --- | --- | --- |
| CLI decrypted save | `<player>_gameData.json` in the working directory | Gitignored (`*gameData*.json`). Not encrypted. |
| Bot score cache | `var/bot.db` table `score_cache.ciphertext` | Fernet. Gitignored via `/var/`. TTL default 24h. |
| Sharing flag | `var/bot.db` table `bindings` | Not secret. Discord id and a boolean. |
| Session token and email | Process memory only | Gone on restart, `/unbind`, or process compromise. |
| Encryption key | `BOT_ENCRYPTION_KEY` environment / `.env` | `.env` is gitignored. `.env.example` has no secret. The key is not written next to the database. |
| Song index | `bot/static/songs_index.json` | Public chart metadata. No account data. |
| Test fixture | `tests/fixtures/sanitized_save.json` | Username, total RKS, `myBest`, `levelsRks` only. No mails or account ids. |

Fernet (`cryptography.fernet`) detects tampering when the key is unknown (`InvalidToken`). It does not hide data from someone who has both `var/bot.db` and `BOT_ENCRYPTION_KEY`.

Compromise cases:

- **Database only:** ciphertext and Discord ids. Chart results are not readable without the key.
- **Key only:** useless without the database (or another copy of the ciphertext).
- **Bot process or the host:** encryption at rest does not apply. The process holds the key, the plaintext cache, and any in-memory session. This is stated in the `/bind` DM.

Key loss: the cache cannot be decrypted. `/unbind` or deleting `var/bot.db` and running `/bind` again is the recovery. `Database.reencrypt_all(new_key)` decrypts with the current key and writes ciphertext for a new Fernet key. There is no Discord command for rotation, so a stolen key cannot be swapped from chat. After rotating, restart the process with the new key. Losing the old key before rotation means the old rows are unreadable; delete them.

`/unbind` deletes the binding (SQLite `ON DELETE CASCADE` removes the cache), runs `VACUUM`, and drops the in-memory session. That does not erase backups, editor swap files, crash dumps, or SSD spare blocks. The command text says so.

`.gitignore` covers `.env`, `*_gameData.json`, `/var/`, `/output/`, `/download/`, and `/charts_info/`.

## 4. Discord authorization

Implemented in `bot/security/authz.py` and called from the slash commands (not only hidden UI):

- Commands are global and DM-only. There is no `GUILD_ID`. A command used in a server gets `Use this command in a DM with the bot.` The guild boundary was removed on purpose.
- `ALLOWED_USER_IDS` is optional. Empty means anyone who can DM the bot can use commands and bind their own Rizline account. A non-empty list restricts every command, including `/bind` replies, to those Discord ids.
- Open access lets a stranger spend Rizline API calls on this host through `/bind` and `/refresh`. The in-process rate limits below are the control. This is accepted for a private deployment and is not enough if the bot is listed publicly.
- `/score` and `/profile` for another user succeed only when that user has a live cache **and** `/share on`. Otherwise the reply is exactly `That result is not available.` The same string is used when the target is unbound, expired, or sharing off (`tests/test_authz.py`). Bound-status is not stated in that text.
- Looking up yourself while unbound is a different message, because that does not reveal anyone else's status.
- `/reload-data` requires `OWNER_ID` when set, otherwise the application owner when that owner is a user. A team-owned app must set `OWNER_ID`.
- `/bind` runs in the DM where it was invoked. It accepts replies only while a bind started by that user is pending, and only if they pass the allow list when one is set.

Residual side channel: the handler does look up the target row before choosing the message, so response timing can differ. The text does not. This was not closed with an artificial delay.

Personal-data replies are ephemeral. `/song` is ephemeral when the caller has a cache, because the embed then includes their scores.

Rate limits (in-process, reset on restart): `/bind` 3 starts per 10 minutes, 8 DM replies per minute, `/refresh` 1 per 30 seconds, lookups 10 per 30 seconds.

## 5. Dependency integrity

| Package | Pinned in |
| --- | --- |
| `pycryptodome==4.1.0` | `requirements.txt` and `requirements-bot.txt` |
| `discord.py==2.7.1`, `cryptography==50.0.0`, `pytest==9.1.1`, and their dependencies | `requirements-bot.txt` |

`requirements-bot.txt` carries PyPI artifact hashes from `pip-compile --generate-hashes` (or, if that file lists hashes, pip checks them on install). Hashes detect a swapped file on a later install. They do not prove the historical install on this PC was clean, and they do not review the upstream code.

The `_raw_ctr` symptom was not reproduced here. No replacement crypto binaries were downloaded outside pip.

## 6. External network destinations

**Bot / login client, runtime:** `https://service.rhyths.net` only (`account/login`, `account/send_email`, `game/rn_login`), plus Discord's API via `discord.py` when the bot is logged in.

**Not used by the bot:** hosts in `Riz_bundle.py` and `index.html` listed above.

**Tests:** `http://127.0.0.1` only, and only when the test passes `allow_http_localhost=True`.

## 7. Tests

| Test module | What it covers |
| --- | --- |
| `tests/test_redaction.py` | Fake email, passcode, code, token in structured and debug output |
| `tests/test_api_client_mock.py` | Redirect not followed, malformed body, oversized body, non-JSON save, GCM round trip, pinned host, no TLS opt-out in source |
| `tests/test_storage_crypto.py` | Fernet round trip, tamper, missing key, wrong key, corrupt DB, TTL, canaries absent from the DB file, rotation |
| `tests/test_authz.py` | Cross-user denial and identical unavailable text |
| `tests/test_songdata.py` | Search, aliases, autocomplete length |
| `tests/test_rks.py` | RKS helpers and B40 selection on the sanitized fixture |

## 8. What this audit does not say

Do not bind a main account until you have read this file and decided the residual risks (Discord DM history, host compromise, unverified API operator) are acceptable. Prefer a test account for the first `/bind`. If a main-account passcode was entered into a copy of the script you do not trust, changing it at the official service is a precaution, not a conclusion that it was stolen.
