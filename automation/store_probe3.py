"""下調べ（読むだけ）：大貫カメラ・さくらやの検索結果の作り"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch
out = {}
for n, u in [("大貫", "https://www.camera-ohnuki.com/search?q=Nikon+F3&type=product"), ("大貫2", "https://www.camera-ohnuki.com/search?q=Nikon"),
             ("さくらや", "https://www.ogisaku.com/products/list.php?mode=search&name=Nikon"), ("さくらや2", "https://www.ogisaku.com/products/list.php?name=F3")]:
    c, h = fetch(u); time.sleep(3)
    i = max(h.find("/products/"), 0)
    out[n] = {"HTTP": c, "len": len(h), "リンク": sorted(set(re.findall(r'href="([^"]*/products/[^"]+)"', h)))[:15], "一部": re.sub(r"\s+", " ", h[i - 1500:i + 2500])}
save_json(os.path.join(ROOT, "data", "店の下調べ", "開拓2.json"), {"時刻": jst(), **out})
print("done")
