"""ブラックフライデーのセール（手で動かす）。11/21 18:47 オーナー「1 → 2 → 3 でお願いします」（3）
- 期間：2026-11-27 0:00 〜 11-30 23:59（アメリカ太平洋時間 PT）。10%引き（Marketing API の値引きセール item_price_markdown）。
- 対象：出品中で、11/27 の時点で出品から14日以上たつ品（台帳の出品日が 11/13 以前、または出品日が無い前からの品）、
  かつ 10%引きでも最低利益の値段（利益5%・1,500円）を割らない品。決めごとA・有在庫（STK-）は入れない。
- data/セール/ブラックフライデー.json の「本番」が false の間はドライラン（対象の数と合計だけ記録）。true でセールを作る（作ったら false に戻す）。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, settings, floor_price, num

P = os.path.join(ROOT, "data", "セール", "ブラックフライデー.json")
cfg = load_json(P, {"本番": False})
st = settings()
rows = []
for r in read_ledger():
    sku = r.get("SKU", "")
    if r.get("状態") != "出品中" or sku.startswith("STK-") or not r.get("eBayの出品ID"):
        continue
    d = (r.get("出品日") or "")[:10]
    if d and d > "2026-11-13":
        continue
    price = num(r.get("売値(ドル)")) or 0
    fp = floor_price(r, st)
    if not price or not fp or price * 0.9 < fp:
        continue
    rows.append({"SKU": sku, "出品ID": r["eBayの出品ID"], "値段": price, "セールの値段": round(price * 0.9, 2), "最低利益": fp})
out = {"時刻": jst(), "本番": bool(cfg.get("本番")), "対象": len(rows), "値段の合計": round(sum(x["値段"] for x in rows), 2), "品": rows[:500]}
if cfg.get("本番") and rows:
    eb = Ebay()
    body = {"name": "Black Friday Sale 10% Off", "description": "Black Friday Sale", "marketplaceId": "EBAY_US",
            "startDate": "2026-11-27T08:00:00.000Z", "endDate": "2026-12-01T07:59:00.000Z", "promotionStatus": "SCHEDULED",
            "applyFreeShipping": False, "autoSelectFutureInventory": False, "blockPriceIncreaseInMarkdown": True,
            "selectedInventoryDiscounts": [{"discountBenefit": {"percentageOffItem": "10"},
                                            "inventoryCriterion": {"inventoryCriterionType": "INVENTORY_BY_VALUE",
                                                                   "listingIds": [x["出品ID"] for x in rows[:500]]}}]}
    try:
        code, j = eb.call("POST", "/sell/marketing/v1/item_price_markdown", body)
        out["作った"] = {"返事": code, "中身": j}
    except EbayError as e:
        out["エラー"] = err_text(e)
    cfg["本番"] = False
    save_json(P, cfg)
save_json(os.path.join(ROOT, "data", "セール", "ブラックフライデー_結果.json"), out)
print("本番" if out["本番"] else "ドライラン", "対象", out["対象"], "合計 $", out["値段の合計"], out.get("エラー", ""))
