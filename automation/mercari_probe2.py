"""GitHub の中でブラウザ（Chromium・Playwright）を動かして、メルカリの商品ページを表示してから在庫を読めるかを試す（読むだけ・数品だけ）。
11/24 08:41 オーナー「AとC」。品と品の間は20秒以上あける。結果は data/判定/メルカリの試し2.json"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, save_json, read_ledger
from playwright.sync_api import sync_playwright

want = ["MER-001682", "GST-000530", "MER-001554", "GST-000614"]
led = {r["SKU"]: r for r in read_ledger()}
out = {"時刻": jst(), "品": []}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    for i, s in enumerate(want):
        if i:
            time.sleep(22)
        url = led[s]["仕入元URL"].split("?")[0]
        rec = {"SKU": s}
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(8000)
            txt = pg.inner_text("body")[:20000]
            rec["売り切れました"] = "売り切れました" in txt
            rec["購入手続きへ"] = "購入手続きへ" in txt
            rec["SOLD"] = bool(re.search(r"\bSOLD\b", txt))
            rec["削除"] = "削除されました" in txt or "見つかりません" in txt
            rec["ロボット"] = bool(re.search(r"ロボット|captcha|アクセスが集中", txt, re.I))
            rec["はじめ"] = txt[:150].replace("\n", " ")
        except Exception as e:
            rec["エラー"] = str(e)[:200]
        out["品"].append(rec)
    b.close()
save_json(os.path.join(ROOT, "data", "判定", "メルカリの試し2.json"), out)
print(json.dumps(out, ensure_ascii=False)[:2000])
