"""下調べ（読むだけ）：イケベ楽器・カメラのキタムラの検索結果の作り"""
import os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch
out = {}
c, top = fetch("https://kitamuracamera.jp/"); time.sleep(3)
out["キタムラのトップのリンク"] = sorted(set(re.findall(r'href="([^"]*(?:search|used|chuko|item|product|goods)[^"]*)"', top)))[:60]
out["キタムラのフォーム"] = re.findall(r'<form[\s\S]{0,600}?</form>', top)[:3]
for n, u in [("イケベ", "https://www.ikebe-gakki.com/Form/Product/ProductList.aspx?shop=0&cat=&bid=ec&dpcnt=20&img=1&sort=07&udns=1&fpfl=0&sfl=0&swrd=BOSS%20DD-3&pno=1"),
             ("イケベ中古", "https://www.ikebe-gakki.com/Form/Product/ProductList.aspx?shop=0&cat=&bid=ec&dpcnt=20&img=1&sort=07&udns=1&fpfl=0&sfl=0&_class=%E3%83%A6%E3%83%BC%E3%82%BA%E3%83%89&swrd=BOSS&pno=1"),
             ("キタムラ1", "https://kitamuracamera.jp/ja/search?q=Nikon%20F3"), ("キタムラ2", "https://kitamuracamera.jp/search?q=Nikon")]:
    c, h = fetch(u); time.sleep(4)
    links = sorted(set(re.findall(r'href="([^"]*(?:ProductDetail|/item/|/products?/|/goods/|/detail)[^"]*)"', h)))
    i = h.find(links[0]) if links else 0
    out[n] = {"HTTP": c, "len": len(h), "リンク": links[:12], "円": len(re.findall(r"円|¥|￥", h)), "ld": "ld+json" in h, "一部": re.sub(r"\s+", " ", h[max(0, i - 800): i + 1800])}
save_json(os.path.join(ROOT, "data", "店の下調べ", "開拓4.json"), {"時刻": jst(), **out})
print("done")
