"""フィギュアの下調べ（読むだけ・手で動かす）。11/28 12:14 オーナー「フィギュアの下調べを始めて」
- eBay の Browse（即決・米国向け）で、シリーズごとに：出品の数・日本から出している数・米国から出している数・値段（送料こみ）の真ん中・新品/中古の割合・よく出てくる作品。
- 出品はしない。eBay の画面は開かない（API だけ）。Sold は API で読めないので出品中だけ。
- 結果は data/下調べ/フィギュア.json。"""
import collections, os, re, statistics, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, num

SERIES = {"ねんどろいど": "Nendoroid", "figma": "figma", "S.H.Figuarts": "S.H.Figuarts", "POP UP PARADE": "Pop Up Parade",
          "プライズ（バンプレスト）": "Banpresto figure", "一番くじ": "Ichiban Kuji figure", "スケールフィギュア": "1/7 scale figure",
          "フィギュアーツZERO": "Figuarts Zero", "ガンプラ": "Gunpla HG", "ROBOT魂": "Robot Spirits"}
WORKS = ["One Piece", "Dragon Ball", "Demon Slayer", "Jujutsu Kaisen", "Hatsune Miku", "Chainsaw Man", "Spy x Family", "Evangelion",
         "Naruto", "My Hero Academia", "Re:Zero", "Frieren", "Oshi no Ko", "Blue Lock", "Pokemon", "Sailor Moon", "Gundam", "Bleach",
         "Hololive", "Genshin", "Attack on Titan", "Kaiju No", "Dandadan", "Sakamoto", "Bocchi", "Hunter x Hunter", "Jojo", "Haikyu",
         "Tokyo Revengers", "Sword Art Online", "Konosuba", "Love Live", "Idolmaster", "Persona", "Final Fantasy", "Zelda", "Mario", "Sonic"]
eb = Ebay()
HD = {"X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=10001"}


def search(q, flt, limit=200, offset=0):
    prm = {"q": q, "filter": flt, "limit": limit, "offset": offset}
    _, j = eb.call("GET", "/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(prm), kind="app", headers=HD)
    return j


def tot(c):
    sh = ((c.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value")
    return float((c.get("price") or {}).get("value") or 0) + float(sh or 0)


out = {"時刻": jst(), "シリーズ": {}}
for ja, q in SERIES.items():
    base = "buyingOptions:{FIXED_PRICE}"
    try:
        all_ = search(q, base, limit=1).get("total", 0)
        jp = search(q, base + ",itemLocationCountry:JP", limit=1).get("total", 0)
        us = search(q, base + ",itemLocationCountry:US", limit=1).get("total", 0)
        items = []
        for off in (0, 200):
            items += search(q, base + ",itemLocationCountry:JP", limit=200, offset=off).get("itemSummaries") or []
        items_us = search(q, base + ",itemLocationCountry:US", limit=200).get("itemSummaries") or []
    except EbayError as e:
        out["シリーズ"][ja] = {"エラー": err_text(e)[:200]}
        continue
    pj = [tot(c) for c in items if tot(c) > 0]
    pu = [tot(c) for c in items_us if tot(c) > 0]
    works = collections.Counter()
    for c in items:
        t = c.get("title") or ""
        for w in WORKS:
            if re.search(re.escape(w), t, re.I):
                works[w] += 1
    cond = collections.Counter("新品" if "new" in (c.get("condition") or "").lower() and "pre" not in (c.get("condition") or "").lower() else "中古" for c in items)
    sellers = collections.Counter((c.get("seller") or {}).get("username") for c in items)
    out["シリーズ"][ja] = {"検索語": q, "出品の数": all_, "日本から": jp, "米国から": us,
                         "日本の値段の真ん中$": round(statistics.median(pj), 2) if pj else None,
                         "米国の値段の真ん中$": round(statistics.median(pu), 2) if pu else None,
                         "日本の$50未満の割合%": round(100 * sum(1 for p in pj if p < 50) / len(pj)) if pj else None,
                         "日本の$100以上の割合%": round(100 * sum(1 for p in pj if p >= 100) / len(pj)) if pj else None,
                         "状態（日本）": dict(cond), "よく出る作品（日本）": works.most_common(10),
                         "日本のセラーの数（見本400品）": len(sellers), "上位セラーの品の割合%": round(100 * sum(n for _, n in sellers.most_common(5)) / max(1, len(items)))}
save_json(os.path.join(ROOT, "data", "下調べ", "フィギュア.json"), out)
for k, v in out["シリーズ"].items():
    print(k, {x: v.get(x) for x in ("出品の数", "日本から", "米国から", "日本の値段の真ん中$", "米国の値段の真ん中$")})
