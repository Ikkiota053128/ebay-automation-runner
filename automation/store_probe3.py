"""じゃんぱらの下調べ（読むだけ）：検索結果と商品ページのHTMLをそのまま data/店の下調べ/ に（Crawl-delay 60 を守る）"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT
from stock_watch import fetch

d = os.path.join(ROOT, "data", "店の下調べ")
code, html = fetch("https://www.janpara.co.jp/sale/search/result/?KEYWORDS=BOSS&CHKOUTCOM=1&OUTCLSCODE=")
open(os.path.join(d, "janpara_search.html"), "w").write(html)
time.sleep(61)
c2, h2 = fetch("https://www.janpara.co.jp/sale/search/detail/?SRCODE=223045648&SHPCODE=223&TYPE=")
open(os.path.join(d, "janpara_item.html"), "w").write(h2)
print("done", code, len(html), c2, len(h2))
