"""GitHub の中のブラウザから Amazon.co.jp が読めるかを試す（読むだけ・検索1ページと商品2ページだけ）。
11/24 09:00 オーナー「Amazon 規約承知済み！仕入れ先入れて！」。結果は data/判定/Amazonの試し.json"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, save_json
from playwright.sync_api import sync_playwright

out = {"時刻": jst(), "検索": {}, "商品": []}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    try:
        pg.goto("https://www.amazon.co.jp/s?k=" + "BOSS+DS-1", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(6000)
        txt = pg.inner_text("body")[:30000]
        links = list(dict.fromkeys(re.findall(r"/dp/([A-Z0-9]{10})", pg.content())))
        out["検索"] = {"ロボット": bool(re.search(r"ロボット|captcha|文字を入力", txt, re.I)), "商品の数": len(links), "はじめ": txt[:200].replace("\n", " "),
                     "中古の印": "中古" in txt, "値段の印": bool(re.search(r"￥\s?[\d,]+", txt))}
        for asin in links[:2]:
            time.sleep(25)
            pg.goto("https://www.amazon.co.jp/dp/" + asin, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
            t = pg.inner_text("body")[:40000]
            out["商品"].append({"ASIN": asin, "ロボット": bool(re.search(r"ロボット|captcha|文字を入力", t, re.I)),
                              "題名": (pg.title() or "")[:100], "在庫あり": "在庫あり" in t, "カートに入れる": "カートに入れる" in t,
                              "一時的に在庫切れ": "一時的に在庫切れ" in t or "現在在庫切れ" in t, "中古": "中古品" in t,
                              "値段": (re.findall(r"￥\s?[\d,]+", t) or [""])[0]})
    except Exception as e:
        out["エラー"] = str(e)[:200]
    b.close()
save_json(os.path.join(ROOT, "data", "判定", "Amazonの試し.json"), out)
print(json.dumps(out, ensure_ascii=False)[:2000])
