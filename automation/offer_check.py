"""出品中の品の値下げ交渉（ベストオファー）がオンかを読むだけ（eBay は変えない）。
11/23 11:41 オーナー「オファーはオンになっているか確認して！」
結果は data/値下げ交渉/オンの確認.json（品ごとに オン/オフ・自動で断る値段・自動で受け入れる値段・今の値段）。"""
import os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger

eb = Ebay()
out = {"時刻": jst(), "品": {}, "まとめ": collections.Counter()}
for r in read_ledger():
    if r.get("状態") != "出品中" or r["SKU"].startswith("STK-"):
        continue
    oid = r.get("offerId")
    if not oid:
        out["品"][r["SKU"]] = {"結果": "offerIdなし（Inventory APIで見られない）"}
        out["まとめ"]["offerIdなし"] += 1
        continue
    try:
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + oid)
    except EbayError as e:
        out["品"][r["SKU"]] = {"結果": "読めない", "エラー": err_text(e)[:200]}
        out["まとめ"]["読めない"] += 1
        continue
    t = ((o.get("listingPolicies") or {}).get("bestOfferTerms") or {})
    on = bool(t.get("bestOfferEnabled"))
    price = float(((o.get("pricingSummary") or {}).get("price") or {}).get("value") or 0)
    dec = (t.get("autoDeclinePrice") or {}).get("value")
    acc = (t.get("autoAcceptPrice") or {}).get("value")
    k = "オン" if on else "オフ"
    if on and dec and float(dec) >= price:
        k = "オンだが断る値段が売値以上"
    out["品"][r["SKU"]] = {"結果": k, "売値": price, "自動で断る": dec, "自動で受け入れる": acc, "状態": o.get("status")}
    out["まとめ"][k] += 1
out["まとめ"] = dict(out["まとめ"])
save_json(os.path.join(ROOT, "data", "値下げ交渉", "オンの確認.json"), out)
print(out["まとめ"])
