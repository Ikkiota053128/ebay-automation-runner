"""出品中の品が、同じ型番・同じ状態の競合の中で何番目の安さかを読むだけ（eBay は変えない）。
11/23 14:10 オーナー「順位を調べて」（14:08「最安値か最安値から2番目の商品しか出さないで」）。
- 競合の外し方は判定（judge.quote）と同じ（付属品・ジャンク・本・外れ値を外す）。
- 品ごとに：今の売値・何番目か・最安・2番目・利益の下限の値段（フロア）・「下げれば最安／2番目に入れるか」。
結果は data/判定/順位の確認.json。"""
import os, sys, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger, settings, floor_price, num
import judge
from price_adjust import model_of


def filt(act0):
    act0 = sorted(x for x in act0 if x > 0)
    if not act0:
        return []
    mid = act0[(len(act0) - 1) // 2] if len(act0) >= 3 else 0
    act = [x for x in act0 if x >= mid * 0.5] if mid > 0 else act0[:]
    top = act0[len(act0) // 2:]
    um = top[(len(top) - 1) // 2] if top else 0
    med = act0[len(act0) // 2]
    ref = max(um, med)
    if ref > 0 and act:
        act = [x for x in act if x >= ref * 0.35] or [med]
    if len(act0) >= 5:
        act = [x for x in act if x >= med * 0.65] or [med]
        dr = 0
        while len(act) >= 3 and dr < 2 and act[0] < act[1] * 0.85 and act[0] < med * 0.7:
            act, dr = act[1:], dr + 1
    return act


cfg = settings()
eb = Ebay()
me = cfg.get("店", {}).get("セラー名", "").lower()
led = read_ledger()
my_ids = {r.get("eBayの出品ID") for r in led}
out = {"時刻": jst(), "品": {}, "まとめ": collections.Counter()}
rem = eb.browse_remaining() or {}
budget = max(0, int(rem.get("remaining") or 0) - 300)
for r in led:
    if r.get("状態") != "出品中" or r["SKU"].startswith("STK-"):
        continue
    if budget <= 0:
        out["品"][r["SKU"]] = {"結果": "検索の残りが少ないので見ていない"}
        out["まとめ"]["見ていない"] += 1
        continue
    md = model_of(r.get("タイトル"))
    price = num(r.get("売値(ドル)")) or 0
    if not md:
        out["品"][r["SKU"]] = {"結果": "型番が読めない", "売値": price}
        out["まとめ"]["型番が読めない"] += 1
        continue
    try:
        act0 = judge.comps(eb, md, int(num(r.get("eBayの状態ID")) or 3000), me, my_ids)
        budget -= 1
    except EbayError as e:
        out["品"][r["SKU"]] = {"結果": "読めない", "エラー": err_text(e)[:200]}
        out["まとめ"]["読めない"] += 1
        continue
    act = filt(act0)
    fp = floor_price(r, cfg)
    if not act:
        out["品"][r["SKU"]] = {"結果": "競合なし", "売値": price, "型番": md}
        out["まとめ"]["競合なし（1番）"] += 1
        continue
    rank = 1 + sum(1 for x in act if x < price - 0.005)
    L, L2 = act[0], (act[1] if len(act) > 1 else None)
    can = None
    if fp:
        if fp <= round(L - 1, 2):
            can = "最安にできる（$%.2f）" % round(L - 1, 2)
        elif L2 and fp < L2:
            can = "2番目にできる（$%.2f）" % fp
        else:
            can = "下限の値段でも3番目以下"
    k = "1番" if rank == 1 else ("2番" if rank == 2 else "3番目以下")
    out["品"][r["SKU"]] = {"結果": k, "順位": rank, "競合の数": len(act), "売値": price, "最安": L, "2番目": L2,
                          "フロア": fp, "下げると": can, "型番": md, "出品ID": r.get("eBayの出品ID")}
    out["まとめ"][k] += 1
    if k == "3番目以下":
        out["まとめ"]["3番目以下で " + (can or "フロアが計算できない")[:10]] += 1
out["まとめ"] = dict(out["まとめ"])
save_json(os.path.join(ROOT, "data", "判定", "順位の確認.json"), out)
print(out["まとめ"])
