# Rizline Lookup

Unofficial Discord bot for the rhythm game Rizline. It looks up songs, series, and jacket art with no account. If you connect your own Rizline account, it can also show your scores, Best 40, score targets, achievements, collection progress, Asyncombat ranks, and weekly tasks.

It is a fan-made tool, run by one person. It is not affiliated with Pigeon Games or with Discord.

The operator does not own Rizline’s songs, charts, illustrations, or names. They stay with their copyright holders and are shown here only for score and song lookup. A copyright holder can ask for a removal through the [terms of service](docs/TERMS.md). The source code in this repository is AI-generated.

Using the bot means you agree to the [terms of service](docs/TERMS.md) and the [privacy policy](docs/PRIVACY.md).

**Add the bot:** https://discord.com/oauth2/authorize?client_id=1562086860988223568

## What you can do

Run `/help` in Discord for the short guide. The full list of what each command does, and how it gets its result, is in [COMMANDS.md](docs/COMMANDS.md).

**No account**

| Command | What it does |
| --- | --- |
| `/song` | A song and its charts. After you bind, your scores are drawn on the card |
| `/arts` | Jacket images, including Special arts |
| `/series` | One track series |
| `/random` | A random chart. You can set a difficulty and a level range |
| `/charts` | Charts between two constants |
| `/collection` | Bios, layouts, and arts. **Owned** and **Missing** need `/bind` |

**Your scores — `/bind` first**

| Command | What it does |
| --- | --- |
| `/bind` | Sign in with your Rizline email. Enter your password, or type `code` to get an email code. The form stays hidden |
| `/refresh` | Download your scores again after you play |
| `/profile` | Your RKS and top charts |
| `/b40` | Your AH5 and B35 as one image |
| `/recommend` | Score targets that raise your RKS |
| `/achievements` | Your achievement list |

**Live data — uses the login saved by `/bind`**

| Command | What it does |
| --- | --- |
| `/asyncombat` | Your current Asyncombat ranks |
| `/weekly` | Your weekly tasks |

The saved login lasts 14 days after a successful `/bind`, `/refresh`, `/asyncombat`, or `/weekly`. It is stored encrypted. Your password and email code are not saved.

**Account**

| Command | What it does |
| --- | --- |
| `/share on` | Let other people who use this bot open your `/profile` while your score cache is still valid |
| `/share off` | Stop that. This is the default |
| `/language` | Card language: English, 简体中文, 繁體中文, or 日本語 |
| `/unbind` | Delete your binding, cached scores, and saved login from this bot. Your language choice can remain; ask the operator if you want that deleted too |
| `/help` | This guide, visible only to you |

## How to use it

1. [Add the bot](https://discord.com/oauth2/authorize?client_id=1562086860988223568) to a server, or install it on your Discord account.
2. Use commands in that server, in a DM with the bot, or in a group chat.
3. Look up songs immediately. Bind an account only when you want your own scores.
4. Most replies show in the channel. Set `private` on a command when only you should see it. `/bind`, `/unbind`, and `/help` are always hidden. `/share` and `/language` confirm in the channel.
5. After you play, run `/refresh` before you expect new scores on `/profile`, `/b40`, or `/song`.

`/profile` is the only command that can show another person’s scores, and only when that person has turned `/share on` and their cache is still valid.

Questions: nightwind0112@gmail.com or Discord @nightwind.nightcat.

## Run your own copy

You need Python 3.12. From the repository root:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements-bot.txt
copy .env.example .env
```

Fill in `.env`:

- `DISCORD_TOKEN` from the Discord developer portal.
- `BOT_ENCRYPTION_KEY`, a Fernet key. Generate one with:

```powershell
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

In the developer portal, enable the **Message Content** intent. The bot requests it at login. Invite the bot with the `applications.commands` scope. Enable **User Install** if you want commands without a shared server. The first global command sync can take up to an hour to appear.

Then start the bot:

```powershell
py main.py
```

The song catalog shipped with the repo is `bot/static/songs_index.json`. Bindings and the encrypted score cache are stored in `var/bot.db`. Do not commit `.env` or `var/`.

Leave `ALLOWED_USER_IDS` empty to let anyone who can use the bot bind their own account. Set it to a comma-separated list of Discord user ids to limit the bot to those people. `/help` stays available either way.

`/reload-data` and `/refresh-game-data` are owner commands. Set `OWNER_ID` when the Discord application is team-owned. Hosting on Altare, including catalog refresh, is described in [DEPLOY_ALTARE.md](docs/DEPLOY_ALTARE.md).

Read [SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md) before you bind a main account on a copy you run yourself. If strangers can invite the bot, set `ALLOWED_USER_IDS`.

## Download a full save on your computer

The Discord bot keeps a short score cache, not a full save. A separate command logs in on your machine and writes a decrypted JSON file there. That file can contain mail and purchase data. It is not uploaded by the bot, and it should not be committed.

```powershell
py -m pip install -r requirements.txt
py rizline/login.py
```

## Tests

```powershell
py -m pytest
```

## Also in this repository

- `docs/` holds the command guide, terms, privacy policy, security audit, and Altare deploy notes.
- `tools/` maintains the song index, jacket art, and the Altare upload pack.
- `index.html` is a local Best 40 page that runs in a browser. The Discord bot is the maintained way to look up scores with other people.
