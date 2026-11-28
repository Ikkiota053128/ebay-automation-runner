"""お手本セラーの出品を分析する（読むだけ・手で動かす）。11/28 09:21 オーナー「この人の出品分析して！アメリカで回ってる商品も出品中心？それとも日本でしか手に入らない商品を出品してる？」
- お手本セラーの出品中の品（Browse・セラーで絞る）：カテゴリ・値段・送料・状態・タイトルの言葉（Tested・No English Menu・Japan Model など）。
- 型番の見本（最大100型番）ごとに同じ型番の即決の出品を検索：競合の数・米国から出している数・日本から出している数・このセラーの値段の順位。
- 結果は data/型番リスト/お手本セラーの分析.json。eBay の画面は開かない。"""
import collections, os, random, re, statistics, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, num
import flea_sweep as fs
from flea_sweep import gas_get_models
from model_grow import mkey

SELLER = (sys.argv[1] if len(sys.argv) > 1 else "s.kojiro")
CATS = {"625": "カメラ", "14324": "腕時計・宝飾", "293": "家電・オーディオ", "619": "楽器", "1492": "釣り"}
eb = Ebay()
gas = gas_get_models() or load_json(os.path.join(ROOT, "data", "型番リスト", "GASの写し.json"), {"models": []})
fs.MAKERS.update(str(m.get("maker", "")).strip().upper() for m in list(gas.get("models") or []) + load_json(os.path.join(ROOT, "data", "型番リスト", "追加.json"), [])
                 if len(str(m.get("maker", "")).strip()) >= 3)


def tot(c):
    sh = ((c.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value")
    return float((c.get("price") or {}).get("value") or 0) + float(sh or 0), (None if sh is None else float(sh))


items = []
for cid, cname in CATS.items():
    for page in range(5):
        prm = {"category_ids": cid, "filter": "sellers:{%s},buyingOptions:{FIXED_PRICE}" % SELLER, "limit": 200, "offset": page * 200}
        try:
            _, j = eb.call("GET", "/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(prm), kind="app", headers={"X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        except EbayError as e:
            print("browse", err_text(e)[:150])
            break
        its = j.get("itemSummaries") or []
        for it in its:
            it["_cat"] = cname
        items += its
        if page == 0:
            print(cname, "合計", j.get("total"))
        if len(its) < 200:
            break
W = {"Tested/Working": r"tested|working", "No English Menu": r"no english", "Japan Model/JDM/Japan only": r"japan(ese)? (model|version|only|edition)|\bjdm\b|domestic",
     "Box": r"\bbox\b", "Seller Japan/From Japan": r"from japan|seller japan|japan seller", "Rare": r"\brare\b", "Near Mint/Mint/Exc": r"\bmint\b|exc\+*|excellent"}
out = {"時刻": jst(), "セラー": SELLER, "読んだ品": len(items), "カテゴリ": dict(collections.Counter(i["_cat"] for i in items)),
       "状態": dict(collections.Counter(i.get("condition") or "?" for i in items).most_common(6)),
       "タイトルの言葉_%": {k: round(100 * sum(1 for i in items if re.search(v, i.get("title") or "", re.I)) / max(1, len(items)), 1) for k, v in W.items()}}
ps = [tot(i)[0] for i in items]
shs = [tot(i)[1] for i in items if tot(i)[1] is not None]
out["値段（送料こみ）"] = {"中央": round(statistics.median(ps), 2) if ps else None, "$100未満": sum(1 for p in ps if p < 100), "$100-200": sum(1 for p in ps if 100 <= p < 200),
                     "$200-300": sum(1 for p in ps if 200 <= p < 300), "$300以上": sum(1 for p in ps if p >= 300)}
out["送料"] = {"無料": sum(1 for s in shs if s == 0), "有料": sum(1 for s in shs if s > 0), "有料の中央": statistics.median([s for s in shs if s > 0]) if any(s > 0 for s in shs) else None}
out["発送地"] = dict(collections.Counter((i.get("itemLocation") or {}).get("country") for i in items))
# 型番ごとの競合
mods = {}
for i in items:
    g = fs.guess_model(i.get("title") or "")
    if g:
        mods.setdefault(mkey(g[1]), (g[0], g[1], i))
keys = list(mods)
random.seed(1)
random.shuffle(keys)
rows = []
for k in keys[:100]:
    mk, md, mine = mods[k]
    try:
        cs = eb.browse("%s %s" % (mk, md), "buyingOptions:{FIXED_PRICE}", limit=100)
    except EbayError as e:
        print("browse", err_text(e)[:120])
        break
    comp = [c for c in cs if k in mkey(c.get("title")) and (c.get("seller") or {}).get("username", "").lower() not in (SELLER.lower(), "ihdj_81")]
    us = sum(1 for c in comp if (c.get("itemLocation") or {}).get("country") == "US")
    jp = sum(1 for c in comp if (c.get("itemLocation") or {}).get("country") == "JP")
    mp = tot(mine)[0]
    allp = sorted(tot(c)[0] for c in comp)
    rows.append({"型番": "%s %s" % (mk, md), "このセラー$": round(mp, 2), "競合": len(comp), "米国": us, "日本": jp, "ほか": len(comp) - us - jp,
                 "順位": 1 + sum(1 for p in allp if p < mp), "米国の最安$": round(min([tot(c)[0] for c in comp if (c.get("itemLocation") or {}).get("country") == "US"] or [0]), 2) or None,
                 "No English Menu": bool(re.search(r"no english", mine.get("title") or "", re.I))})
n = len(rows)
if n:
    out["型番の見本"] = n
    out["競合"] = {"競合の数_中央": statistics.median([r["競合"] for r in rows]),
                 "米国の競合がいない型番": sum(1 for r in rows if r["米国"] == 0), "米国の競合1-2": sum(1 for r in rows if 1 <= r["米国"] <= 2),
                 "米国の競合3以上": sum(1 for r in rows if r["米国"] >= 3), "競合15以上": sum(1 for r in rows if r["競合"] >= 15),
                 "日本の競合だけ": sum(1 for r in rows if r["競合"] and r["米国"] == 0 and r["ほか"] == 0),
                 "このセラーが最安": sum(1 for r in rows if r["順位"] == 1), "このセラーが2番目": sum(1 for r in rows if r["順位"] == 2),
                 "このセラーが3番目以下": sum(1 for r in rows if r["順位"] >= 3),
                 "米国の最安より高い型番": sum(1 for r in rows if r["米国の最安$"] and r["このセラー$"] > r["米国の最安$"])}
    out["品"] = rows
save_json(os.path.join(ROOT, "data", "型番リスト", "お手本セラーの分析.json"), out)
print({k: v for k, v in out.items() if k != "品"})
