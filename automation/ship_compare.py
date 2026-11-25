"""自分の店と、同じ型番の競合の「配送のしかた」を比べる（読むだけ・手で動かす）。
11/25 11:34 オーナー「私のショップと周りの競合は私より配送方法違うか確認して！」
- 出品中の品から SHIP_N 品（売値の高い順にばらけるように）を選び、自分の出品と、同じ型番の競合（最大4品・日本から発送の品を優先）を
  Browse の getItem で読む（米国 ニューヨーク 10001 の買い手として）。
- 比べる：送料（無料か・いくら）・配送サービス（FedEx/DHL/SpeedPAK/日本郵便など）・お届け予定日（最短〜最長の日数）・発送までの日数・
  発送元の国・返品（日数・送料はだれが払う）・輸入税の表示。
- 結果は data/判定/配送の比べ.json。eBay の画面は開かない（API だけ）。"""
import collections, datetime as dt, os, re, statistics, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger

HD = {"X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=10001"}
N = int(os.environ.get("SHIP_N", "40"))
eb = Ebay()
today = dt.date.today()


def get(item_id):
    _, g = eb.call("GET", "/buy/browse/v1/item/" + urllib.parse.quote(item_id, safe=""), kind="app", headers=HD)
    return g


def days(s):
    try:
        return (dt.date.fromisoformat(s[:10]) - today).days
    except Exception:
        return None


def summary(g):
    so = (g.get("shippingOptions") or [{}])
    s = so[0] if so else {}
    cost = float((s.get("shippingCost") or {}).get("value") or 0)
    rt = g.get("returnTerms") or {}
    ad = " ".join(str(x) for x in [g.get("importCharges"), (s.get("importCharges") if s else None)] if x)
    return {"送料_ドル": cost, "無料": cost == 0,
            "サービス": (s.get("shippingServiceCode") or s.get("shippingCarrierCode") or s.get("type") or "?"),
            "最短_日": days(s.get("minEstimatedDeliveryDate") or ""), "最長_日": days(s.get("maxEstimatedDeliveryDate") or ""),
            "発送元": ((g.get("itemLocation") or {}).get("country") or ""),
            "返品": ("%s日・%s" % ((rt.get("returnPeriod") or {}).get("value", "?"), "送料は売り手" if rt.get("returnShippingCostPayer") == "SELLER" else "送料は買い手")) if rt.get("returnsAccepted") else "返品なし",
            "輸入税の表示": "あり" if ad else "なし",
            "値段_ドル": float((g.get("price") or {}).get("value") or 0)}


rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("eBayの出品ID") and len((r.get("タイトル") or "").split()) > 1]
rows.sort(key=lambda r: -float(r.get("売値(ドル)") or 0))
step = max(1, len(rows) // N)
pick = rows[::step][:N]
mine_ids = {r["eBayの出品ID"] for r in rows}
out = {"時刻": jst(), "品": [], "まとめ": {}, "失敗": []}
me_all, comp_all, comp_jp = [], [], []
for r in pick:
    try:
        g = get("v1|%s|0" % r["eBayの出品ID"])
        me = summary(g)
    except EbayError as e:
        out["失敗"].append({"SKU": r["SKU"], "エラー": err_text(e)[:200]})
        continue
    t = r["タイトル"].split()
    model = t[1]
    md = re.sub(r"[^0-9A-Z]", "", model.upper())
    try:
        its = eb.browse("%s %s" % (t[0], model), "buyingOptions:{FIXED_PRICE}", limit=50)
    except EbayError as e:
        out["失敗"].append({"SKU": r["SKU"], "エラー": err_text(e)[:200]})
        continue
    its = [x for x in its if str(x.get("legacyItemId")) not in mine_ids and (x.get("seller") or {}).get("username", "").lower() != "ihdj_81"
           and md in re.sub(r"[^0-9A-Z]", "", (x.get("title") or "").upper())]
    its.sort(key=lambda x: 0 if (x.get("itemLocation") or {}).get("country") == "JP" else 1)
    comps = []
    for x in its[:4]:
        try:
            c = summary(get(x["itemId"]))
            c["売り手"] = "日本" if c["発送元"] == "JP" else c["発送元"]
            comps.append(c)
        except EbayError:
            continue
    me_all.append(me)
    comp_all += comps
    comp_jp += [c for c in comps if c["発送元"] == "JP"]
    out["品"].append({"SKU": r["SKU"], "自分": me, "競合": comps})


def agg(L):
    if not L:
        return {}
    med = lambda k: statistics.median([x[k] for x in L if isinstance(x.get(k), (int, float))] or [0])
    return {"品数": len(L), "送料無料の割合": "%d%%" % round(100 * sum(x["無料"] for x in L) / len(L)),
            "送料の中央値_ドル": med("送料_ドル"), "お届け最短の中央値_日": med("最短_日"), "お届け最長の中央値_日": med("最長_日"),
            "配送サービス": dict(collections.Counter(x["サービス"] for x in L).most_common(6)),
            "返品": dict(collections.Counter(x["返品"] for x in L).most_common(4)),
            "発送元": dict(collections.Counter(x["発送元"] for x in L).most_common(4))}


out["まとめ"] = {"自分": agg(me_all), "競合（全部）": agg(comp_all), "競合（日本から発送）": agg(comp_jp)}
faster = sum(1 for p in out["品"] for c in p["競合"] if c["最長_日"] is not None and p["自分"]["最長_日"] is not None and c["最長_日"] < p["自分"]["最長_日"])
out["まとめ"]["自分より早く届く競合"] = faster
save_json(os.path.join(ROOT, "data", "判定", "配送の比べ.json"), out)
print(out["まとめ"])
