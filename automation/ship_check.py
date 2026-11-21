"""配送ポリシーの発送先を読む（読むだけ・手で動かす）。11/21 13:16 オーナー「発送対象国ちゃんとアメリカになっているか確認して！」
① EBAY_US の配送ポリシーを全部読み、アメリカ（国内）の配送サービス・除外地域・国際配送の行き先を書き出す
② 出品中の品（台帳）が、どの配送ポリシーを使っているかを getOffers で数える
結果は data/判定/発送先の確認.json（買い手の情報は扱わない）"""
import collections, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, save_json, read_ledger

eb = Ebay()
out = {"時刻": jst(), "ポリシー": [], "使っている数": {}, "読めなかった": []}
_, pj = eb.call("GET", "/sell/account/v1/fulfillment_policy?marketplace_id=EBAY_US")
for fp in pj.get("fulfillmentPolicies", []):
    dom, intl = [], []
    for o in fp.get("shippingOptions") or []:
        svc = [("%s%s" % (s.get("shippingServiceCode", ""), "（無料）" if s.get("freeShipping") else ""),
                [x.get("regionName") for x in ((s.get("shipToLocations") or {}).get("regionIncluded") or [])]) for s in o.get("shippingServices") or []]
        (dom if o.get("optionType") == "DOMESTIC" else intl).extend(svc)
    stl = fp.get("shipToLocations") or {}
    out["ポリシー"].append({"id": fp.get("fulfillmentPolicyId"), "名前": fp.get("name"), "発送日数": (fp.get("handlingTime") or {}).get("value"),
                         "アメリカ（国内）の配送": dom, "国際の配送": intl,
                         "行き先": [x.get("regionName") for x in stl.get("regionIncluded") or []],
                         "除外": [x.get("regionName") for x in stl.get("regionExcluded") or []]})
use = collections.Counter()
for r in read_ledger():
    if r.get("状態") != "出品中" or r.get("SKU", "").startswith("STK-"):
        continue
    try:
        offs = eb.offers_of(r["SKU"])
        pid = next((str((o.get("listingPolicies") or {}).get("fulfillmentPolicyId")) for o in offs if o.get("status") == "PUBLISHED"), None)
        use[pid or "公開中のオファー無し"] += 1
    except EbayError as e:
        out["読めなかった"].append(r["SKU"])
out["使っている数"] = dict(use.most_common())
save_json(os.path.join(ROOT, "data", "判定", "発送先の確認.json"), out)
print("ポリシー", len(out["ポリシー"]), "／出品中の品", sum(use.values()), "／読めなかった", len(out["読めなかった"]))
