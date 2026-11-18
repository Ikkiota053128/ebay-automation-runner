"""型番リストを育てる（GAS の v358「シリーズの追加」・v293 と同じ考え方を GitHub で）。

- 種（もと）：最近売れた品（data/注文の記録 の SKU → 台帳のタイトルの型番）と、出品中の品の型番（毎回少しずつ順番に）。
- 種の型番のシリーズ（例：DW-5600 → 「Casio DW-」）を eBay（Browse・即決・中古）で探し、商品名に出てくる同じシリーズの型番を数える。
- 足す条件：3件以上・中央値 $70 以上・付属品／ジャンク／本の出品は数えない・型番が4つ以上並ぶ出品は数えない・
  大きい／重い品・ゲーム・キャラクター（決めごとA）は足さない・GAS の型番リストと GitHub の追加にまだ無い。
- 足した型番は data/型番リスト/追加.json。店の地引網・フリマの地引網は GAS のリストにこれを足して探す。
- 1回に足す上限・Browse の回数の上限は 時刻表 の「型番リストを育てる」。
"""
import collections, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, now, notify, load_json, save_json, read_ledger, timetable, write_run, mark_started, browse_stopped, num
from price_adjust import JUNK, BOOK, REF_ACC, ACC, model_of
from flea_sweep import gas_get_models
import judge

NAME = "型番リストを育てる"
BIG = re.compile(r"RB67|RZ67|PENTAX\s?67|PENTAX\s?6x7|Mamiya\s?7\b|6x7|4x5|Gimbal|Stabilizer|Tripod|Multiple Effects|Multi[- ]?Effects|"
                 r"ME-90|ME-80|ME-70|GT-1000|GT-100\b|GX-100|Pedalboard|Guitar Amp|Bass Amp|Cabinet|Subwoofer|Woofer|Drum Set", re.I)
ADD_P = os.path.join(ROOT, "data", "型番リスト", "追加.json")


# リールの「大きさの記号」（C3000HG・SW8000HG・LT2500S など）は、ステラ・ツインパワーなど別の製品で同じなので型番にしない
REEL_SIZE = re.compile(r"^(C|SW|LT|FC|CT)?-?\d{3,5}[A-Z]{0,4}$", re.I)


def size_code(maker, model):
    return bool(re.search(r"shimano|daiwa|abu|penn", str(maker), re.I)) and bool(REEL_SIZE.match(str(model).replace(" ", "")))


def mkey(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def series_of(model):
    m = re.match(r"^([A-Z]{1,4})([\s-]?)(\d)", str(model or "").upper().strip())
    return (m.group(1), m.group(2)) if m else None


def grow_one(eb, maker_en, model, have, st):
    ser = series_of(model)
    if not ser or not maker_en:
        return [], "シリーズの形ではない・メーカーが分からない"
    letters, sep = ser
    q = "%s %s%s" % (maker_en, letters, "-" if sep == "-" else "")
    items = eb.browse(q, "buyingOptions:{FIXED_PRICE},conditionIds:{3000|4000|5000|6000}", limit=200)
    rx = re.compile(r"(^|[^A-Z0-9])(" + letters + r"[\s-]?\d{1,5}[A-Z]{0,3})(?![A-Z0-9])", re.I)
    mk_rx = re.compile(re.escape(maker_en), re.I)
    by = {}
    for it in items:
        t = str(it.get("title", ""))
        if not mk_rx.search(t) or JUNK.search(t) or BOOK.search(t) or REF_ACC.search(t) or ACC.search(t):
            continue
        found = {}
        for m in rx.finditer(t):
            md = re.sub(r"\s", "-" if sep == "-" else "", m.group(2).upper())
            found.setdefault(mkey(md), md)
        if len(found) > 2:   # 対応機種の羅列
            continue
        p = num((it.get("price") or {}).get("value")) or 0
        for k, md in found.items():
            by.setdefault(k, {"md": md, "ps": [], "t": t})["ps"].append(p)
    out = []
    for k, v in by.items():
        ps = sorted(p for p in v["ps"] if p > 0)
        if len(ps) < 3 or k in have or len(k) < 4:
            continue
        med = ps[len(ps) // 2]
        if size_code(maker_en, v["md"]):
            continue
        if med < st["最低の中央値_ドル"] or BIG.search(v["t"] + " " + v["md"]) or judge.RULE_OUT.search(v["t"]):
            continue
        out.append({"maker": maker_en, "model": v["md"], "n": len(ps), "med": med, "例": v["t"][:80]})
    out.sort(key=lambda c: -c["n"])
    return out, q


def main():
    tt = timetable(NAME)
    st = {"最低の中央値_ドル": float(tt.get("最低の中央値_ドル", 70)), "1回に足す上限_件": int(tt.get("1回に足す上限_件", 40)),
          "1回に探すシリーズの数": int(tt.get("1回に探すシリーズの数", 30))}
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready() or browse_stopped():
        write_run(NAME, True, 0, 0)
        return 0
    rem = eb.browse_remaining() or {}
    if rem.get("remaining") is not None and int(rem["remaining"]) < int(tt.get("Browseの残りの下限", 1500)):
        print("Browse の残りが少ないので今回は休む")
        write_run(NAME, True, 0, 0)
        return 0
    gas = gas_get_models() or {"models": []}
    add = load_json(ADD_P, [])
    have = {mkey(m.get("model")) for m in gas["models"]} | {mkey(a["model"]) for a in add}
    makers = {}
    for m in gas["models"]:
        mk = str(m.get("maker", ""))
        if re.match(r"^[\x20-\x7E]+$", mk) and mk.strip():
            makers.setdefault(mkey(m.get("model")), mk.strip())
    led = read_ledger()
    # 種：最近売れた品 → 出品中の品（順番）
    seeds = []
    sold = {}
    import glob
    for f in glob.glob(os.path.join(ROOT, "data", "注文の記録", "*.json")):
        d = load_json(f, {})
        if d.get("SKU"):
            sold[d["SKU"]] = 1
    by_sku = {r["SKU"]: r for r in led}
    for s in sold:
        md = model_of((by_sku.get(s) or {}).get("タイトル"))
        if md:
            seeds.append((md, (by_sku[s].get("タイトル") or "").split()[0], "売れた"))
    act = [r for r in led if r.get("状態") == "出品中" and r.get("タイトル")]
    cur_p = os.path.join(ROOT, "data", "型番リスト", "順番.json")
    cur = load_json(cur_p, {"i": 0})
    i0 = cur["i"] % max(len(act), 1)
    for r in (act[i0:] + act[:i0]):
        md = model_of(r["タイトル"])
        if md:
            seeds.append((md, r["タイトル"].split()[0], "出品中"))
    done_ser, added, tried, why = set(), [], 0, collections.Counter()
    for md, mk, src in seeds:
        if tried >= st["1回に探すシリーズの数"] or len(added) >= st["1回に足す上限_件"]:
            break
        ser = series_of(md)
        if not ser:
            continue
        key = (mk.upper(), ser[0])
        if key in done_ser:
            continue
        done_ser.add(key)
        tried += 1
        if src == "出品中":
            cur["i"] = (cur["i"] + 1) % max(len(act), 1)
        try:
            cand, q = grow_one(eb, mk, md, have, st)
        except EbayError as e:
            why[err_text(e)[:60]] += 1
            break
        for c in cand:
            if len(added) >= st["1回に足す上限_件"]:
                break
            c.update({"cond": "中古", "足した日時": jst(), "なぜ": "%s の %s シリーズ（%s）・eBay %d件・中央値 $%.0f" % (src, ser[0], md, c["n"], c["med"])})
            add.append(c)
            added.append(c)
            have.add(mkey(c["model"]))
        time.sleep(0.5)
    save_json(ADD_P, add)
    save_json(cur_p, cur)
    msg = "【型番リストを育てる】%s シリーズ %d個を探して、型番を %d個足した（GitHubの追加 合計 %d個）%s" % (
        jst(), tried, len(added), len(add), ("：" + "・".join("%s %s($%.0f)" % (c["maker"], c["model"], c["med"]) for c in added[:15])) if added else "")
    print(msg)
    notify(msg)
    write_run(NAME, True, len(added), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
