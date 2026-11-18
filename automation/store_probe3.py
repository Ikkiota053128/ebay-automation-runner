"""じゃんぱらの下調べ（読むだけ）：検索結果と商品ページの作りを data/店の下調べ/janpara.json に（robots の Crawl-delay 60 を守る）"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch

out = {}
code, html = fetch("https://www.janpara.co.jp/sale/search/result/?KEYWORDS=Nikon+D750&CHKOUTCOM=1")
out["検索"] = {"HTTP": code, "len": len(html)}
i = html.find("search/detail/?SRCODE")
out["検索の一部"] = [html[max(0, m.start() - 1500): m.start() + 2500] for m in list(re.finditer(r"search/detail/\?SRCODE", html))[:2]]
links = list(dict.fromkeys(re.findall(r'https://www\.janpara\.co\.jp/sale/search/detail/\?SRCODE=\d+&SHPCODE=\d+', html)))
out["リンク"] = links[:10]
time.sleep(61)
if links:
    c2, h2 = fetch(links[0])
    out["商品ページ"] = {"url": links[0], "HTTP": c2, "len": len(h2), "ld": "ld+json" in h2,
                    "画像": re.findall(r'(?:src|href|data-src)="([^"]+\.(?:jpg|jpeg|png)[^"]*)"', h2)[:40],
                    "値段の近く": [h2[max(0, m.start() - 300): m.end() + 300] for m in list(re.finditer(r"円|&yen;|￥", h2))[:6]],
                    "在庫の言葉": re.findall(r"カートに入れる|売り切れ|SOLD|在庫なし|品切れ|販売終了|お取り置き|商品が見つかりません", h2)[:10],
                    "title": (re.search(r"<title>([\s\S]*?)</title>", h2) or [None, ""])[1][:200],
                    "h1": re.findall(r"<h[12][^>]*>([\s\S]{0,300}?)</h[12]>", h2)[:5]}
save_json(os.path.join(ROOT, "data", "店の下調べ", "janpara.json"), {"時刻": jst(), **out})
print("done", code, len(links))
