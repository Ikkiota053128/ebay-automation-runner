"""在庫ゼロの品のうち、写真にほかの出品者の写真が混ざっている品を探す（読むだけ・手で動かす）。11/22 11:10 オーナー「はい」
結果は data/判定/在庫ゼロの混ざり.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, jst, read_ledger, save_json
import judge_list as jl
eb = Ebay()
out = {"時刻": jst(), "見た": 0, "混ざり": [], "混ざりなし": 0}
for r in read_ledger():
    if r.get("状態") != "在庫ゼロ" or r["SKU"].startswith("STK-") or not r.get("offerId"):
        continue
    try:
        cur = (eb.inventory_item(r["SKU"]).get("product") or {}).get("imageUrls") or []
    except EbayError:
        continue
    out["見た"] += 1
    s = [m.group(1) for m in (jl.SELLER_RX.search(u) for u in cur) if m]
    if len(set(s)) > 1:
        out["混ざり"].append({"SKU": r["SKU"], "タイトル": r.get("タイトル", ""), "売値": r.get("売値(ドル)"), "出品ID": r.get("eBayの出品ID"),
                            "仕入元URL": r.get("仕入元URL"), "写真": len(cur), "ほかの出品者の写真": len(s) - s.count(s[0])})
    else:
        out["混ざりなし"] += 1
save_json(os.path.join(ROOT, "data", "判定", "在庫ゼロの混ざり.json"), out)
print("見た", out["見た"], "混ざり", len(out["混ざり"]))
