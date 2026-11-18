"""発送10営業日の配送ポリシーを作る（オフモール・トレファクの品用・11/18 21:46 オーナー「発送日数10日の設定で出します」）。
今の GitHub の配送ポリシー（327189638011・FedEx）をそのまま写し、発送までの日数だけ10日にする。同じ名前があれば作らず、それを使う。
結果：data/判定/発送10日のポリシー.json"""
import copy, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, err_text, EbayError, save_json, jst

NAME = "GitHub FedEx 10days (Off-Mall/Treasure)"
eb = Ebay()
_, lst = eb.call("GET", "/sell/account/v1/fulfillment_policy?marketplace_id=EBAY_US")
hit = next((p for p in lst.get("fulfillmentPolicies", []) if p.get("name") == NAME), None)
if not hit:
    _, src = eb.call("GET", "/sell/account/v1/fulfillment_policy/327189638011")
    body = copy.deepcopy(src)
    for k in ("fulfillmentPolicyId", "warnings"):
        body.pop(k, None)
    body["name"] = NAME
    body["description"] = "Handling 10 business days (Off-Mall / Treasure Factory). Copy of 327189638011."
    body["handlingTime"] = {"value": 10, "unit": "DAY"}
    for o in body.get("shippingOptions", []):
        o.pop("optionType_id", None)
    try:
        _, hit = eb.call("POST", "/sell/account/v1/fulfillment_policy", body)
    except EbayError as e:
        print("作れなかった：", err_text(e)[:800])
        sys.exit(1)
pid = str(hit.get("fulfillmentPolicyId"))
save_json(os.path.join(ROOT, "data", "判定", "発送10日のポリシー.json"), {"作った日時": jst(), "id": pid, "名前": NAME, "handlingTime": hit.get("handlingTime"),
                                                                    "アメリカに送れる": not any("US" in str(x) for x in ((hit.get("shipToLocations") or {}).get("regionExcluded") or []))})
print("ok", pid, hit.get("handlingTime"))
