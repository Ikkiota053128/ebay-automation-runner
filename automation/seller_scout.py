"""お手本セラーの出品から型番を集めて、型番リストに足す（教科書 第3章「セラー起点のリサーチ」）。
11/28 09:08 オーナー「このセラーの出品参考になるから、セラーに追加して」（s.kojiro）。
- お手本セラーの一覧：data/型番リスト/お手本セラー.json {"本番": false, "セラー": [{"セラー": "s.kojiro", "メモ": …, "足した日時": …}]}
- eBay の Browse（即決・セラーで絞る・決めた大きいカテゴリごと）で、出品中の品の商品名を読む（eBay の画面は開かない。Sold は API で読めないので出品中だけ）。
- 商品名から メーカー＋型番 を読み（flea_sweep.guess_model・知らないメーカーは商品名の頭の英字）、
  $70 以上・決めごとA でない・付属品／ジャンク／本でない・大きい品でない・リールの大きさの記号でない・まだ型番リストに無い型番を足す。
- 本番 false はドライラン（足す予定だけ data/型番リスト/お手本セラーの結果.json と Discord に）。本番は data/型番リスト/追加.json に足す。
"""
import collections, os, re, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, notify, timetable, browse_stopped, num
import flea_sweep as fs
from flea_sweep import gas_get_models
from model_grow import BIG, mkey, size_code
from price_adjust import JUNK, BOOK, ACC
import judge

CFG_P = os.path.join(ROOT, "data", "型番リスト", "お手本セラー.json")
ADD_P = os.path.join(ROOT, "data", "型番リスト", "追加.json")
OUT_P = os.path.join(ROOT, "data", "型番リスト", "お手本セラーの結果.json")
CATS = {"625": "カメラ", "14324": "腕時計・宝飾", "293": "家電・オーディオ", "619": "楽器", "1492": "釣り"}


def main():
    tt = timetable("お手本セラー") or {}
    cfg = load_json(CFG_P, {"本番": False, "セラー": []})
    live = bool(cfg.get("本番"))
    mn = float(tt.get("最低の値段_ドル", 70))
    cap = int(tt.get("1回に足す上限_件", 60))
    eb = Ebay()
    if not eb.ready() or browse_stopped():
        print("鍵が無い・Browse が止まっている")
        return 0
    gas = gas_get_models() or load_json(os.path.join(ROOT, "data", "型番リスト", "GASの写し.json"), {"models": []})
    add = load_json(ADD_P, [])
    allm = list(gas.get("models") or []) + add
    fs.MAKERS.update(str(m.get("maker", "")).strip().upper() for m in allm if len(str(m.get("maker", "")).strip()) >= 3)
    have = {mkey(m.get("model")) for m in allm}
    global KNOWN
    KNOWN = set(fs.MAKERS)
    out = {"時刻": jst(), "本番": live, "セラー": {}, "足す": [], "見送り": collections.Counter()}
    found = {}
    for s in cfg.get("セラー", []):
        name = s["セラー"]
        n_items = 0
        for cid, cname in CATS.items():
            for page in range(int(tt.get("1カテゴリのページ_上限", 3))):
                try:
                    eb.browse_n += 1
                    import urllib.parse
                    prm = {"category_ids": cid, "filter": "sellers:{%s},buyingOptions:{FIXED_PRICE}" % name, "limit": 200, "offset": page * 200}
                    _, j = eb.call("GET", "/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(prm), kind="app",
                                   headers={"X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
                except EbayError as e:
                    out["見送り"]["Browse のエラー " + err_text(e)[:60]] += 1
                    break
                its = j.get("itemSummaries") or []
                n_items += len(its)
                for it in its:
                    t = it.get("title") or ""
                    price = num((it.get("price") or {}).get("value")) or 0
                    if judge.RULE_OUT.search(t):
                        out["見送り"]["決めごとA"] += 1
                        continue
                    if JUNK.search(t) or BOOK.search(t) or ACC.search(t) or BIG.search(t):
                        out["見送り"]["付属品・ジャンク・本・大きい品"] += 1
                        continue
                    if price < mn:
                        out["見送り"]["$%d 未満" % mn] += 1
                        continue
                    if re.search(r"\b(laptop|notebook|let's note|tablet|ipad|monitor|printer)\b", t, re.I):
                        out["見送り"]["パソコン・タブレットなど（店の種類でない）"] += 1
                        continue
                    # メーカーは商品名の頭の英字を先に（OLYMPUS … ZOOM のように後ろの言葉をメーカーにしない）
                    w = re.match(r"^([A-Za-z][A-Za-z\-]{2,})\s", t)
                    head = w.group(1).upper() if w else None
                    new_maker = bool(head) and head not in KNOWN
                    g = None
                    if head:
                        saved = set(fs.MAKERS)
                        fs.MAKERS.clear(); fs.MAKERS.add(head)
                        g = fs.guess_model(t)
                        fs.MAKERS.clear(); fs.MAKERS.update(saved)
                    if not g:
                        g = fs.guess_model(t)
                        new_maker = False
                    if not g:
                        out["見送り"]["型番が読めない"] += 1
                        continue
                    mk, md = g
                    if size_code(mk, md):
                        out["見送り"]["リールの大きさの記号"] += 1
                        continue
                    k = mkey(md)
                    if k in have:
                        out["見送り"]["もう型番リストにある"] += 1
                        continue
                    f = found.setdefault(k, {"maker": mk.title() if mk.isupper() and len(mk) > 4 else mk, "model": md, "値段": [], "例": t[:80],
                                             "cond": "新品" if "new" in str(it.get("condition", "")).lower() and "pre" not in str(it.get("condition", "")).lower() else "中古",
                                             "カテゴリ": cname, "新しいメーカー": new_maker, "セラー": name})
                    f["値段"].append(price)
                if len(its) < 200:
                    break
        out["セラー"][name] = {"出品中を読んだ": n_items}
    out["見つけた型番"] = len(found)
    picks = sorted(found.values(), key=lambda f: -statistics.median(f["値段"]))[:cap]
    for f in picks:
        out["足す"].append({"maker": f["maker"], "model": f["model"], "n": len(f["値段"]), "med": round(statistics.median(f["値段"]), 2), "例": f["例"],
                           "cond": f["cond"], "足した日時": jst(), "なぜ": "お手本セラー %s の出品（%s）%s" % (f["セラー"], f["カテゴリ"], "・新しいメーカー" if f["新しいメーカー"] else "")})
    out["見送り"] = dict(out["見送り"])
    if live and out["足す"]:
        save_json(ADD_P, add + out["足す"])
        cfg["最後に足した"] = jst()
        save_json(CFG_P, cfg)
    save_json(OUT_P, out)
    lines = ["%s %s（$%.0f・%s・%s）" % (a["maker"], a["model"], a["med"], a["cond"], a["なぜ"].split("（")[-1].rstrip("）")) for a in out["足す"][:25]]
    notify("【お手本セラー】%s %s：%s／型番リストに%s %d型番\n%s" % (jst(), "本番" if live else "ドライラン（まだ足していない）",
           "・".join("%s 出品中%d品" % (k, v["出品中を読んだ"]) for k, v in out["セラー"].items()), "足した" if live else "足す予定", len(out["足す"]), "\n".join(lines)))
    print("本番" if live else "ドライラン", out["セラー"], "足す", len(out["足す"]), out["見送り"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
