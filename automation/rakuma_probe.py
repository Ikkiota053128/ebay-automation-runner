"""GitHub から楽天ラクマ（fril.jp）が読めるかを試す（読むだけ・検索1ページと商品2ページだけ）。
11/24 09:01 オーナー「楽天ラクマ 規約承知済み！仕入れ先入れて！」。結果は data/判定/ラクマの試し.json"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, save_json
from playwright.sync_api import sync_playwright

out = {"時刻": jst(), "検索": {}, "商品": []}
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
    try:
        pg.goto("https://fril.jp/s?query=BOSS+DS-1&transaction=selling", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(6000)
        txt = pg.inner_text("body")[:30000]
        html = pg.content()
        links = list(dict.fromkeys(re.findall(r"https://item\.fril\.jp/[0-9a-f]{20,}", html)))
        out["検索"] = {"ロボット": bool(re.search(r"ロボット|captcha|アクセスが集中", txt, re.I)), "商品の数": len(links), "はじめ": txt[:200].replace("\n", " "),
                     "値段の印": bool(re.search(r"¥\s?[\d,]+", txt)), "SOLDの数": len(re.findall(r"SOLD", txt))}
        pg.goto("https://fril.jp/s?query=BOSS+DS-1&transaction=soldout", wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(6000)
        sold = list(dict.fromkeys(re.findall(r"https://item\.fril\.jp/[0-9a-f]{20,}", pg.content())))[:2]
        cards = pg.eval_on_selector_all('a[href^="https://item.fril.jp/"]', "els => els.slice(0,6).map(e => e.innerText.slice(0,120))")
        out["一覧の文字"] = cards
        for u in links[:2] + sold:
            time.sleep(25)
            pg.goto(u, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(6000)
            t = pg.inner_text("body")[:40000]
            out["商品"].append({"URL": u, "題名": (pg.title() or "")[:100], "購入に進む": "購入に進む" in t, "売り切れ": bool(re.search(r"売り切れ|SOLD OUT|売切", t)),
                              "値段": (re.findall(r"¥\s?[\d,]+", t) or [""])[0], "写真": len(re.findall(r"img\.fril\.jp/img/\d+/l/", pg.content())), "売り切れの検索から": u in sold,
                              "ボタンのあたり": re.findall(r".{0,40}(?:購入|売り切れ|SOLD|カート).{0,40}", t)[:6]})
    except Exception as e:
        out["エラー"] = str(e)[:200]
    b.close()
save_json(os.path.join(ROOT, "data", "判定", "ラクマの試し.json"), out)
print(json.dumps(out, ensure_ascii=False)[:2000])
