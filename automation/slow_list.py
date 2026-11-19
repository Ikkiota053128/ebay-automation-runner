"""売れていない出品の一覧（読むだけ・手で動かす）：eBay の出品中（GetMyeBaySelling ActiveList）の 出品の始まり・ウォッチ数・値段を読み、
出してからの日数が長い順に data/上限/売れていない出品.json に書く。終えるのはオーナーの承認のあと（このプログラムは何も変えない）"""
import datetime as dt, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, save_json, jst, now, read_ledger

eb = Ebay()
items, page = [], 1
while True:
    x = eb.trading("GetMyeBaySelling", "<ActiveList><Include>true</Include><Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>%d</PageNumber></Pagination></ActiveList><DetailLevel>ReturnAll</DetailLevel>" % page)
    # 11/19 12:07 オーナー「一覧を直して」：ReturnAll では売れた・売れなかった（終了）の一覧も一緒に返るので、ActiveList の中だけを読む
    al = (re.search(r"<ActiveList>([\s\S]*?)</ActiveList>", x) or [None, ""])[1]
    for b in re.findall(r"<Item>([\s\S]*?)</Item>", al):
        g = lambda t: (re.search(r"<%s[^>]*>([^<]*)</%s>" % (t, t), b) or [None, ""])[1]
        items.append({"出品ID": g("ItemID"), "SKU": g("SKU"), "タイトル": g("Title")[:80], "値段": float(g("CurrentPrice") or 0),
                      "始まり": g("StartTime")[:10], "ウォッチ": int(g("WatchCount") or 0),
                      "在庫": int(g("QuantityAvailable") or (int(g("Quantity") or 0) - int((re.search(r"<QuantitySold>(\d+)</QuantitySold>", b) or [None, "0"])[1])))})
    tp = int((re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", al) or [None, "1"])[1])
    total_entries = int((re.search(r"<TotalNumberOfEntries>(\d+)</TotalNumberOfEntries>", al) or [None, "0"])[1])
    if page >= tp:
        break
    page += 1
items = list({i["出品ID"]: i for i in items}.values())
if total_entries and len(items) != total_entries:
    print("注意：eBayが言う出品中の数 %d と、読めた数 %d が違う" % (total_entries, len(items)))   # ページの読み直しで同じ品が何度も返ることがある → 出品IDで1つに
today = now().date()
for it in items:
    try:
        it["日数"] = (today - dt.date.fromisoformat(it["始まり"])).days
    except Exception:
        it["日数"] = None
items.sort(key=lambda i: -(i["日数"] or 0))
b = {"60日以上": [i for i in items if (i["日数"] or 0) >= 60], "30〜59日": [i for i in items if 30 <= (i["日数"] or 0) < 60]}
save_json(os.path.join(ROOT, "data", "上限", "売れていない出品.json"), {"時刻": jst(), "eBayが言う出品中の数": total_entries, "出品中": len(items), "合計ドル": round(sum(i["値段"] for i in items), 2), "在庫1以上": sum(1 for i in items if i["在庫"] > 0),
          "在庫1以上の合計ドル": round(sum(i["値段"] for i in items if i["在庫"] > 0), 2),
          "60日以上": b["60日以上"], "30〜59日": b["30〜59日"]})
save_json(os.path.join(ROOT, "data", "上限", "eBayの出品中.json"), {"時刻": jst(), "品": [{k: i[k] for k in ("出品ID", "SKU", "値段", "在庫", "始まり", "ウォッチ", "タイトル")} for i in items]})
print("ok", len(items), {k: (len(v), round(sum(i["値段"] for i in v))) for k, v in b.items()})
