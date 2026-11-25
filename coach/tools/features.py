"""ScoreSaber ★3 の譜面ファイル（.dat）から配置の特徴量を計算する。

入力: ss_star03_maps_20261125.json（{hash: {info, diffs: {"Standard/Hard": datText}}, bl: {...}}）
出力: features_star03.csv（1行＝1譜面×難易度）

方向（cutDirection）: 0上 1下 2左 3右 4左上 5右上 6左下 7右下 8ドット
type/c: 0=赤(左手) 1=青(右手)、v2 の type 3 は爆弾
"""
import csv, json, math, statistics as st, sys

# 方向 → 振る向きの角度（度）。上=90、右=0。ドットは None
ANG = {0: 90, 1: 270, 2: 180, 3: 0, 4: 135, 5: 45, 6: 225, 7: 315, 8: None}


def angdiff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def parse_notes(dat):
    """(time_beat, x, y, color, dir) のノーツと、(time, x, y) の爆弾を返す。v2/v3/v4 に対応。"""
    j = json.loads(dat)
    notes, bombs, chains, arcs = [], [], 0, 0
    if "_notes" in j:  # v2
        for n in j["_notes"]:
            t = n.get("_type")
            if t in (0, 1):
                notes.append((n["_time"], n["_lineIndex"], n["_lineLayer"], t, n["_cutDirection"]))
            elif t == 3:
                bombs.append((n["_time"], n["_lineIndex"], n["_lineLayer"]))
        arcs = len(j.get("_sliders", []) or [])
    elif "colorNotes" in j and j["colorNotes"] and "b" in j["colorNotes"][0]:  # v3
        for n in j["colorNotes"]:
            notes.append((n.get("b", 0), n.get("x", 0), n.get("y", 0), n.get("c", 0), n.get("d", 0)))
        for b in j.get("bombNotes", []) or []:
            bombs.append((b.get("b", 0), b.get("x", 0), b.get("y", 0)))
        chains = len(j.get("burstSliders", []) or [])
        arcs = len(j.get("sliders", []) or [])
    elif "colorNotes" in j:  # v4（ノーツ本体は colorNotesData に分離）
        data = j.get("colorNotesData", [])
        for n in j["colorNotes"]:
            dd = data[n.get("i", 0)] if data else {}
            notes.append((n.get("b", 0), dd.get("x", 0), dd.get("y", 0), dd.get("c", 0), dd.get("d", 0)))
        bdata = j.get("bombNotesData", [])
        for b in j.get("bombNotes", []) or []:
            bd = bdata[b.get("i", 0)] if bdata else {}
            bombs.append((b.get("b", 0), bd.get("x", 0), bd.get("y", 0)))
        chains = len(j.get("chains", []) or [])
        arcs = len(j.get("arcs", []) or [])
    notes.sort()
    bombs.sort()
    return notes, bombs, chains, arcs


def info_params(info_txt, ch, df):
    i = json.loads(info_txt)
    bpm = i.get("_beatsPerMinute") or (i.get("audio", {}) or {}).get("bpm") or 120
    njs = off = None
    if "_difficultyBeatmapSets" in i:
        for s in i["_difficultyBeatmapSets"]:
            if s["_beatmapCharacteristicName"] != ch:
                continue
            for b in s["_difficultyBeatmaps"]:
                if b["_difficulty"] == df:
                    njs, off = b.get("_noteJumpMovementSpeed"), b.get("_noteJumpStartBeatOffset")
    else:
        for b in i.get("difficultyBeatmaps", []):
            if b.get("characteristic") == ch and b.get("difficulty") == df:
                njs, off = b.get("noteJumpMovementSpeed"), b.get("noteJumpStartBeatOffset")
    return float(bpm), njs, off


def features(dat, info_txt, ch, df):
    bpm, njs, off = info_params(info_txt, ch, df)
    notes, bombs, chains, arcs = parse_notes(dat)
    if len(notes) < 10:
        return None
    sec = lambda b: b * 60.0 / bpm
    t0, t1 = sec(notes[0][0]), sec(notes[-1][0])
    dur = max(t1 - t0, 1e-6)
    f = {"bpm": bpm, "njs": njs, "offset": off, "notes": len(notes), "bombs": len(bombs),
         "chains": chains, "arcs": arcs, "play_sec": round(dur, 1),
         "nps": len(notes) / dur, "bombs_per_min": len(bombs) / dur * 60}

    # 同じ拍に複数ノーツ（同じ手）＝スタック/スライダー/ウィンドウ。振りとしては1回にまとめる
    swings = {0: [], 1: []}
    for c in (0, 1):
        hand = [n for n in notes if n[3] == c]
        i = 0
        while i < len(hand):
            grp = [hand[i]]
            while i + 1 < len(hand) and hand[i + 1][0] - grp[0][0] < 0.0626:  # 1/16拍未満は同時扱い
                i += 1
                grp.append(hand[i])
            swings[c].append(grp)
            i += 1
    f["left_share"] = sum(len(g) for g in swings[0]) / len(notes)
    f["multi_note_swing_share"] = sum(1 for c in (0, 1) for g in swings[c] if len(g) > 1) / max(1, sum(len(swings[c]) for c in (0, 1)))
    # 両手同時（ダブル）
    times = {}
    for n in notes:
        times.setdefault(round(n[0], 3), set()).add(n[3])
    f["double_share"] = sum(1 for s in times.values() if len(s) == 2) / len(times)

    # 振りごとの特徴（手ごと）
    gaps, resets, angle_changes, moves, fast = [], 0, [], [], 0
    dots = sum(1 for n in notes if n[4] == 8)
    bomb_resets = 0
    per_hand_gap = {0: [], 1: []}
    for c in (0, 1):
        sw = swings[c]
        for a, b in zip(sw, sw[1:]):
            ta, tb = sec(a[0][0]), sec(b[0][0])
            g = tb - ta
            if g <= 0:
                continue
            gaps.append(g)
            per_hand_gap[c].append(g)
            if g < 0.25:
                fast += 1
            da = next((ANG[n[4]] for n in a if ANG.get(n[4]) is not None), None)
            db = next((ANG[n[4]] for n in b if ANG.get(n[4]) is not None), None)
            if da is not None and db is not None:
                ad = angdiff(da, db)
                angle_changes.append(ad)
                if ad <= 45:  # 同じ向きに続けて振る＝リセット（振り戻しが必要）
                    resets += 1
                    if any(a[0][0] < bt[0] < b[0][0] for bt in bombs):
                        bomb_resets += 1
            # 位置の移動量（グリッド距離）
            moves.append(math.hypot(b[0][1] - a[-1][1], b[0][2] - a[-1][2]))
    nsw = max(1, len(gaps))
    f["swing_gap_median_s"] = st.median(gaps) if gaps else None
    f["swing_gap_p10_s"] = sorted(gaps)[len(gaps) // 10] if gaps else None
    f["fast_swing_share"] = fast / nsw  # 同じ手の振り間隔0.25秒未満の割合
    f["swings_per_sec"] = (len(gaps) + 2) / dur
    f["reset_share"] = resets / nsw
    f["bomb_reset_share"] = bomb_resets / nsw
    f["angle_change_mean"] = st.mean(angle_changes) if angle_changes else None
    f["angle_change_90_share"] = (sum(1 for x in angle_changes if 45 < x < 135) / len(angle_changes)) if angle_changes else None
    f["move_mean"] = st.mean(moves) if moves else None
    f["big_move_share"] = (sum(1 for m in moves if m >= 2) / len(moves)) if moves else None
    f["dot_share"] = dots / len(notes)

    # 位置と方向の分布
    xs = [n[1] for n in notes]
    ys = [n[2] for n in notes]
    f["top_row_share"] = sum(1 for y in ys if y == 2) / len(notes)
    f["bottom_row_share"] = sum(1 for y in ys if y == 0) / len(notes)
    f["outer_lane_share"] = sum(1 for x in xs if x in (0, 3)) / len(notes)
    cross = sum(1 for n in notes if (n[3] == 0 and n[1] >= 2) or (n[3] == 1 and n[1] <= 1))
    f["crossover_share"] = cross / len(notes)
    d = [n[4] for n in notes]
    f["up_share"] = sum(1 for x in d if x in (0, 4, 5)) / len(notes)
    f["horizontal_share"] = sum(1 for x in d if x in (2, 3)) / len(notes)
    f["diagonal_share"] = sum(1 for x in d if x in (4, 5, 6, 7)) / len(notes)
    # 内向き（左手が右へ／右手が左へ）の横振り＝手の甲側・バックハンド系
    f["inward_horizontal_share"] = sum(1 for n in notes if (n[3] == 0 and n[4] == 3) or (n[3] == 1 and n[4] == 2)) / len(notes)
    # 上段での切り上げ（手首を手の甲側に返す動きが大きい）
    f["top_upswing_share"] = sum(1 for n in notes if n[2] == 2 and n[4] in (0, 4, 5)) / len(notes)
    # 下段での切り下げ
    f["bottom_downswing_share"] = sum(1 for n in notes if n[2] == 0 and n[4] in (1, 6, 7)) / len(notes)
    # 手ごとの速さの偏り
    for c, name in ((0, "left"), (1, "right")):
        g = per_hand_gap[c]
        f[f"{name}_fast_share"] = (sum(1 for x in g if x < 0.25) / len(g)) if g else None
    return f


if __name__ == "__main__":
    src, out = sys.argv[1], sys.argv[2]
    d = json.load(open(src, encoding="utf-8"))
    rows, errs = [], []
    for h, m in d["maps"].items():
        for k, dat in (m.get("diffs") or {}).items():
            ch, df = k.split("/")
            if not dat:
                errs.append((h, k, "no dat"))
                continue
            try:
                f = features(dat, m["info"], ch, df)
            except Exception as e:  # noqa
                errs.append((h, k, repr(e)))
                continue
            if f:
                rows.append({"hash": h, "mode": ch, "difficulty": df, **f})
    cols = list(rows[0].keys())
    with open(out, "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("rows", len(rows), "errors", len(errs))
    for e in errs[:20]:
        print(" ", e)
