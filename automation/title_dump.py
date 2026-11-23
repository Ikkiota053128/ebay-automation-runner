"""出品中の品のタイトル・項目（Item specifics）・カテゴリを読むだけ（eBay は変えない）。
11/23 12:39 オーナー「おすすめは 1 → 2 で！ほかのエフエクター、とけいいもしらべて」の下調べ。
結果は data/判定/タイトルと項目.json。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger

eb = Ebay()
out = {"時刻": jst(), "品": {}}
for r in read_ledger():
    if r.get("状態") != "出品中" or not r.get("offerId") or r["SKU"].startswith("STK-"):
        continue
    try:
        it = eb.inventory_item(r["SKU"])
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
        p = it.get("product") or {}
        out["品"][r["SKU"]] = {"タイトル": p.get("title"), "項目": p.get("aspects") or {}, "カテゴリ": o.get("categoryId"),
                              "状態": it.get("condition"), "状態の説明": it.get("conditionDescription"),
                              "出品ID": r.get("eBayの出品ID"), "仕入元URL": r.get("仕入元URL"), "売値": r.get("売値(ドル)")}
    except EbayError as e:
        out["品"][r["SKU"]] = {"エラー": err_text(e)[:200]}
save_json(os.path.join(ROOT, "data", "判定", "タイトルと項目.json"), out)
print("読んだ", len(out["品"]))
