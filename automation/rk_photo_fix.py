"""楽天の写真が読めない（404）出品中の品の写真を、読める形に直す（手で動かす）。11/25 07:45 オーナー「最近読み取れない商品画像が出品されるのはなぜ？」
- 対象：data/判定/写真の調べ.json で だめ の楽天の品。写真のアドレスを judge_list.rk_img で読める形にして PUT し、読み直して確かめる。
- 読める写真が1枚も無い品は直さずに記録する。結果は data/判定/楽天の写真の直し.json"""
import os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json
from judge_list import rk_img

CL = {"Content-Language": "en-US"}
eb = Ebay()
bad = [x["SKU"] for x in load_json(os.path.join(ROOT, "data", "判定", "写真の調べ.json"), {}).get("品", []) if x.get("だめ") and "rakuten" in (x.get("仕入元") or "")]
out = {"時刻": jst(), "直した": [], "直せない": []}
for sku in bad:
    try:
        it = eb.inventory_item(sku)
        old = (it.get("product") or {}).get("imageUrls") or []
        new = [x for x in (rk_img(u) for u in old) if x]
        if not new:
            out["直せない"].append({"SKU": sku, "前": old})
            continue
        it["product"]["imageUrls"] = new
        body = {k: v for k, v in it.items() if k in ("product", "condition", "conditionDescription", "conditionDescriptors", "availability", "packageWeightAndSize", "locale")}
        pw = body.get("packageWeightAndSize") or {}
        if pw and not float((pw.get("weight") or {}).get("value") or 0) > 0:
            pw.pop("weight", None)
            if not pw.get("dimensions") or not all(float(pw["dimensions"].get(k) or 0) > 0 for k in ("length", "width", "height")):
                body.pop("packageWeightAndSize", None)
        eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), body, headers=CL)
        chk = (eb.inventory_item(sku).get("product") or {}).get("imageUrls") or []
        out["直した"].append({"SKU": sku, "前": old, "後": chk})
    except EbayError as e:
        out["直せない"].append({"SKU": sku, "エラー": err_text(e)[:300]})
save_json(os.path.join(ROOT, "data", "判定", "楽天の写真の直し.json"), out)
print("直した", len(out["直した"]), "直せない", len(out["直せない"]))
