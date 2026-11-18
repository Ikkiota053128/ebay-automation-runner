"""新しい仕入れ先の下調べ（読むだけ・11/18 22:23 オーナー「2と3番探して」）：robots.txt・トップ・規約のページ（転売・転載・自動の文）・検索フォームを data/店の下調べ/開拓.json に"""
import os, re, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, save_json, jst
import urllib.request, urllib.error

def fetch(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (compatible; ebay-automation store check)', 'Accept-Language': 'ja'}), timeout=25)
        b = r.read()
        enc = 'euc-jp' if re.search(rb'charset=["\']?euc-jp', b[:3000], re.I) else 'cp932' if re.search(rb'charset=["\']?(shift_jis|sjis|x-sjis|windows-31j)', b[:3000], re.I) else 'utf-8'
        return r.status, b.decode(enc, 'replace')
    except urllib.error.HTTPError as e:
        return e.code, ''
    except Exception as e:
        return None, str(e)[:100]

STORES = {"大貫カメラ": "https://www.camera-ohnuki.com/", "三宝カメラ": "http://www.sanpou.ne.jp/", "チャンプカメラ": "https://www.champcamera.co.jp/",
          "トップカメラ": "https://www.topcamera.co.jp/", "荻窪カメラのさくらや": "https://www.ogisaku.com/", "タカナシカメラ CAM-ALL": "https://shop.cam-all.com/",
          "J-Guitar": "https://www.j-guitar.com/", "デジマート": "https://www.digimart.net/", "ハイファイ堂": "https://www.hifido.co.jp/",
          "オーディオユニオン": "https://www.audiounion.jp/", "タックルベリー": "https://www.tackleberry.co.jp/", "monobankオークション": "https://www.monobank.co.jp/"}
KEY = re.compile(r"転売|営利|再販|業者|転載|二次利用|複製|無断|ロボット|クローラ|スクレイピング|自動的|機械的")
RES = re.compile(r"(転売|再販目的|営利目的|輸出)[^。]{0,60}(できません|禁止|お断り|不可|取り消|キャンセル|ご遠慮)|(お断り|キャンセル|取り消)[^。]{0,40}(転売|再販目的|営利目的|輸出)")
CPY = re.compile(r"(転載|二次利用|複製|無断使用|無断転用)[^。]{0,40}(禁止|お断り|できません)")
BOT = re.compile(r"(ロボット|クローラ|スクレイピング|自動的に|機械的に)[^。]{0,60}(禁止|お断り|できません)")
txt = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", h, flags=re.I)))
out = {}
for name, top in STORES.items():
    r = {"トップ": top}
    host = re.match(r"(https?://[^/]+)", top).group(1)
    c, rb = fetch(host + "/robots.txt"); r["robots"] = (c, rb[:800]); time.sleep(3)
    c, h = fetch(top); r["トップのHTTP"] = c; r["長さ"] = len(h); time.sleep(3)
    r["フォーム"] = [{"action": a, "inputs": re.findall(r'name="([^"]+)"', b)[:6]} for a, b in re.findall(r'<form[^>]*action="([^"]*)"[^>]*>([\s\S]*?)</form>', h or "", re.I)][:4]
    links = []
    for l, t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]{0,80}?)</a>', h or "", re.I):
        if re.search(r"kiyaku|terms|rule|guide|policy|agreement|規約|ご利用|利用案内|ガイド|特定商|注意", l + t, re.I):
            u = urllib.parse.urljoin(top, l)
            if u.startswith(host) and u not in links:
                links.append(u)
    r["規約のページ"] = []
    hits = {"転売": [], "転載": [], "自動": []}
    for u in links[:5]:
        c2, h2 = fetch(u); time.sleep(3)
        t = txt(h2) if c2 == 200 else ""
        for s in re.split(r"(?<=。)", t):
            if RES.search(s): hits["転売"].append(s.strip()[:180])
            if CPY.search(s): hits["転載"].append(s.strip()[:180])
            if BOT.search(s): hits["自動"].append(s.strip()[:180])
        r["規約のページ"].append([u, c2, len(t)])
    r["文"] = {k: list(dict.fromkeys(v))[:3] for k, v in hits.items()}
    out[name] = r
    print(name, r["トップのHTTP"], len(links), {k: len(v) for k, v in hits.items()})
save_json(os.path.join(ROOT, "data", "店の下調べ", "開拓.json"), {"時刻": jst(), "店": out})
