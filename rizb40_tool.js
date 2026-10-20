const OUTPUT_REPORT_SUFFIX = "_rks_report.json";
const EPS = 1e-6;
const TRACK_RE = /\.\d+$/;
let songsData = null;
let trackMapping = null;
let constOverrides = {};

function normalize(s) {
    return s.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
}

function decodeHtmlEntities(str) {
    if (!str) return str;
    const textarea = document.createElement('textarea');
    textarea.innerHTML = str;
    return textarea.value;
}

function stripTrackPrefix(trackId) {
    return trackId.startsWith("track.") ? trackId.slice(6) : trackId;
}

function assetTitle(trackId) {
    let s = stripTrackPrefix(trackId);
    s = s.replace(TRACK_RE, '');
    const parts = s.split(".");
    return parts.length > 0 ? parts[0] : s;
}

function recordKey(trackId, diff) {
    return `${trackId}|${diff}`;
}

function parseFloatValue(s) {
    let t = String(s).trim().replace(/,/g, '');
    if (t.endsWith("+")) {
        t = t.slice(0, -1);
    }
    if (!t) return 0.0;
    return parseFloat(t) || 0.0;
}

function parseIntValue(s) {
    return Math.round(parseFloatValue(s));
}

function chartConst(trackId, diff, fallback, overrides) {
    const keys = [recordKey(trackId, diff), recordKey(stripTrackPrefix(trackId), diff)];
    for (const key of keys) {
        if (key in overrides) {
            return overrides[key];
        }
    }
    return fallback;
}

function computeH(mH, diff) {
    if (mH <= 0) return 0;
    let k = 0.98;
    if (diff === "EZ") k = 0.5;
    else if (diff === "HD") k = 0.9;
    if ((1 - k) * mH > 5) {
        return Math.ceil(k * mH - 1e-12);
    }
    return mH - 5;
}

function getAccRKS(cr) {
    if (cr >= 119.9999) return 10.5;
    if (cr >= 118) return 10.2;
    if (cr >= 116) return 9.9;
    if (cr >= 114) return 9.6;
    if (cr >= 112) return 9.3;
    if (cr >= 110) return 9.0;
    if (cr >= 105) return 8.25;
    if (cr >= 100) return 7.5;
    if (cr >= 95) return 6.75;
    if (cr >= 90) return 6.0;
    if (cr >= 80) return 4.5;
    if (cr >= 70) return 3.0;
    if (cr >= 60) return 1.5;
    return 0.0;
}

function rksFloat32Matches(a, b) {
    return Float32Array.from([a])[0] === Float32Array.from([b])[0];
}

function integrality(c, h, rks, acc) {
    if (c <= 0 || h <= 0) return [0.0, false];
    const x = h * (11 * c + acc - rks) / c;
    const nearest = Math.round(x);
    const ok = Math.abs(x - nearest) <= EPS && x >= -EPS && x <= h + EPS;
    return [x, ok];
}

function scoreRizPerfect(score) {
    const mP = Math.round((score - 1000000) / 100);
    return mP < 0 ? 0.0 : mP;
}

function expectedRKSIfHitFull(c, h, score, acc, observed) {
    if (c <= 0 || h <= 0 || score <= 0) return [0.0, false, false];
    const mP = scoreRizPerfect(score);
    const q = Math.min(mP, h);
    const expected = 10 * c + acc + c * q / h;
    return [expected, true, rksFloat32Matches(expected, observed)];
}

function rowToJsonItem(slot, r) {
    return {
        slot: slot,
        srcRank: r.sourceRank,
        trackId: r.trackId,
        rks: r.rks,
        diff: r.diff,
        const: r.const,
        title: r.title,
        ahStatus: r.ahStatus || 0,
        score: r.score
    };
}

function buildReportPayload(special5, ordinary35, overflow, avatarId = "", avatarPos = null, username = "", bioId1 = "", bioId2 = "", layoutId = "", backgroundId = "") {
    return {
        ah5: special5.map((r, i) => rowToJsonItem(i + 1, r)),
        b35: ordinary35.map((r, i) => rowToJsonItem(i + 1, r)),
        overflow: overflow.map((r, i) => rowToJsonItem(i + 36, r)),
        username: username || "",
        avatar: avatarId ? {
            id: avatarId,
            pos: avatarPos || { x: 0, y: 0, z: 1 }
        } : null,
        bioId1: bioId1 || "",
        bioId2: bioId2 || "",
        layoutId: layoutId || "",
        backgroundId: backgroundId || ""
    };
}

function buildRecords(data, songs, trackMapping, constOverrides) {
    const songsByNorm = {};
    for (const row of songs) {
        for (const key of [row.Page || "", row.Title || ""]) {
            const n = normalize(key);
            if (n) songsByNorm[n] = row;
        }
    }

    const addAlias = (alias, title) => {
        for (const row of songs) {
            if (row.Title === title || row.Page === title) {
                songsByNorm[alias] = row;
                return;
            }
        }
    };

    addAlias("houkagooverdrive", "Houkago OVERDRIVE!!!!! (Game ver.)");
    addAlias("linklins", "LINK x LIN＃S");
    addAlias("swingsweettweedance", "Swing Sweet Twee Dance feat. ななきなな");
    addAlias("bamboo", "竹");

    const songsByAssetId = {};
    for (const [key, value] of Object.entries(trackMapping)) {
        if (typeof value === 'string') {
            const song = songsByNorm[normalize(value)];
            if (song) songsByAssetId[key] = song;
            continue;
        }

        const song = songsByNorm[normalize(key)];
        if (song && value && value.id) {
            songsByAssetId[value.id] = song;
        }
    }

    const bestByKey = {};
    for (const b of data.myBest) {
        bestByKey[recordKey(b.trackAssetId, b.difficultyClassName)] = b;
    }

    const records = [];
    const missing = [];

    for (let idx = 0; idx < data.levels.length; idx++) {
        const level = data.levels[idx];
        const key = recordKey(level.trackId, level.difficultyClassName);
        const best = bestByKey[key];

        if (!best) {
            throw new Error(`missing myBest record for ${level.trackId} ${level.difficultyClassName}`);
        }

        const assetId = stripTrackPrefix(level.trackId);
        const assetName = assetTitle(level.trackId);

        let song = songsByAssetId[assetId];
        if (!song) song = songsByNorm[normalize(assetName)];
        if (!song) {
            missing.push(`#${idx + 1} ${level.trackId} (${assetName})`);
            continue;
        }

        const diff = level.difficultyClassName;
        const c = chartConst(level.trackId, diff, parseFloatValue(song[`${diff} Lv`]), constOverrides);
        const maxHit = parseIntValue(song[`${diff} Hit`]);
        const maxScore = parseIntValue(song[`${diff} Score`]);
        let rizHit = parseIntValue(song[`${diff} RizHit`]);
        if (rizHit === 0 && maxScore >= 1000000) {
            rizHit = Math.round((maxScore - 1000000) / 100);
        }

        const h = computeH(rizHit, diff);
        const acc = getAccRKS(best.completeRate);

        const [x, intPass] = integrality(c, h, level.rks, acc);
        const [expected, expectedKnown, expectedMatches] = expectedRKSIfHitFull(c, h, best.score, acc, level.rks);

        const confirmedAH = maxHit > 0 && rizHit === maxHit;
        const hitFullCompatible = intPass || (expectedKnown && expectedMatches);
        const ahStatus = confirmedAH ? 1 : (hitFullCompatible ? 2 : 0);

        records.push({
            sourceRank: idx + 1,
            trackId: level.trackId,
            title: decodeHtmlEntities(song.Title) || "",
            artist: decodeHtmlEntities(song.Artist) || "",
            diff: diff,
            rks: level.rks,
            score: best.score,
            completeRate: best.completeRate,
            isFullCombo: best.isFullCombo,
            isClear: best.isClear,
            const: c,
            maxHit: maxHit,
            rizHit: rizHit,
            h: h,
            accRKS: acc,
            integralityX: x,
            integralityPass: intPass,
            expectedRKS: expected,
            expectedRKSKnown: expectedKnown,
            expectedRKSMatches: expectedMatches,
            ahStatus: ahStatus,
            hitFullCompatible: hitFullCompatible,
            noMissCandidate: confirmedAH || hitFullCompatible
        });
    }

    return [records, missing];
}

function selectTop40(records) {
    const byRks = [...records].sort((a, b) => b.rks - a.rks);

    const confirmedAH = byRks.filter(r => r.ahStatus === 1);
    const possibleAH = byRks.filter(r => r.ahStatus === 2);

    const candidates = [];
    const selected = new Set();

    for (const r of confirmedAH) {
        if (candidates.length >= 5) break;
        const key = recordKey(r.trackId, r.diff);
        if (!selected.has(key)) {
            candidates.push(r);
            selected.add(key);
        }
    }

    for (const r of possibleAH) {
        if (candidates.length >= 5) break;
        const key = recordKey(r.trackId, r.diff);
        if (!selected.has(key)) {
            candidates.push(r);
            selected.add(key);
        }
    }

    candidates.sort((a, b) => b.rks - a.rks);

    const ordinary = [];
    const overflow = [];

    for (const r of byRks) {
        if (selected.has(recordKey(r.trackId, r.diff))) continue;
        if (ordinary.length < 35) {
            ordinary.push(r);
        } else if (overflow.length < 10) {
            overflow.push(r);
        } else {
            break;
        }
    }

    return [candidates, ordinary, overflow];
}

async function loadData(songs, mapping) {
    songsData = Array.isArray(songs) ? songs : songs?.cargoquery;
    if (!Array.isArray(songsData)) {
        throw new Error('songs.json must contain a song array or a cargoquery array');
    }
    if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping)) {
        throw new Error('mapping.json must contain an object');
    }
    trackMapping = mapping;
    console.log("B40 metadata loaded from local JSON files");
    return true;
}

function processUserData(rawData) {
    if (!songsData) {
        throw new Error('数据尚未加载完成');
    }

    const levelsRaw = rawData.levelsRks || [];
    if (!levelsRaw.length) {
        throw new Error("levelsRks is empty or missing");
    }

    const myBest = (rawData.myBest || []).map(item => ({
        trackAssetId: String(item.trackAssetId || ""),
        difficultyClassName: String(item.difficultyClassName || ""),
        score: parseIntValue(item.score || 0),
        completeRate: parseFloatValue(item.completeRate || 0),
        isFullCombo: Boolean(item.isFullCombo),
        isClear: Boolean(item.isClear)
    }));

    const levels = levelsRaw.map(item => ({
        trackId: String(item.trackId || ""),
        difficultyClassName: String(item.difficultyClassName || ""),
        rks: parseFloatValue(item.rks || 0)
    }));

    const avatarId = String(rawData.rizcard?.avatarId || rawData.avatarId || "");
    const avatarPos = rawData.rizcard?.avatarPos || rawData.avatarPos || { x: 0, y: 0, z: 1 };
    const username = String(rawData.username || "");
    const bioId1 = String(rawData.rizcard?.bioId1 || rawData.bioId1 || "");
    const bioId2 = String(rawData.rizcard?.bioId2 || rawData.bioId2 || "");
    const layoutId = String(rawData.rizcard?.layoutId || rawData.layoutId || "");
    const backgroundId = String(rawData.rizcard?.backgroundId || rawData.backgroundId || "");

    const userData = {
        myBest,
        levels,
        totalRks: parseFloatValue(rawData.totalRks || 0),
        avatarId,
        avatarPos,
        username,
        bioId1,
        bioId2,
        layoutId,
        backgroundId
    };

    const songsArray = songsData.cargoquery || songsData;
    const [records, missing] = buildRecords(userData, songsArray, trackMapping || {}, constOverrides);

    if (missing.length > 0) {
        console.log("警告：存在未匹配的曲目：");
        for (const item of missing) {
            console.log(`  ${item}`);
        }
    }

    const [special5, ordinary35, overflow] = selectTop40(records);
    const payload = buildReportPayload(special5, ordinary35, overflow, avatarId, avatarPos, username, bioId1, bioId2, layoutId, backgroundId);

    return payload;
}

function processUserDataFallback(rawData) {
    const levelsRaw = Array.isArray(rawData.levelsRks) ? rawData.levelsRks : [];
    const myBest = Array.isArray(rawData.myBest) ? rawData.myBest : [];
    if (levelsRaw.length === 0 || myBest.length === 0) {
        throw new Error("Save data must contain non-empty levelsRks and myBest arrays");
    }

    const bestByKey = new Map(
        myBest.map(item => [
            recordKey(String(item.trackAssetId || ""), String(item.difficultyClassName || "")),
            item
        ])
    );
    const records = [];
    for (const [index, level] of levelsRaw.entries()) {
        const trackId = String(level.trackId || "");
        const diff = String(level.difficultyClassName || "");
        const best = bestByKey.get(recordKey(trackId, diff));
        if (!trackId || !best) continue;
        records.push({
            sourceRank: index + 1,
            trackId,
            title: assetTitle(trackId),
            diff,
            rks: parseFloatValue(level.rks || 0),
            score: parseIntValue(best.score || 0),
            const: null,
            ahStatus: 0
        });
    }
    if (records.length === 0) {
        throw new Error("No matching entries found between levelsRks and myBest");
    }

    records.sort((a, b) => b.rks - a.rks);
    records.forEach((record, index) => {
        record.sourceRank = index + 1;
    });
    const [approximateAH5, ordinary35, overflow] = [
        records.slice(0, 5),
        records.slice(5, 40),
        records.slice(40, 50)
    ];
    const payload = buildReportPayload(
        approximateAH5,
        ordinary35,
        overflow,
        String(rawData.rizcard?.avatarId || rawData.avatarId || ""),
        rawData.rizcard?.avatarPos || rawData.avatarPos || { x: 0, y: 0, z: 1 },
        String(rawData.username || ""),
        String(rawData.rizcard?.bioId1 || rawData.bioId1 || ""),
        String(rawData.rizcard?.bioId2 || rawData.bioId2 || ""),
        String(rawData.rizcard?.layoutId || rawData.layoutId || ""),
        String(rawData.rizcard?.backgroundId || rawData.backgroundId || "")
    );
    payload.fallback = true;
    return payload;
}

async function refreshData() {
    if (!songsData || !trackMapping) {
        throw new Error('Select the folder containing songs.json and mapping.json before refreshing.');
    }
    return { success: true, source: 'local' };
}

window.Rizb40Tool = {
    loadData,
    refreshData,
    processUserData,
    processUserDataFallback,
    get isReady() { return songsData !== null; }
};