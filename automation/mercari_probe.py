"""GitHub（クラウド）からメルカリの商品ページが読めるかを試す（読むだけ・数品だけ）。
11/24 08:41 オーナー「AとC」（規約は承知済み）。品と品の間は20秒以上あける。結果は data/判定/メルカリの試し.json"""
import json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, save_json, read_ledger

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
want = ["MER-001682", "GST-000530", "MER-001554", "GST-000614"]   # 在庫なし2品（オーナーが見た）・在庫あり2品
led = {r["SKU"]: r for r in read_ledger()}
rows = [led[s] for s in want if s in led]
out = {"時刻": jst(), "品": []}
for i, r in enumerate(rows):
    if i:
        time.sleep(22)
    url = r["仕入元URL"].split("?")[0]
    rec = {"SKU": r["SKU"], "URL": url}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
        res = urllib.request.urlopen(req, timeout=30)
        html = res.read().decode("utf-8", "replace")
        rec["HTTP"] = res.status
        rec["長さ"] = len(html)
        rec["og:title"] = (re.findall(r'property="og:title"[^>]*content="([^"]*)"', html) or [""])[0][:120]
        rec["売り切れの印"] = bool(re.search(r"sold_out|売り切れ|SOLD", html))
        rec["販売中の印"] = bool(re.search(r"on_sale|購入手続きへ", html))
        rec["商品のJSON"] = bool(re.search(r'"itemStatus"|"status":"(on_sale|sold_out|trading)"', html))
        for k in ("InStock", "OutOfStock", "SoldOut", "product:availability", "ITEM_STATUS", "item_status", "sold_out", "on_sale", "売り切れ", "購入手続きへ"):
            rec["数:" + k] = len(re.findall(re.escape(k), html))
        rec["availability"] = re.findall(r'.{0,60}(?:availability|Availability).{0,80}', html)[:4]
    except Exception as e:
        rec["エラー"] = str(e)[:200]
    out["品"].append(rec)
save_json(os.path.join(ROOT, "data", "判定", "メルカリの試し.json"), out)
print(json.dumps(out, ensure_ascii=False)[:1500])
