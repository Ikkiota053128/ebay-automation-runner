"""楽天・Yahoo!ショッピングの店ごとの規約を読む（毎月1日と手で動かしたとき）。

- 台帳で使っている店と、店の地引網の最近の候補の店の「会社概要・ご利用案内」ページ（楽天 info.html・Yahoo! info.html）を読む。
- 「転売・再販・営利目的の購入を断る」「写真・文章の転載・二次利用を禁止」の文があれば、その店を「使わない店」にする。
- 結果：data/判定/使わない店.json（店の地引網・判定と出品・予備の仕入れ先が読む）と data/店の下調べ/モールの店の規約.json。
- 読めなかった店は「読めない」のまま（使わない店にはしない）。1店ごとに 3秒あける。
"""
import collections, csv, glob, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, load_json, save_json, jst, notify, write_run, mark_started, read_ledger
from stock_watch import fetch

NAME = "モールの店の規約"
RESALE = re.compile(r"(転売|再販|営利|せどり|業者)[^。]{0,60}(できません|できない|禁止|お断り|不可|取り消|取消|キャンセル|ご遠慮|控え|停止)|"
                    r"(お断り|キャンセル|取り消|取消)[^。]{0,40}(転売|再販|営利目的)")
COPY = re.compile(r"(転載|二次利用|二次使用|無断使用|無断転用|無断利用|複製)[^。]{0,40}(禁止|お断り|できません|固く)")
WARRANTY_ONLY = re.compile(r"(初期不良|保証|返品|交換)[^。]{0,40}(転売|再販)|(転売|再販)[^。]{0,40}(初期不良|保証|返品|交換)")


def shop_of(url):
    m = re.match(r"https?://store\.shopping\.yahoo\.co\.jp/([^/?#]+)/", url or "") or re.match(r"https?://item\.rakuten\.co\.jp/([^/?#]+)/", url or "")
    if not m:
        return None
    return ("Y" if "yahoo" in url else "R") + ":" + m.group(1)


def pages_of(key):
    k, s = key.split(":", 1)
    if k == "R":
        return ["https://www.rakuten.co.jp/%s/info.html" % s, "https://www.rakuten.co.jp/%s/info2.html" % s]
    return ["https://store.shopping.yahoo.co.jp/%s/info.html" % s, "https://store.shopping.yahoo.co.jp/%s/guide.html" % s]


def main():
    mark_started(NAME)
    cnt = collections.Counter()
    for r in read_ledger():
        if r.get("状態") in ("出品中", "在庫ゼロ", "売れた"):
            k = shop_of(r.get("仕入元URL"))
            if k:
                cnt[k] += 5
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "店の地引網", "2*.json")))[-60:]:
        for c in load_json(f, {}).get("候補", []) or []:
            k = shop_of(c.get("url"))
            if k:
                cnt[k] += 1
    res_p = os.path.join(ROOT, "data", "店の下調べ", "モールの店の規約.json")
    res = load_json(res_p, {})
    limit = int(os.environ.get("MALL_TERMS_MAX", "250"))
    todo = [k for k, _ in cnt.most_common() if not res.get(k, {}).get("読んだ日時", "").startswith(jst()[:7])][:limit]
    for k in todo:
        hit_r, hit_c, codes, warranty = [], [], [], []
        for u in pages_of(k):
            code, html = fetch(u)
            codes.append(code)
            time.sleep(3)
            if code != 200:
                continue
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html, flags=re.I)))
            for s in re.split(r"(?<=。)", t):
                if RESALE.search(s):
                    (warranty if WARRANTY_ONLY.search(s) else hit_r).append(s.strip()[:200])
                if COPY.search(s):
                    hit_c.append(s.strip()[:200])
        st = "読めない" if not any(c == 200 for c in codes) else ("使わない" if hit_r or hit_c else "OK")
        res[k] = {"結果": st, "転売の文": hit_r[:3], "転載の文": hit_c[:3], "保証だけの文": warranty[:2], "HTTP": codes, "読んだ日時": jst(), "重み": cnt[k]}
    save_json(res_p, res)
    bad = sorted(k for k, v in res.items() if v["結果"] == "使わない")
    save_json(os.path.join(ROOT, "data", "判定", "使わない店.json"), {"更新": jst(), "店": bad,
              "_説明": "楽天(R:)・Yahoo!(Y:)の店の規約で、転売目的の購入を断る・写真や文章の転載を禁止している店（mall_terms.py）"})
    c = collections.Counter(v["結果"] for k, v in res.items() if k in todo)
    msg = "【モールの店の規約】%s 読んだ %d店（OK %d・使わない %d・読めない %d）。使わない店は全部で %d店" % (jst(), len(todo), c["OK"], c["使わない"], c["読めない"], len(bad))
    print(msg)
    notify(msg)
    write_run(NAME, True, len(todo), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
