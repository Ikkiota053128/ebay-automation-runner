"""ウォッチしている人（興味のある買い手）に、値下げのオファーを送る（手で動かす）。
11/24 19:49 オーナー「はい」（2：ウォッチした人へのオファー）。eBay の Negotiation API（find_eligible_items → send_offer_to_interested_buyers）。
- eBay が「送れる」と返した出品だけ（ウォッチされている出品）。決めごとA・有在庫（STK-）は外す。
- 値引きは 時刻表 オファー → 値引き_最大（はじめ10%）から1%ずつ下げて、値引き後の値段が最低利益の値段（common.floor_price）以上になる割合。値引き_最小（5%）に届かない品は送らない。
- オファーの期間は 2日。買い手が値段を言い返すこと（カウンター）はなし。
- data/判定/オファー.json：{"本番": false}。本番 false はドライラン。結果は data/判定/オファー_結果.json。同じ出品に送るのは7日に1回まで。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import notify, ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger, settings, timetable, floor_price, num

P = os.path.join(ROOT, "data", "判定", "オファー.json")
RP = os.path.join(ROOT, "data", "判定", "オファー_結果.json")
HD = {"X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
cfg = load_json(P, {"本番": False})
tt = timetable("オファー") or {}
live = bool(cfg.get("本番"))
mx, mn = int(tt.get("値引き_最大", 10)), int(tt.get("値引き_最小", 5))
st = settings()
eb = Ebay()
by_lid = {r.get("eBayの出品ID"): r for r in read_ledger() if r.get("状態") == "出品中"}
res = load_json(RP, {"送った": {}})
sent = res.setdefault("送った", {})
out = {"時刻": jst(), "本番": live, "送れる出品": 0, "予定": [], "送った": [], "送らない": [], "失敗": []}
lids, off = [], 0
while True:
    try:
        _, j = eb.call("GET", "/sell/negotiation/v1/find_eligible_items?limit=200&offset=%d" % off, headers=HD)
    except EbayError as e:
        out["失敗"].append({"どこ": "find_eligible_items", "エラー": err_text(e)[:400]})
        break
    items = (j or {}).get("eligibleItems") or []
    lids += [x.get("listingId") for x in items if x.get("listingId")]
    if len(items) < 200:
        break
    off += 200
out["送れる出品"] = len(lids)
now_t = time.time()
for lid in lids:
    r = by_lid.get(lid)
    if not r or r["SKU"].startswith("STK-"):
        out["送らない"].append({"出品ID": lid, "理由": "台帳に出品中で無い・有在庫"})
        continue
    if now_t - float((sent.get(lid) or {}).get("t", 0)) < 7 * 86400:
        out["送らない"].append({"SKU": r["SKU"], "理由": "7日以内に送った"})
        continue
    price, fp = num(r.get("売値(ドル)")) or 0, floor_price(r, st)
    if not price or not fp:
        out["送らない"].append({"SKU": r["SKU"], "理由": "最低利益の値段が出せない"})
        continue
    pct = next((p for p in range(mx, mn - 1, -1) if price * (1 - p / 100) >= fp), None)
    if pct is None:
        out["送らない"].append({"SKU": r["SKU"], "理由": "%d%%引きでも最低利益を割る（$%.2f・フロア $%.2f）" % (mn, price, fp)})
        continue
    plan = {"SKU": r["SKU"], "出品ID": lid, "値段": price, "値引き": pct, "オファーの値段": round(price * (1 - pct / 100), 2), "フロア": fp, "タイトル": (r.get("タイトル") or "")[:60]}
    if not live:
        out["予定"].append(plan)
        continue
    body = {"allowCounterOffer": False, "message": "Thank you for watching! Here is a special price just for you. Ships from Okinawa, Japan.",
            "offerDuration": {"unit": "DAY", "value": 2},
            "offeredItems": [{"listingId": lid, "discountPercentage": str(pct), "quantity": 1}]}
    try:
        eb.call("POST", "/sell/negotiation/v1/send_offer_to_interested_buyers", body, headers=HD)
        sent[lid] = {"t": now_t, "値引き": pct, "日時": jst()}
        out["送った"].append(plan)
    except EbayError as e:
        out["失敗"].append(dict(plan, エラー=err_text(e)[:400]))
if live:
    cfg["本番"] = False
    save_json(P, cfg)
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "送れる", out["送れる出品"], "予定", len(out["予定"]), "送った", len(out["送った"]), "送らない", len(out["送らない"]), "失敗", len(out["失敗"]))
L = out["送った"] or out["予定"]
notify("【ウォッチした人へのオファー】%s %s 送れる出品%d・%s%d品%s\n%s" % (jst(), "本番" if live else "ドライラン（送っていない）", out["送れる出品"], "送った" if live else "送る予定",
       len(L), ("・失敗%d" % len(out["失敗"])) if out["失敗"] else "", "\n".join("%s %d%%引き $%.2f→$%.2f（フロア $%.2f）" % (p["SKU"], p["値引き"], p["値段"], p["オファーの値段"], p["フロア"]) for p in L[:20])))
