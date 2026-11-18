"""4店の下調べ（読むだけ・手で動かす）：トップページから検索フォームと規約のリンクを探し、規約の文（転売・転載・自動）と検索ページの作りを data/店の下調べ/probe3.json に保存"""
import os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch as _f


def fetch(u):
    import urllib.request
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'ja'}), timeout=30)
        b = r.read()
        enc = 'cp932' if re.search(rb'charset=["\']?(shift_jis|sjis|x-sjis|windows-31j)', b[:3000], re.I) else 'utf-8'
        return r.status, b.decode(enc, 'replace')
    except Exception:
        return _f(u)

STORES = {
    "カメラのナニワ（規約）": ("https://cameranonaniwa.jp/shop/pages/guide.aspx", 4, []),
    "カメラのナニワ（トップ）": ("https://cameranonaniwa.jp/", 4, []),
}
KEY = re.compile(r"転売|営利|再販|業者|転載|二次利用|複製|無断|ロボット|クローラ|スクレイピング|自動化|自動的|機械的|プログラム")


def text_of(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)))


out = {}
for name, (top, gap, guesses) in STORES.items():
    r = {"トップ": top}
    code, html = fetch(top)
    r["トップのHTTP"] = code
    time.sleep(gap)
    forms = [{"action": a, "inputs": re.findall(r'<input[^>]+name="([^"]+)"', body)[:8]}
             for a, body in re.findall(r'<form[^>]*action="([^"]*)"[^>]*>([\s\S]*?)</form>', html or "", re.I)][:6]
    r["フォーム"] = forms
    links = []
    for l, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]{0,80}?)</a>', html or "", re.I):
        if re.search(r"kiyaku|terms|rule|policy|guide|agreement|規約|ご利用|利用案内|ショッピングガイド|特定商|免責|注意", l + t, re.I):
            u = urllib.parse.urljoin(top, l)
            if u not in links:
                links.append(u)
    r["規約らしいリンク"] = links[:15]
    r["ショップらしいリンク"] = [urllib.parse.urljoin(top, l) for l in re.findall(r'href="([^"]*(?:shop|store|online|ec|item|product|used|chuko|中古)[^"]*)"', html or "", re.I)][:15]
    pages = []
    for u in links[: (3 if gap > 30 else 6)]:
        c2, h2 = fetch(u)
        time.sleep(gap)
        t = text_of(h2) if c2 == 200 else ""
        hits = []
        for m in KEY.finditer(t):
            s = t[max(0, m.start() - 100): m.end() + 100]
            if not any(s[30:130] in h for h in hits):
                hits.append(s)
        pages.append({"url": u, "HTTP": c2, "文字数": len(t), "見つかった文": hits[:30]})
    r["規約のページ"] = pages
    srch = []
    for u in guesses[: (1 if gap > 30 else 2)]:
        c3, h3 = fetch(u)
        time.sleep(gap)
        srch.append({"url": u, "HTTP": c3, "len": len(h3 or ""), "円の数": len(re.findall(r"円|¥|&yen;", h3 or "")),
                     "商品リンクの例": list(dict.fromkeys(re.findall(r'href="([^"]*(?:item|product|goods|detail)[^"]*)"', h3 or "", re.I)))[:8],
                     "JSON-LD": "ld+json" in (h3 or ""), "本文の一部": text_of(h3 or "")[:800]})
    r["検索"] = srch
    out[name] = r
    print(name, code, len(forms), len(links), [(p["HTTP"], len(p["見つかった文"])) for p in pages], [(s["HTTP"], s["円の数"]) for s in srch])
save_json(os.path.join(ROOT, "data", "店の下調べ", "probe3.json"), {"時刻": jst(), "店": out})
