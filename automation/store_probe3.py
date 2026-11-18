"""トレファクの下調べ（読むだけ）：カテゴリの名前と番号・新着順の一覧の商品の作り"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch

c, h = fetch("https://ec.treasure-f.com/category/"); time.sleep(3)
cats = []
for m in re.finditer(r'href="(/search\?category=[^"]+)"[^>]*>([\s\S]{0,200}?)</a>', h):
    cats.append([m.group(1).replace("&amp;", "&"), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()[:40]])
c2, l = fetch("https://ec.treasure-f.com/search?category=1011&order=newarrival&number=90&step=1"); time.sleep(3)
i = l.find("/item/")
save_json(os.path.join(ROOT, "data", "店の下調べ", "treasure2.json"), {"時刻": jst(), "カテゴリ": cats[:300], "一覧HTTP": c2, "一覧の商品数": len(set(re.findall(r'/item/[^"?#]+', l))),
          "一覧の一部": re.sub(r"\s+", " ", l[max(0, i - 2500): i + 3000])})
print("done", len(cats))
