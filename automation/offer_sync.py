"""オファーと出品の値段がずれた品を合わせる（手で動かす）。11/21 17:47 オーナー「1〜3お願いします」（3）
値段の調整で、オファーの値段は下がったのに、値下げ交渉の「自動で断る値段」に当たって（25016）出品の値段が変わらなかった品。
対象 data/値段の調整/本当の値段_対象.json。オファーを読み、値下げ交渉を「最低利益の値段がオファーの値段より $0.01 以上安いときだけ」に直して
オファーを保存（出品も直る）→ GetItem で出品の値段がオファーと同じか確かめる → 同じなら台帳の売値を合わせる。"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger, num

CL = {"Content-Language": "en-US"}
eb = Ebay()
want = set(load_json(os.path.join(ROOT, "data", "値段の調整", "本当の値段_対象.json"), []))
rows = read_ledger()
out = {"時刻": jst(), "合わせた": [], "失敗": []}
for r in rows:
    if r.get("SKU") not in want or not r.get("offerId"):
        continue
    oid = r["offerId"]
    try:
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + oid)
        price = num(o["pricingSummary"]["price"]["value"])
        pol = o.get("listingPolicies") or {}
        bt = pol.get("bestOfferTerms") or {}
        dec = num((bt.get("autoDeclinePrice") or {}).get("value")) or 0
        if bt.get("bestOfferEnabled") and dec + 0.01 >= price:
            pol["bestOfferTerms"] = {"bestOfferEnabled": False}
        o["listingPolicies"] = pol
        for k in ("offerId", "status", "listing"):
            o.pop(k, None)
        eb.call("PUT", "/sell/inventory/v1/offer/" + oid, o, headers=CL)
        x = eb.trading("GetItem", "<ItemID>%s</ItemID>" % r.get("eBayの出品ID"))
        live = num((re.findall(r"<CurrentPrice[^>]*>([^<]*)</CurrentPrice>", x) or [""])[0])
        if live is not None and abs(live - price) < 0.005:
            r["売値(ドル)"] = "%.2f" % price
            r["最後に値段を変えた日時"] = jst()
            out["合わせた"].append({"SKU": r["SKU"], "値段": price})
        else:
            out["失敗"].append({"SKU": r["SKU"], "オファー": price, "出品": live})
    except EbayError as e:
        out["失敗"].append({"SKU": r["SKU"], "エラー": err_text(e)})
if out["合わせた"]:
    save_ledger(rows, ["売値(ドル)", "最後に値段を変えた日時"], "オファーと出品を合わせる")
save_json(os.path.join(ROOT, "data", "値段の調整", "合わせた結果.json"), out)
print("合わせた", len(out["合わせた"]), "失敗", len(out["失敗"]))
