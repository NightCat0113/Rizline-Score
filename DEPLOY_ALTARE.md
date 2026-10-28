# Deploy Rizline Lookup on Altare

Altare host guide: [deploy a discord.py bot](https://altare.gg/en/help/discord-bots/deploy-python-bot).

## 1. Pack the upload

From the repo root on your PC:

```powershell
python tools/pack_altare.py
```

That writes `dist/rizline-altare.zip` with code, `locale/`, the song index, the font, `output/illust`, and `output/series`. It does **not** include `.env`, `var/bot.db`, `download/`, or HiRes jackets.

For sharper song art (much larger upload):

```powershell
python tools/pack_altare.py --hires
```

## 2. Create the Altare server

1. Open [console.altare.gg](https://console.altare.gg).
2. Create a server from the **Python** template.
3. Give it **1024 MB** memory to start (Pillow + `/b40` cards need more than a tiny bot). Raise later if Resources shows pressure.
4. Prefer Python **3.12** if the template lets you pick a version.

## 3. Upload and extract

1. Open the server’s file manager.
2. Upload `dist/rizline-altare.zip`.
3. Extract it so `main.py`, `requirements.txt`, `bot/`, and `rizline/` sit in the **server root** (not inside an extra folder).
4. Delete the zip afterward to free disk.

## 4. Create `.env` on the server

In the server root, create `.env` (never commit this file):

```txt
DISCORD_TOKEN=your-discord-bot-token
BOT_ENCRYPTION_KEY=your-fernet-key
ALLOWED_USER_IDS=
CACHE_TTL_HOURS=24
OWNER_ID=
```

Generate a Fernet key locally if you need a new one:

```powershell
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

If you reuse an existing `var/bot.db` from your PC, you **must** use the same `BOT_ENCRYPTION_KEY` or the score cache will not decrypt. Prefer starting with an empty `var/` and running `/bind` + `/refresh` on the server.

## 5. Startup settings

1. Set the main / app file to `main.py`.
2. Confirm the requirements file points at `requirements.txt` (the pack script already puts a copy next to `main.py`).
3. Start the server and watch the console for pip install, then:

   `Logged in as …`

## 6. Discord portal checklist

- Message Content intent enabled (needed for `/bind` DM replies).
- Bot invited / user-installable the way you already use locally.
- Application name can be set to **Rizline Lookup** in the developer portal.
- After the first deploy, global slash commands can take up to an hour to appear in DMs.

## What not to upload

| Path | Why |
| --- | --- |
| `.venv/`, `__pycache__/` | Not portable; Altare installs from `requirements.txt` |
| `.env` from git | Secrets — create on the server |
| `download/` | ~GB of raw game bundles |
| `output/illust_HiRes/` | Optional; use `--hires` only if you want it |
| `tests/`, `.pytest_cache/` | Not needed at runtime |

## Updating later (GitHub main → Altare → Discord)

After the first install, a push to `main` deploys code and restarts the bot. Altare has no git pull; [`.github/workflows/deploy-altare.yml`](.github/workflows/deploy-altare.yml) first runs safety checks (compile, pytest, code-only zip contents), then packs a code-only zip and uses the Altare client API to upload it, extract it, delete the zip, and restart. Deploy is skipped if those checks fail. Startup runs `main.py`, which syncs slash commands. Global command changes can still take up to an hour to show up in Discord.

The code-only zip refreshes `bot/`, `rizline/`, `locale/`, `songs.json`, `mapping.json`, `main.py`, and `requirements.txt`. It does **not** replace:

- `.env`
- `var/` (encrypted score cache)
- `output/` (jackets and series art)
- `assets/fonts/` (the card font)

### One-time secrets

In the GitHub repo: **Settings → Secrets and variables → Actions**.

| Secret | Value |
| --- | --- |
| `ALTARE_API_KEY` | API key from the Altare console |
| `ALTARE_SERVER_ID` | The server’s short id |

Until both secrets exist, the workflow fails on purpose and does not touch the server.

### Day to day

1. Commit on `main` and `git push origin main` (or run the **Deploy Altare** workflow by hand).
2. Watch the Actions run, then the Altare console for `Logged in as …`.
3. Stop the copy of the bot on your PC once Altare is the live host, so two processes do not share one token.

Manual full packs (`python tools/pack_altare.py`) are only for the first install or when art or the font on the server needs replacing. Extract those over the tree and keep `.env` and `var/`.
