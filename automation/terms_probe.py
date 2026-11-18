"""今使っている店の利用規約を読む（読むだけ）：転売・営利目的の購入、転載・二次利用、ロボット・自動プログラムの決まりがある文を抜き出す"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
from stock_watch import fetch

PAGES = {
    "イシバシ楽器": ["https://store.ishibashi.co.jp/view/page/kiyaku", "https://store.ishibashi.co.jp/view/page/guide", "https://store.ishibashi.co.jp/help/", "https://store.ishibashi.co.jp/view/page/terms", "https://store.ishibashi.co.jp/"],
    "カメラの八百富": ["https://www.yaotomi.co.jp/policies/terms-of-service", "https://www.yaotomi.co.jp/pages/terms", "https://www.yaotomi.co.jp/pages/guide"],
    "トレファク": ["https://ec.treasure-f.com/guide/terms/", "https://ec.treasure-f.com/terms/", "https://ec.treasure-f.com/guide/", "https://ec.treasure-f.com/kiyaku/"],
    "ハードオフ（オフモール）": ["https://netmall.hardoff.co.jp/guide/terms/", "https://netmall.hardoff.co.jp/terms/", "https://netmall.hardoff.co.jp/guide/", "https://netmall.hardoff.co.jp/kiyaku/"],
}
KEY = re.compile(r"転売|営利|再販|業者|転載|二次利用|複製|無断|ロボット|クローラ|スクレイピング|自動化|自動的|機械的")
out = {}
for name, urls in PAGES.items():
    res = []
    for u in urls:
        code, html = fetch(u)
        time.sleep(3)
        if code != 200:
            res.append({"url": u, "HTTP": code})
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)))
        hits = []
        for m in KEY.finditer(text):
            s = text[max(0, m.start() - 80): m.end() + 80]
            if not any(s[20:120] in h for h in hits):
                hits.append(s)
        links = [l for l in re.findall(r'href="([^"]+)"', html) if re.search(r"kiyaku|terms|rule|guide|policy|規約", l, re.I)][:15]
        res.append({"url": u, "HTTP": 200, "文字数": len(text), "見つかった文": hits[:25], "規約らしいリンク": links})
    out[name] = res
save_json(os.path.join(ROOT, "data", "店の下調べ", "規約.json"), {"時刻": jst(), "店": out})
for k, v in out.items():
    print(k, [(x["url"], x["HTTP"], len(x.get("見つかった文", []))) for x in v])
