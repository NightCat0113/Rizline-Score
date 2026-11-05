# Commands

How to use Rizline Lookup, then what each command does and where its result comes from.

Using the bot means you agree to the [terms of service](TERMS.md) and the [privacy policy](PRIVACY.md).

## How to use the bot

### 1. Add it

Open [this invite](https://discord.com/oauth2/authorize?client_id=1562086860988223568) and add the bot to a server, or install it on your Discord account.

Then type `/` in a server channel, a DM with the bot, or a group chat. Pick a command from the list. The first time after an update, a new command can take up to an hour to show up.

`/help` is the short version of this page. Only you can see that reply.

### 2. Look up a song

You do not need an account for this.

1. Type `/song`.
2. In `title`, start typing a song name and pick a suggestion.
3. Press Enter.

You get a card with the jacket and the charts. `/arts` is the same idea for jacket pictures. `/series` is one track series. `/random` picks a chart for you. `/charts` lists charts between two levels. `/collection` browses bios, layouts, and arts.

### 3. Show your own scores

Do this once:

1. Run `/bind`. The reply is hidden.
2. Press **Continue**.
3. Enter the email on your Rizline account, then your password.
4. If you would rather use email verification, type `code` instead of the password. When the mail arrives, press **Enter code** and submit the code. The code is not posted in the channel.

The bot signs in, keeps an encrypted login, and stores a score cache. Your password and the email code are not saved.

Then:

- `/profile` shows your RKS and top charts.
- `/b40` draws your AH5 and B35.
- `/song` draws your scores on the song card.
- `/recommend` suggests scores that would raise your RKS.
- `/achievements` lists what you have unlocked.
- `/collection` with **Owned** or **Missing** compares the catalog with what you have.
- `/asyncombat`, `/weekly`, and `/rizcard` ask the game for a live result. They need the saved login, not just the cache.

### 4. After you play

Run `/refresh` before you expect new numbers. The cache is kept for about 24 hours. The saved login lasts 14 days after a successful `/bind`, `/refresh`, `/asyncombat`, `/weekly`, or `/rizcard`. When it expires, `/bind` again.

### 5. Choose who can see the reply

A reply shows in the channel where you ran the command. Turn on `private` when only you should see that song card, Best 40, or rank image.

`/bind`, `/unbind`, and `/help` are always hidden. `/share` and `/language` post their confirmation in the channel.

Other people who use this bot cannot open your `/profile` unless you run `/share` and choose `on`. Sharing stays off until you turn it on. `/b40`, `/recommend`, `/achievements`, `/asyncombat`, `/weekly`, and `/rizcard` stay yours either way.

`/language` sets the words on the cards: English, 简体中文, 繁體中文, or 日本語.

### 6. Stop

Run `/unbind`. That deletes the binding, the score cache, and the saved login from this bot. Your language choice can remain. It does not delete the Rizline account.

Song lookups read a catalog stored with the bot. Score commands read the cache from the last `/bind` or `/refresh`. Live commands call the game with the saved login. Typing a song or series name offers suggestions as you type.

| Command | Needs | What you get |
| --- | --- | --- |
| `/song` | Nothing | Song card. Your scores appear on it after you bind |
| `/arts` | Nothing | Jacket images |
| `/series` | Nothing | Track-series card |
| `/random` | Nothing | One random chart |
| `/charts` | Nothing | A paged list of charts in a level range |
| `/collection` | Nothing to browse. `/bind` for Owned and Missing | Bios, layouts, or arts |
| `/bind` | Your Rizline email | A saved login and a score cache |
| `/refresh` | A saved login | An updated score cache |
| `/profile` | A fresh cache. Another person only if they used `/share on` | RKS and top charts |
| `/b40` | Your cache | AH5 and B35 image |
| `/recommend` | Your cache | Score targets that raise RKS |
| `/achievements` | Your cache | Achievement checklist |
| `/asyncombat` | A saved login | Live Asyncombat ranks |
| `/weekly` | A saved login | Live weekly tasks |
| `/rizcard` | A saved login | Live Rizcard image |
| `/share` | A binding | Sharing on or off |
| `/language` | Nothing | Card language |
| `/unbind` | Nothing | Deletes the binding, cache, and saved login |
| `/help` | Nothing | Short guide, only you can see it |

## `/song`

**Function.** Look up one song.

**What it does.** Sends a card with the title, charts, and jacket. Difficulties are EZ, HD, IN, AT, and SP when the song has them. If you are bound and the cache is still valid, your score, accuracy, and clear state are drawn on the charts you have played. If the card image cannot be built, the same facts are sent as text.

**How it works.** You pass `title`. The bot searches the local song index and uses the match. Suggestions appear while you type. Set `private` to hide the reply. Too many lookups in a short time are refused.

## `/arts`

**Function.** Show jacket art.

**What it does.** Sends the jacket images for a song, including Special art when that song has it.

**How it works.** You pass `title` or a Special art name. The bot resolves the name against the catalog and attaches the image files. Hi-res art is used when the host has those files. Set `private` to hide the reply.

## `/series`

**Function.** Look up one track series.

**What it does.** Sends a series card: name, volumes, and the songs in them. The words and the series poster follow your `/language` setting. If the image cannot be built, the same facts are sent as text.

**How it works.** You pass `name`. Suggestions appear while you type. This command does not draw your scores. Set `private` to hide the reply.

## `/random`

**Function.** Pick a chart at random.

**What it does.** Sends the same kind of song card as `/song`, with one difficulty highlighted. Your scores appear on the card when you are bound.

**How it works.** Every option is optional. `difficulty` is EZ, HD, IN, AT, or SP. `min` and `max` limit the chart constant from 1 to 20. The bot chooses one chart inside that filter from the local catalog. If nothing matches, it says so. Set `private` to hide the reply.

## `/charts`

**Function.** List charts between two constants.

**What it does.** Sends a paged list. Each page shows song titles and difficulties in the range you asked for. Buttons move between pages. Only the person who ran the command can press them, and the buttons stop working after a few minutes.

**How it works.** `min` and `max` are required, from 1 to 20. The order does not matter. `difficulty` is optional. The list comes from the local catalog, not from your scores. Set `private` to hide the reply.

## `/collection`

**Function.** Browse bios, layouts, or jacket arts.

**What it does.** Sends a paged image. Bios are text pills. Layouts and arts are a grid. If you are bound, owned items are marked and the caption shows how many you have. Buttons change the page. Only you can press them.

**How it works.** `type` is required: Bio, Layout, or Arts. `status` is All, Owned, or Missing. All works with no account and ignores ownership. Owned and Missing need a cache that includes collection data. If the cache is older than that feature, run `/refresh`. Set `private` to hide the reply.

## `/bind`

**Function.** Connect your Rizline account.

**What it does.** Stores an encrypted login and downloads a score cache: username, RKS, chart results, profile-card ids, achievements, owned collection ids, and tutorial challenge progress. The password and email code are used once and not saved.

**How it works.**

1. Run `/bind`. The reply is hidden.
2. Press **Continue**.
3. Enter the email on the Rizline account, and your password. Or type `code` instead of the password to get a verification email.
4. If a code was sent, press **Enter code** and submit the code from your inbox. The code is not posted in the channel.
5. The bot signs in at the game service, keeps the session, and stores the cache.

A later `/bind` replaces the old login. If the password is rejected, the bot can fall through to an email code. The form expires if you wait too long. Too many bind attempts in a few minutes are refused.

## `/refresh`

**Function.** Download your scores again.

**What it does.** Replaces the score cache with a new fetch, and tells you the username it updated. It also extends the saved login by 14 days.

**How it works.** The bot uses the encrypted session from `/bind`. It does not ask for the password again. If the game rejects the login, the session is deleted and you need `/bind` again. You can refresh once every 30 seconds. Set `private` to hide the “updated” reply. Run this after you play, before you expect new numbers on `/profile`, `/b40`, `/song`, `/recommend`, `/achievements`, or `/collection`.

## `/profile`

**Function.** Show RKS and the best charts.

**What it does.** Sends text: username, total RKS, record / clear / full-combo counts, and the top charts by RKS. A note is added when the cache is getting old.

**How it works.** With no `user`, it reads your cache. With `user`, it reads that person’s cache only if they turned `/share on` and the cache is still valid. Otherwise the reply is the same “not available” line whether they are unbound, expired, or sharing off. Set `private` to hide the reply.

## `/b40`

**Function.** Show your Best 40 as an image.

**What it does.** Renders the AH5 charts and the B35 charts from your cache onto one card. Labels follow `/language`.

**How it works.** It uses your cache only. Other people cannot open your `/b40` with `/share`. Set `private` to hide the image. If the image cannot be built, the command reports a generic failure.

## `/recommend`

**Function.** Find score targets that raise your RKS.

**What it does.** Sends a plan of charts where a higher score, with accuracy held as it is, would raise your overall RKS. Buttons page through the plan. Only you can press them.

**How it works.** It reads your cache. `increase` is optional, from 0.01 to 10. Leave it empty to ask for the largest score-only gain. `songs` is optional: titles separated by semicolons, with suggestions while you type. If those songs cannot reach the target, the bot says what the estimated maximum is. Set `private` to hide the reply.

## `/achievements`

**Function.** Browse your achievement checklist.

**What it does.** Sends a paged list of achievement names and how to unlock them, marked unlocked or locked from your cache. Buttons change the page. Only you can press them. The list language follows `/language`.

**How it works.** `status` is All, Unlocked, or Locked. The definitions come from the local catalog. Your unlocks come from the cache. An older cache asks you to `/refresh`. Set `private` to hide the reply.

## `/asyncombat`

**Function.** Show live Asyncombat ranks.

**What it does.** Sends an image of your current ranks. It is not read from the score cache, and it is not kept in the database after the reply is sent.

**How it works.** The bot calls the game with your saved login. A successful call extends that login by 14 days. If the session is missing or rejected, run `/bind` again. Set `private` to hide the image. Live lookups are rate-limited.

## `/weekly`

**Function.** Show weekly task progress.

**What it does.** Sends a paged list of this week’s tasks and how far you are. Buttons change the page. Only you can press them. Task text follows `/language`.

**How it works.** Same live login as `/asyncombat`. The result is not written into the score cache. Set `private` to hide the reply.

## `/rizcard`

**Function.** Show your live Rizcard.

**What it does.** Sends an image of the Rizcard you have equipped. The picture comes from the game at the moment you run the command. It is not read from the score cache, and it is not kept in the database after the reply is sent.

**How it works.** Same live login as `/asyncombat`. A successful call extends that login by 14 days. If the session is missing or rejected, run `/bind` again. Set `private` to hide the image. Live lookups are rate-limited.

## `/share`

**Function.** Let other bot users open your `/profile`, or stop that.

**What it does.** `on` allows `/profile` lookups of you while your cache is still valid. `off` is the default. Other commands on your account stay private either way. Scores you post in a channel by leaving `private` off are still visible there.

**How it works.** You must `/bind` first. The confirmation is posted in the channel, so people there can see whether sharing is on.

## `/language`

**Function.** Choose the language drawn on cards.

**What it does.** Sets English, 简体中文, 繁體中文, or 日本語 for series art and for words on `/song`, `/series`, `/b40`, `/collection`, `/asyncombat`, and `/weekly`.

**How it works.** The choice is stored for your Discord user. `/unbind` does not delete it. The confirmation is posted in the channel.

## `/unbind`

**Function.** Remove your account from this bot.

**What it does.** Deletes the binding, the encrypted score cache, and the saved login. The reply says whether anything was stored. It also says a normal database delete does not wipe backups or leftover disk copies. Your language choice remains until you ask the operator to delete it.

**How it works.** The reply is hidden, then removed shortly afterward. Nothing is sent to the game to close the Rizline account itself.

## `/help`

**Function.** Show the short in-Discord guide.

**What it does.** Sends the start steps, visibility rules, and the command list. Only you can see it. This file is the longer version.

## Owner commands

These are registered, and they answer only the bot owner. Everyone else is told the command is limited to the owner. Both replies are hidden.

### `/reload-data`

**Function.** Reload the song index already on disk.

**What it does.** Counts the songs it loaded. It does not download anything.

**How it works.** The process reads `bot/static/songs_index.json` again. Use it after that file has been replaced.

### `/refresh-game-data`

**Function.** Update the song catalog.

**What it does.** On a machine that can run the download tools, it runs the local pipeline and rebuilds the index. On a small host, it starts the GitHub Actions refresh workflow instead, when `GITHUB_TOKEN` and `GITHUB_REPOSITORY` are set. A second run is refused while one is already going.

**How it works.** Player accounts are not part of this command. New jacket files still have to be on the host before `/arts` can send them.
