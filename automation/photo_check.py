"""出品中の品の写真の数を、仕入れ先の写真の数と比べる（読むだけ・手で動かす）。11/22 7:52 オーナー「仕入れ先の写真はすべて取得して、出品してるか確認して！」
- eBay：Inventory API の product.imageUrls の数。
- 仕入れ先：判定と出品と同じ読み方（more_photos）で、最初の3枚で止めずに全部数える（楽天は公式APIの最大3枚・メルカリ/Amazonは開かない）。
- 仕入れ先は1回に「見る上限」品まで（ページを開く間は4秒以上あける）。結果は data/判定/写真の点検.json"""
import collections, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, jst, read_ledger, save_json, hand_only
import judge_list as jl

LIMIT = int(os.environ.get("PHOTO_SRC_LIMIT", "150"))
eb = Ebay()
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")]


def src_of(u):
    u = str(u or "")
    for k, v in [("rakuten", "楽天"), ("paypayfleamarket", "Yahoo!フリマ"), ("auctions.yahoo", "ヤフオク"), ("shopping.yahoo", "Yahoo!ショッピング"),
                 ("mercari", "メルカリ"), ("amazon", "Amazon"), ("hardoff", "ハードオフ"), ("treasure-f", "トレファク")]:
        if k in u:
            return v
    return "ほかの店" if u else "仕入れ先なし"


out, t0 = [], time.time()
seen_src = collections.Counter()
for r in rows:
    if time.time() - t0 > 22 * 60:
        break
    try:
        n_eb = len((eb.inventory_item(r["SKU"]).get("product") or {}).get("imageUrls") or [])
    except EbayError:
        continue
    s = src_of(r.get("仕入元URL"))
    x = {"SKU": r["SKU"], "仕入れ先": s, "eBay": n_eb}
    if r.get("仕入元URL") and not hand_only(r["仕入元URL"]) and seen_src[s] < LIMIT // 6 + 5 and len([o for o in out if "仕入れ先の数" in o]) < LIMIT:
        seen_src[s] += 1
        try:
            ph = jl.more_photos({"url": r["仕入元URL"], "id": r["SKU"], "photos": []})
            x["仕入れ先の数"] = len(ph)
        except Exception as e:
            x["仕入れ先の数"] = None
        time.sleep(4)
    out.append(x)
by = collections.defaultdict(list)
for x in out:
    by[x["仕入れ先"]].append(x)
summ = {}
for s, xs in by.items():
    cmp = [x for x in xs if x.get("仕入れ先の数")]
    summ[s] = {"品": len(xs), "eBayの写真_平均": round(sum(x["eBay"] for x in xs) / len(xs), 1),
               "eBay_3枚以下": sum(1 for x in xs if x["eBay"] <= 3),
               "比べた品": len(cmp), "仕入れ先の写真_平均": round(sum(x["仕入れ先の数"] for x in cmp) / len(cmp), 1) if cmp else None,
               "仕入れ先より少ない": sum(1 for x in cmp if x["eBay"] < min(x["仕入れ先の数"], 24))}
save_json(os.path.join(ROOT, "data", "判定", "写真の点検.json"), {"時刻": jst(), "見た": len(out), "出品中": len(rows), "まとめ": summ, "品": out})
print("見た", len(out), "/", len(rows))
