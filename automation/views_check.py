"""出品ごとの閲覧数を読む（読むだけ・手で動かす）。11/19 12:12 オーナー「閲覧数がない、少ない商品はすべて終わらせて」（仕入れ先の無い225品だけ・30日で閲覧0回・出品から30日未満は除く）。
対象：data/判定/閲覧の確認_対象.json（[{"SKU", "出品ID", "始まり"}]）。eBay の集計の窓口（Analytics API traffic_report）で直近30日の閲覧数を読み、
data/判定/閲覧の確認_結果.json に書く。終えるのはこのプログラムではない（取り下げの一覧に入れて、判定と出品が終える）。"""
import datetime as dt, json, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, load_json, save_json, jst, now

tgt = load_json(os.path.join(ROOT, "data", "判定", "閲覧の確認_対象.json"), [])
eb = Ebay()
end = now().date() - dt.timedelta(days=1)
start = end - dt.timedelta(days=29)
views, errs = {}, []
ids = [t["出品ID"] for t in tgt if t.get("出品ID")]
for i in range(0, len(ids), 50):
    part = ids[i:i + 50]
    flt = "marketplace_ids:{EBAY_US},date_range:[%s..%s],listing_ids:{%s}" % (start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "|".join(part))
    path = "/sell/analytics/v1/traffic_report?" + urllib.parse.urlencode({"dimension": "LISTING", "metric": "LISTING_VIEWS_TOTAL", "filter": flt})
    try:
        _, j = eb.call("GET", path)
        for rec in j.get("records", []):
            lid = str((rec.get("dimensionValues") or [{}])[0].get("value", ""))
            v = (rec.get("metricValues") or [{}])[0].get("value")
            views[lid] = int(v or 0)
        for lid in part:
            views.setdefault(lid, 0)   # 記録が返らない出品は閲覧0
    except EbayError as e:
        errs.append(err_text(e)[:400])
        break
out = {"時刻": jst(), "期間": "%s〜%s（PT）" % (start, end), "閲覧数": views, "エラー": errs}
save_json(os.path.join(ROOT, "data", "判定", "閲覧の確認_結果.json"), out)
print("閲覧数を読んだ", len(views), "／対象", len(ids), "／エラー", len(errs), errs[:1])
sys.exit(1 if errs else 0)
