"""決めた値段に下げる（手で動かす）。11/23 14:17 オーナー「1とB」の 1：順位の確認で「下げれば最安か2番目に入れる」品を下げる。
対象 data/値段の調整/手で下げる.json：[{"SKU":…, "値段":…, "フロア":…}]。利益の下限（フロア）より下には下げない。
オファーの値段を変え、値下げ交渉は「フロアが値段より $0.01 以上安いときだけ・フロアで断る」に直す（25016 を避ける）→ 保存 → GetItem で出品の値段を確かめる → 台帳の売値を合わせる。"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, save_ledger, num

CL = {"Content-Language": "en-US"}
eb = Ebay()
want = {x["SKU"]: x for x in load_json(os.path.join(ROOT, "data", "値段の調整", "手で下げる.json"), [])}
rows = read_ledger()
out = {"時刻": jst(), "下げた": [], "失敗": []}
for r in rows:
    w = want.get(r["SKU"])
    if not w or not r.get("offerId") or r.get("状態") != "出品中":
        continue
    price, fp = round(float(w["値段"]), 2), float(w["フロア"])
    try:
        if price < fp - 0.005:
            raise EbayError(0, {"raw": "フロアより下なので下げない"})
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
        old = num(o["pricingSummary"]["price"]["value"])
        if old is not None and price >= old:
            raise EbayError(0, {"raw": "今の値段 $%.2f より安くない" % old})
        if old is not None and price < old * 0.7:   # 11/24 06:48 オーナー「至急1〜4やって」：1回で30%より大きい値下げはしない
            raise EbayError(0, {"raw": "大きすぎる値下げ（$%.2f → $%.2f）なので止めた" % (old, price)})
        o["pricingSummary"]["price"] = {"value": "%.2f" % price, "currency": "USD"}
        pol = o.get("listingPolicies") or {}
        if fp + 0.01 < price:
            pol["bestOfferTerms"] = {"bestOfferEnabled": True, "autoDeclinePrice": {"value": "%.2f" % fp, "currency": "USD"},
                                     "autoAcceptPrice": {"value": "%.2f" % (fp + 0.01), "currency": "USD"}}
        else:
            pol["bestOfferTerms"] = {"bestOfferEnabled": False}
        o["listingPolicies"] = pol
        for k in ("offerId", "status", "listing"):
            o.pop(k, None)
        eb.call("PUT", "/sell/inventory/v1/offer/" + r["offerId"], o, headers=CL)
        x = eb.trading("GetItem", "<ItemID>%s</ItemID>" % r.get("eBayの出品ID"))
        live = num((re.findall(r"<CurrentPrice[^>]*>([^<]*)</CurrentPrice>", x) or [""])[0])
        if live is None or abs(live - price) > 0.005:
            raise EbayError(0, {"raw": "出品の値段が $%s のまま" % live})
        r["売値(ドル)"] = "%.2f" % price
        r["最後に値段を変えた日時"] = jst()
        out["下げた"].append({"SKU": r["SKU"], "前": old, "後": price})
    except EbayError as e:
        out["失敗"].append({"SKU": r["SKU"], "エラー": err_text(e)[:300]})
if out["下げた"]:
    save_ledger(rows, ["売値(ドル)", "最後に値段を変えた日時"], "順位の確認で手で下げる")
save_json(os.path.join(ROOT, "data", "値段の調整", "手で下げた結果.json"), out)
print("下げた", len(out["下げた"]), "失敗", len(out["失敗"]))
