"""アメリカの買い手から見えるか・買えるかを確かめる（読むだけ・手で動かす）。11/21 18:02 オーナー「なぜこう表示される？大丈夫？」
出品中の品を配送ポリシーごとに数品選び、Browse API（getItemByLegacyId）をアメリカ（ニューヨーク 10001）・カナダ・イギリスの買い手として読み、
配送の選択肢・送れる地域・送れない地域を書き出す。結果は data/判定/アメリカから見えるか.json"""
import json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, load_json

eb = Ebay()
chk = load_json(os.path.join(ROOT, "data", "判定", "発送先の確認.json"), {})
pick = {}
for x in chk.get("気になる品", []):
    pass
import csv
from common import read_ledger
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("eBayの出品ID")]
lids = [r["eBayの出品ID"] for r in rows[:: max(1, len(rows) // 8)]][:8]
out = {"時刻": jst(), "品": []}
for lid in lids:
    for ctx in ("country=US,zip=10001", "country=CA,zip=M5V3L9", "country=GB,zip=SW1A1AA"):
        try:
            _, j = eb.call("GET", "/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=" + lid, kind="app",
                           headers={"X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "X-EBAY-C-ENDUSERCTX": "contextualLocation=" + urllib.parse.quote(ctx, safe="=,")})
            so = [{"サービス": s.get("shippingServiceCode"), "送料": (s.get("shippingCost") or {}).get("value"), "種類": s.get("type")} for s in j.get("shippingOptions") or []]
            stl = j.get("shipToLocations") or {}
            out["品"].append({"出品ID": lid, "買い手": ctx, "タイトル": j.get("title", "")[:60], "配送": so,
                             "送れる": [r.get("regionName") for r in stl.get("regionIncluded") or []],
                             "送れない": [r.get("regionName") for r in stl.get("regionExcluded") or []][:200],
                             "買えるか": j.get("eligibleForInlineCheckout"), "注意": j.get("warnings")})
        except EbayError as e:
            out["品"].append({"出品ID": lid, "買い手": ctx, "エラー": err_text(e)[:300]})
save_json(os.path.join(ROOT, "data", "判定", "アメリカから見えるか.json"), out)
print("見た", len(out["品"]))
