"""商品ページの写真の並びを調べる（読むだけ・手で動かす）。data/ログ/page_dump/ に写真のアドレスのまわりだけを残す"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
from stock_watch import fetch
urls = ["https://paypayfleamarket.yahoo.co.jp/item/z727143012", "https://paypayfleamarket.yahoo.co.jp/item/z727331502", "https://auctions.yahoo.co.jp/jp/auction/w1252987503"]
od = os.path.join(ROOT, "data", "ログ", "page_dump"); os.makedirs(od, exist_ok=True)
for u in urls:
    code, html = fetch(u)
    html = (html or "").replace("\\u002F", "/").replace("\\/", "/")
    out = {"code": code, "len": len(html), "og": re.findall(r'og:image"[^>]*content="([^"]+)"|content="([^"]+)"[^>]*og:image', html)[:3], "hits": []}
    for m in re.finditer(r"auctions\.c\.yimg\.jp/images\.auctions\.yahoo\.co\.jp/image/[^\"'\s<>]+", html):
        out["hits"].append({"pos": m.start(), "url": m.group(0)[-90:], "before": re.sub(r"\s+", " ", html[max(0, m.start() - 160): m.start()])})
    for k in ["\"images\"", "\"imageUrls\"", "\"thumbnail", "itemImages", "\"photos\"", "otherItems", "recommend", "sellerItems", "__NEXT_DATA__"]:
        out.setdefault("keys", {})[k] = [i.start() for i in re.finditer(re.escape(k), html)][:10]
    json.dump(out, open(os.path.join(od, re.sub(r"\W+", "_", u)[-30:] + ".json"), "w"), ensure_ascii=False, indent=1)
print("ok")
