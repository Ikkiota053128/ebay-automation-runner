"""下調べ（読むだけ）：イケベ楽器の中古の検索結果のリンクの形"""
import collections, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch
c, h = fetch("https://www.ikebe-gakki.com/Form/Product/ProductList.aspx?shop=0&cat=&bid=ec&dpcnt=20&img=1&sort=07&udns=1&fpfl=0&sfl=0&_class=%E3%83%A6%E3%83%BC%E3%82%BA%E3%83%89&swrd=BOSS&pno=1")
hrefs = re.findall(r'href="([^"#]+)"', h)
pref = collections.Counter(re.sub(r"[?].*$", "", x)[:60] for x in hrefs)
i = h.find("DD-") if "DD-" in h else h.find("BOSS", 200000)
save_json(os.path.join(ROOT, "data", "店の下調べ", "開拓5.json"), {"時刻": jst(), "HTTP": c, "len": len(h), "リンクの形": pref.most_common(40),
          "BOSSの近く": re.sub(r"\s+", " ", h[max(0, i - 1500): i + 1500]), "ld": len(re.findall("ld\\+json", h))})
print("done")
