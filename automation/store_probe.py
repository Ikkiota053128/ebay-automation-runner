"""店のサイトの下調べ（読むだけ）：robots.txt と、検索ページの作り（商品の名前・値段・リンクがどう書かれているか）を data/店の下調べ/ に保存する"""
import json, os, re, sys, time, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
STORES2 = [
    ("フジヤ_a", "https://www.fujiya-camera.co.jp", "/shop/goods/search.aspx?search=x&keyword=Nikon+D3300"),
    ("フジヤ_b", "https://www.fujiya-camera.co.jp", "/shop/goods/search.aspx?keyword=Nikon%20D3300&search=%E6%A4%9C%E7%B4%A2"),
    ("フジヤ_c", "https://www.fujiya-camera.co.jp", "/shop/goods/search.aspx?q=Nikon+D3300"),
    ("フジヤ_d", "https://www.fujiya-camera.co.jp", "/shop/goods/search.aspx"),
    ("八百富_s", "https://www.yaotomi.co.jp", "/search?q=Nikon%20D3300&type=product"),
]
STORES = [
    ("イシバシ楽器", "https://www.ishibashi.co.jp", "/ec/search?q=BOSS%20DD-3"),
    ("イシバシ楽器2", "https://www.ishibashi.co.jp", "/search/?q=BOSS"),
    ("フジヤカメラ", "https://www.fujiya-camera.co.jp", "/search?q=Nikon%20D3300"),
    ("カメラの八百富", "https://www.yaotomi.co.jp", "/search?q=Nikon"),
    ("PEEK A BOO CAMERA", "https://peekaboo-camera.com", "/search?q=Nikon"),
    ("マップカメラ", "https://www.mapcamera.com", "/search?keyword=Nikon%20D3300"),
    ("カメラのキタムラ", "https://shop.kitamura.jp", "/ec/list?keyword=Nikon%20D3300&type=u"),
    ("ハードオフ", "https://netmall.hardoff.co.jp", "/search/?q=BOSS%20DD-3"),
    ("セカンドストリート", "https://www.2ndstreet.jp", "/search?keyword=BOSS%20DD-3"),
    ("トレファク", "https://ec.treasure-f.com", "/search?keyword=SEIKO"),
]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:
        return None, str(e)[:200], url


out = {}
for name, host, path in (STORES2 if os.environ.get("PROBE2") else STORES):
    c1, robots, _ = get(host + "/robots.txt")
    c2, html, final = get(host + path)
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)
    yen = re.findall(r"[\d,]{3,9}\s*円|¥\s?[\d,]{3,9}", text)[:10]
    links = list(dict.fromkeys(re.findall(r'href="([^"]+)"', html)))[:400]
    out[name] = {"robots_code": c1, "robots": robots[:3000], "search_code": c2, "final_url": final, "len": len(html),
                 "円の数": len(re.findall(r"円", text)), "値段の例": yen, "リンク": links,
                 "本文の一部": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:4000],
                 "HTMLの一部": html[:200] + " … " + html[len(html) // 3: len(html) // 3 + 6000]}
    time.sleep(3)
save_json(os.path.join(ROOT, "data", "店の下調べ", ("probe2.json" if os.environ.get("PROBE2") else "probe.json")), {"時刻": jst(), "店": out})
print("\n".join("%s：robots %s・検索 %s・%d文字・値段 %d" % (k, v["robots_code"], v["search_code"], v["len"], len(v["値段の例"])) for k, v in out.items()))
