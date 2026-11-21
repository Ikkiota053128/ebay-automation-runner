"""eBay の出品の本当の値段（GetItem）と、オファーの値段を比べる（読むだけ・手で動かす）。
対象は data/値段の調整/本当の値段_対象.json（SKU の一覧）。結果は data/値段の調整/本当の値段_結果.json"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger

eb = Ebay()
want = set(load_json(os.path.join(ROOT, "data", "値段の調整", "本当の値段_対象.json"), []))
out = {"時刻": jst(), "品": []}
for r in read_ledger():
    if r.get("SKU") not in want:
        continue
    lid = r.get("eBayの出品ID")
    x = eb.trading("GetItem", "<ItemID>%s</ItemID><DetailLevel>ReturnAll</DetailLevel>" % lid)
    f = lambda t: (re.findall(r"<%s[^>]*>([^<]*)</%s>" % (t, t), x) or [""])[0]
    try:
        offs = [o for o in eb.offers_of(r["SKU"]) if o.get("status") == "PUBLISHED"]
        op = offs[0]["pricingSummary"]["price"]["value"] if offs else ""
        bo = (offs[0].get("listingPolicies") or {}).get("bestOfferTerms") if offs else {}
    except EbayError as e:
        op, bo = "読めず " + err_text(e)[:60], {}
    out["品"].append({"SKU": r["SKU"], "出品の値段": f("CurrentPrice"), "オファーの値段": op, "台帳の値段": r.get("売値(ドル)"),
                     "出品の状態": f("ListingStatus"), "出品の自動で断る値段": f("MinimumBestOfferPrice"), "オファーの値下げ交渉": bo})
save_json(os.path.join(ROOT, "data", "値段の調整", "本当の値段_結果.json"), out)
print("見た", len(out["品"]))
