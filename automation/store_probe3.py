"""トレファクの下調べ（読むだけ）：カテゴリの新着ページの作り（robots・カテゴリのリンク・一覧の商品リンク）を data/店の下調べ/treasure.json に"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch

out = {}
c, rb = fetch("https://ec.treasure-f.com/robots.txt"); out["robots"] = rb[:1500]; time.sleep(3)
c, top = fetch("https://ec.treasure-f.com/"); time.sleep(3)
links = sorted(set(re.findall(r'href="(/[^"]*(?:categor|genre|cat|search\?)[^"]*)"', top)))
out["カテゴリらしいリンク"] = links[:120]
cams = [l for l in links if re.search(r"camera|カメラ|music|楽器|audio|watch|時計|lens", l, re.I)][:6]
out["見たページ"] = []
for l in cams[:4]:
    c2, h = fetch("https://ec.treasure-f.com" + l); time.sleep(3)
    out["見たページ"].append({"url": l, "HTTP": c2, "len": len(h), "商品リンク": list(dict.fromkeys(re.findall(r'href="(/item/[^"]+)"', h)))[:6],
                          "並べ替え": sorted(set(re.findall(r'(?:sort|order)=[^"&]+', h)))[:10], "一部": re.sub(r"\s+", " ", h[h.find("/item/") - 1500: h.find("/item/") + 1500]) if "/item/" in h else ""})
c3, s = fetch("https://ec.treasure-f.com/search?word=Nikon"); time.sleep(3)
out["検索の並べ替え"] = sorted(set(re.findall(r'(?:sort|order|category)[=_][^"&\s]+', s)))[:30]
out["検索のリンク例"] = sorted(set(re.findall(r'href="(/search\?[^"]+)"', s)))[:40]
save_json(os.path.join(ROOT, "data", "店の下調べ", "treasure.json"), {"時刻": jst(), **out})
print("done", len(links), len(cams))
