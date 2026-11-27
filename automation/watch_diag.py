"""腕時計の閲覧数が少ない原因を調べる（読むだけ・手で動かす）。11/27 19:28 オーナー「私のショップの腕時計の閲覧数が悪い。なぜか調べて！原因分析して」
- 出品中の全部の品：直近30日の 表示回数（インプレッション）・検索結果での表示・閲覧数・クリック率（Analytics traffic_report）。
- オファー（カテゴリ・値段）と商品（写真の枚数・項目の数・タイトルの長さ）。
- 腕時計（カテゴリ 31387 か タイトルに Watch）だけ：同じ型番の競合を検索して、競合の数・最安・自分の値段の順位・日本から出している競合の数。
- 結果は data/判定/腕時計の診断.json。eBay の画面は開かない（API だけ）。"""
import collections, datetime as dt, os, re, statistics, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, now, read_ledger, save_json

eb = Ebay()
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("eBayの出品ID") and r.get("offerId")]
end = now().date() - dt.timedelta(days=1)
start = end - dt.timedelta(days=29)
MET = ["LISTING_IMPRESSION_TOTAL", "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE", "LISTING_VIEWS_TOTAL", "CLICK_THROUGH_RATE"]
tr = {}
ids = [r["eBayの出品ID"] for r in rows]
for i in range(0, len(ids), 50):
    part = ids[i:i + 50]
    flt = "marketplace_ids:{EBAY_US},date_range:[%s..%s],listing_ids:{%s}" % (start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "|".join(part))
    try:
        _, j = eb.call("GET", "/sell/analytics/v1/traffic_report?" + urllib.parse.urlencode({"dimension": "LISTING", "metric": ",".join(MET), "filter": flt}))
        hdr = [m.get("key") for m in (j.get("header") or {}).get("metrics", [])]
        for rec in j.get("records", []):
            lid = str((rec.get("dimensionValues") or [{}])[0].get("value", ""))
            vals = [x.get("value") for x in rec.get("metricValues") or []]
            tr[lid] = dict(zip(hdr or MET, vals))
    except EbayError as e:
        print("traffic_report", err_text(e)[:200])
items = []
for r in rows:
    try:
        o = [x for x in eb.offers_of(r["SKU"]) if x.get("offerId") == r["offerId"]]
        o = o[0] if o else {}
        it = eb.inventory_item(r["SKU"])
    except EbayError:
        continue
    p = it.get("product") or {}
    asp = p.get("aspects") or {}
    cat = str(o.get("categoryId") or "")
    t = tr.get(r["eBayの出品ID"], {})
    title = p.get("title") or r.get("タイトル") or ""
    try:
        age = (now().date() - dt.date.fromisoformat((r.get("出品日") or "")[:10])).days
    except ValueError:
        age = None
    items.append({"SKU": r["SKU"], "出品ID": r["eBayの出品ID"], "カテゴリ": cat, "腕時計": cat == "31387" or bool(re.search(r"\bwatch\b", title, re.I)),
                  "タイトル": title, "文字数": len(title), "写真": len(p.get("imageUrls") or []),
                  "項目": sum(1 for k, v in asp.items() if v and not re.match(r"(?i)does not apply", str(v[0]))),
                  "値段": float(((o.get("pricingSummary") or {}).get("price") or {}).get("value") or 0), "日数": age,
                  "表示": int(t.get("LISTING_IMPRESSION_TOTAL") or 0), "検索で表示": int(t.get("LISTING_IMPRESSION_SEARCH_RESULTS_PAGE") or 0),
                  "閲覧": int(t.get("LISTING_VIEWS_TOTAL") or 0), "クリック率": float(t.get("CLICK_THROUGH_RATE") or 0),
                  "仕入元": next((n for k, n in [("paypayfleamarket", "Yahoo!フリマ"), ("auctions.yahoo", "ヤフオク"), ("rakuten", "楽天"), ("shopping.yahoo", "Yahoo!ショッピング"), ("mercari", "メルカリ"), ("fril", "ラクマ")] if k in (r.get("仕入元URL") or "")), "店ほか")})
# 腕時計：競合と値段の順位
for x in [i for i in items if i["腕時計"]]:
    t = x["タイトル"].split()
    if len(t) < 2:
        continue
    md = re.sub(r"[^0-9A-Z]", "", t[1].upper())
    try:
        its = eb.browse("%s %s" % (t[0], t[1]), "buyingOptions:{FIXED_PRICE}", limit=50)
    except EbayError:
        continue
    comp = [c for c in its if str(c.get("legacyItemId")) != x["出品ID"] and (c.get("seller") or {}).get("username", "").lower() != "ihdj_81"
            and md in re.sub(r"[^0-9A-Z]", "", (c.get("title") or "").upper())]
    def tot(c):
        sh = ((c.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value") or 0
        return float((c.get("price") or {}).get("value") or 0) + float(sh)
    ps = sorted(tot(c) for c in comp)
    x["競合"] = len(comp)
    x["日本の競合"] = sum(1 for c in comp if (c.get("itemLocation") or {}).get("country") == "JP")
    x["米国の競合"] = sum(1 for c in comp if (c.get("itemLocation") or {}).get("country") == "US")
    x["競合の最安"] = ps[0] if ps else None
    x["順位"] = 1 + sum(1 for v in ps if v < x["値段"]) if ps else None
    x["新品の競合"] = sum(1 for c in comp if "new" in (c.get("condition") or "").lower())


def agg(L):
    if not L:
        return {}
    m = lambda k: round(statistics.mean([i[k] for i in L if isinstance(i.get(k), (int, float))] or [0]), 2)
    md = lambda k: statistics.median([i[k] for i in L if isinstance(i.get(k), (int, float))] or [0])
    return {"品数": len(L), "表示_平均": m("表示"), "検索で表示_平均": m("検索で表示"), "閲覧_平均": m("閲覧"), "閲覧0の品": sum(1 for i in L if i["閲覧"] == 0),
            "クリック率_平均%": m("クリック率"), "値段_中央": md("値段"), "日数_中央": md("日数"), "写真_平均": m("写真"), "項目_平均": m("項目"), "文字数_平均": m("文字数")}


W = [i for i in items if i["腕時計"]]
O = [i for i in items if not i["腕時計"]]
wr = [i for i in W if i.get("順位")]
out = {"時刻": jst(), "期間": "%s〜%s" % (start, end), "腕時計": agg(W), "ほか": agg(O),
       "腕時計の競合": {"調べた": len(wr), "最安": sum(1 for i in wr if i["順位"] == 1), "2番目": sum(1 for i in wr if i["順位"] == 2),
                    "3番目以下": sum(1 for i in wr if i["順位"] >= 3), "競合の数_中央": statistics.median([i["競合"] for i in wr] or [0]),
                    "米国の競合がいる品": sum(1 for i in wr if i.get("米国の競合")), "自分÷最安_中央": round(statistics.median([i["値段"] / i["競合の最安"] for i in wr if i.get("競合の最安")] or [0]), 2)},
       "腕時計_仕入元": dict(collections.Counter(i["仕入元"] for i in W)),
       "腕時計_ブランド": dict(collections.Counter(i["タイトル"].split()[0] for i in W if i["タイトル"]).most_common(10)),
       "腕時計の品": sorted(W, key=lambda i: -i["表示"])}
save_json(os.path.join(ROOT, "data", "判定", "腕時計の診断.json"), out)
print({k: out[k] for k in ("腕時計", "ほか", "腕時計の競合")})
