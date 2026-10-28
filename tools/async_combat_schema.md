# Asyncombat, weekly tasks, and live Rizcard

## Verdict

Asyncombat (Weekly Challenge), weekly tasks, and the live Rizcard are **not** in `POST game/rn_login`. The Android client loads them over RhythNet Socket.IO on the pinned host:

`https://service.rhyths.net/websocket/pigeongames.rizline`

Socket.IO path used by this repo: `websocket/pigeongames.rizline/socket.io`. Transport is **websocket only**.

Do not render Asyncombat from save `challenge` / `challengeProgress`. That array is the eight Starter courses. Do not render `/rizcard` from the `rn_login` / score-cache `rizcard` object. `/b40` still uses that cache and is unchanged.

## Handshake (unauthenticated)

Probed without a game session. No tokens were sent.

| Request | Result |
| --- | --- |
| `GET /socket.io/?EIO=4\|3&transport=polling` | HTTP 404 `Cannot GET /socket.io/` |
| `GET /websocket/pigeongames.rizline/socket.io/?EIO=4&transport=polling` | HTTP 400 `{"code":0,"message":"Transport unknown"}` |
| Same path, `transport=websocket`, no upgrade | HTTP 400 `{"code":3,"message":"Bad request"}` |
| Raw TLS websocket upgrade, EIO 4 and EIO 3 | HTTP 502 from the load balancer |
| `python-socketio` Client, websocket only, no auth | `ConnectionError` |

Long-polling is disabled (`Transport unknown`). Authenticated websocket upgrades work at Engine.IO level; python-socketio's automatic `/` namespace join times out (`BadNamespaceError` / empty namespaces) in live bot tests.

`rizline_socket.py` uses **Engine.IO directly** (`websocket/pigeongames.rizline`, then `.../socket.io`), session on query string + headers, then Socket.IO packets as Engine.IO MESSAGE payloads. Because `engineio.Client.send` already adds MESSAGE type `4`, the app payloads are Socket.IO types only:

1. CONNECT `0` / `0{auth}` (on the wire: `40` / `40{auth}`)
2. EVENT `2<id>["<transaction>", body]` / `2["<transaction>", body]` (on the wire: `42…`)
3. same with event `message` / `request` / `SocketMessage`
4. raw JSON body

Body fields include `messageName`, `transactionName`, and `requestId`. Earlier bugs sent `40`/`42` into `send()`, which became invalid `440`/`442` on the wire.

The Android client loads these through `SendRequestToServer` / `SendRequestToServerWithJson` using the same `/game/` prefix as `rn_login`: `async_battle/rank_info`, `async_battle/info`, `get_weekly_tasks`, `fetch_own_rizcard` (body `serialAfter`), and `fetch_static_rizcard_progress`. Session headers include `device_id` and `device-id`. A non-404 HTTP error is returned as-is. Socket.IO is only the fallback when every one of those paths is HTTP 404. `claim_weekly_task_reward` is not called.

An authenticated response body was not captured in the first discovery session. `tools/inspect_async_stage.py` prints redacted key paths after interactive login.

## Request body

Each call is a Socket.IO ack (`Client.call`). The event is the transaction name, then `message`, then `request`, until one returns an object.

```json
{
  "messageName": "<transaction>",
  "transactionName": "<transaction>",
  "email": "<session>",
  "token": "<session>",
  "device_id": "<session>"
}
```

The first object ack is the payload. Secret keys are never written by the inspector.

## Transactions

| Command | Transactions (in order) |
| --- | --- |
| `/asyncombat` | `EnsureWeeklyPlayerInfo`, `RefreshWeeklyPlayerInfo` (errors ignored), then `GetWeeklyRankInfo` |
| `/weekly` | `GetWeeklyTasks` only. `ClaimWeeklyTaskReward` is not called. |
| `/rizcard` | `SyncOwnRizcards`, then `FetchStaticRizcardProgress`, then `OnGetStaticCard`. First object ack wins. |

## Weekly rank (`GetWeeklyRankInfo`)

`WeeklyRankInfoResult` fields from the APK metadata:

| UI | Field |
| --- | --- |
| Current | `currentRank` (`WeeklyRankData`) |
| Peak | `currentSeasonBestRank` |
| Initial | `currentSeasonStartingRank` |
| Season stats | `currentSeasonStats` |
| Lifetime stats | `lifetimeStats` |
| Recent matches | `recentMatches` |

`WeeklyRankData`: `segmentName` (Do through Do△), `stars`, `absStars`, `isPlus`, `potentialLevel`, `isPlaced`, `placementCount`, `placementResults`, `totalWin`, `totalLose`. A missing name uses numeric `segment` 0–7 as Do, Re, Mi, Fa, Sol, La, Si, Do△. The journey rail also shows a `+` tier for each of Do–Ti (`isPlus` / a trailing `+` on the name); Do△ is the final node and has no separate `+` step.

`WeeklyBattleStatisticsGroup`: `active` is Challenge, `passive` is Engage. Each side may use `playCount` / `matchCount`, `winCount`, `currentWinStreak`, `bestWinStreak`. The image shows the best streak when both are present.

Screen copy: `challenge.series.weekly` = Asyncombat; `currentRank` / `seasonBestRank` / `startRank`; `challenge` / `challenged`; `playCount` / `winCount` / `winStreakCount`.

## Weekly tasks (`GetWeeklyTasks`)

`GetWeeklyTasksResult` includes `weekIndex` and `nextRefreshAt`. Task rows are accepted under `tasks`, `weeklyTasks`, `items`, or `list` (also nested under `result` / `data`).

Per task, the mapper reads `id` / `taskId`, `progress` / `current`, `target` / `goal` / `need`, and `status` / `claimed` / `claimable` / `completed`. Status becomes `incomplete`, `complete`, `claimable`, or `claimed`.

English titles shipped with the client (`weeklyTask.<id>`):

| id | title |
| --- | --- |
| 100101 | Log in 3 days total |
| 100201 | Log in 2 consecutive days |
| 100301 | Play any track 5 times |
| 100401 | Clear any track 5 times |
| 100502 | Play Asyncombat 5 times |
| 100601 | Play any track with any MOD 2 times |
| 100701 | Accumulate 100 Dots |
| 100801 | Clear 3 different tracks in Main Discs |
| 100901 | Clear 3 different tracks in EX Discs |
| 101001 | Accumulate 3000000 score |
| 101101 | Accumulate 3000 Hits |
| 101201 | Total level of cleared charts reaches 15 |
| 101301 | Win 3 times in Asyncombat |
| 101401 | Get a 2-win Streak in Asyncombat |

## Own Rizcard

Accepted containers: `rizcard`, `card`, `staticCard`, `profile`, `ownRizcard`, the first `rizcards` item, and `result` / `data`. The renderer uses the same fields as the existing card art: `avatarId`, `avatarPos`, `bioId1`, `bioId2`, `backgroundId`, `layoutId`. Those values must come from the socket payload, not the score cache.

`OwnRizcardInfo` also has `cardSerial` and `exchangeTime`. `OwnStaticRizcardInfo` has `cardId`. `staticCard`, `readed`, and `maxRead` appear beside `FetchStaticRizcardProgress`.

## REST paths that are not this API

Live probe after sign-in: every guessed path returned HTTP 404.

`game/challenge`, `game/weekly`, `game/weekly_challenge`, `game/challenge_weekly`, `game/rn_challenge`, `game/rn_weekly`, `game/asyncombat`, `game/challenge/weekly`.
