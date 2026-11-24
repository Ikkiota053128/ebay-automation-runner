"""最近出した品の写真を調べる（読むだけ・手で動かす）。11/25 07:45 オーナー「最近読み取れない商品画像が出品されるのはなぜ？」
- 出品日が IMG_DAYS 日以内の出品中の品：Inventory API の imageUrls と、1枚目の写真を GET して種類・大きさを見る。
- 結果は data/判定/写真の調べ.json"""
import os, sys, urllib.request, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, read_ledger, save_json
import datetime

days = int(os.environ.get("IMG_DAYS", "2"))
since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
eb = Ebay()
out = {"時刻": jst(), "品": [], "まとめ": {}}
cnt = collections.Counter()
for r in read_ledger():
    if r.get("状態") != "出品中" or (r.get("出品日") or "") < since:
        continue
    sku = r["SKU"]
    try:
        it = eb.inventory_item(sku)
    except EbayError as e:
        out["品"].append({"SKU": sku, "エラー": err_text(e)[:200]})
        continue
    urls = (it.get("product") or {}).get("imageUrls") or []
    x = {"SKU": sku, "枚数": len(urls), "1枚目": urls[0] if urls else "", "仕入元": (r.get("仕入元URL") or "")[:40]}
    if urls:
        try:
            req = urllib.request.Request(urls[0], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as f:
                b = f.read()
                x["種類"], x["バイト"] = f.headers.get("Content-Type"), len(b)
                try:
                    from PIL import Image
                    import io
                    im = Image.open(io.BytesIO(b))
                    x["大きさ"] = "%dx%d" % im.size
                except Exception as e:
                    x["画像として読めない"] = str(e)[:100]
        except Exception as e:
            x["取れない"] = str(e)[:150]
    bad = (not urls) or x.get("取れない") or x.get("画像として読めない") or (x.get("バイト") or 0) < 3000
    x["だめ"] = bool(bad)
    src = next((k for k in ("rakuten", "paypayfleamarket", "auctions.yahoo", "shopping.yahoo", "fril", "mercari", "hardoff", "treasure") if k in (r.get("仕入元URL") or "")), "ほか")
    cnt[(src, "だめ" if bad else "よい")] += 1
    out["品"].append(x)
out["まとめ"] = {"%s/%s" % k: v for k, v in cnt.items()}
save_json(os.path.join(ROOT, "data", "判定", "写真の調べ.json"), out)
print(out["まとめ"])
