# eBayのかわりの偽物で、値段の調整・移行の流れを通す（本物には出ない）
import os, sys, json, tempfile, shutil, csv, io, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["LEDGER_ROOT"] = tmp
root = os.environ.get("SETTINGS_ROOT") or os.path.join(os.path.dirname(__file__), "..", "..")   # 店の設定.json・時刻表.json のある所（データ置き場）
for f in ["店の設定.json", "時刻表.json"]: shutil.copy(os.path.join(root, f), tmp)
t = json.load(open(os.path.join(tmp, "時刻表.json")))
t["プログラム"]["値段の調整"]["実行"] = True
t["プログラム"]["今の出品の移行"]["実行"] = True
json.dump(t, open(os.path.join(tmp, "時刻表.json"), "w"), ensure_ascii=False)
os.environ.update(EBAY_CLIENT_ID="x", EBAY_CLIENT_SECRET="y", EBAY_REFRESH_TOKEN="z"); os.environ.pop("NOTIFY_WEBHOOK_URL", None)
import common, price_adjust as pa, migrate as mg
base = {"仕入値(円)": "10000", "出品時の海外送料(円)": "3000", "手数料率": "17.42%", "関税率": "15.0%", "固定費(円)": "0", "為替": "152", "状態": "出品中", "eBayの状態ID": "3000"}
with open(os.path.join(tmp, "台帳.csv"), "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=common.COLS); w.writeheader()
    w.writerow({**base, "SKU": "S-LOSS", "offerId": "O1", "eBayの出品ID": "1", "タイトル": "BOSS DS-1 Pedal", "出品日": "2026-11-10"})
    w.writerow({**base, "SKU": "S-OLD", "offerId": "O2", "eBayの出品ID": "2", "タイトル": "BOSS SD-1 Pedal", "出品日": "2026-09-01"})
    w.writerow({**base, "SKU": "S-MIG", "offerId": "", "eBayの出品ID": "3", "タイトル": "x", "仕入元URL": "https://netmall.hardoff.co.jp/product/5/"})
price = {"O1": 90.0, "O2": 300.0, "O3": 120.0}
status = {"O1": "PUBLISHED", "O2": "PUBLISHED", "O3": "PUBLISHED"}
sku2o = {"S-LOSS": "O1", "S-OLD": "O2", "S-MIG": "O3"}
class R:
    def __init__(s, b, code=200): s.b, s.status = json.dumps(b).encode(), code
    def read(s): return s.b
def opener(req, timeout=0):
    u = req.full_url; body = json.loads(req.data) if req.data and "oauth2" not in u else None
    if "oauth2/token" in u: return R({"access_token": "t", "expires_in": 7200})
    if "/sell/fulfillment/v1/order" in u: return R({"orders": [], "total": 0})
    if "rate_limit" in u: return R({"rateLimits": [{"resources": [{"rates": [{"remaining": 4000, "reset": "2026-11-19T07:00:00Z"}]}]}]})
    if "item_summary/search" in u:
        return R({"itemSummaries": [{"title": "BOSS DS-1 Distortion", "price": {"value": "150.00", "currency": "USD"}, "seller": {"username": "other"}, "legacyItemId": "99"},
                                    {"title": "BOSS DS-1 junk for parts", "price": {"value": "20.00", "currency": "USD"}, "seller": {"username": "x"}, "legacyItemId": "98"},
                                    {"title": "BOSS DS-1", "price": {"value": "10.00", "currency": "USD"}, "seller": {"username": "ihdj_81"}, "legacyItemId": "1"}]})
    if "/offer?sku=" in u:
        sku = urllib.parse.unquote(u.split("sku=")[1].split("&")[0]); o = sku2o[sku]
        return R({"offers": [{"offerId": o, "status": status[o], "listing": {"listingId": {"O3": "3"}.get(o, "")}, "pricingSummary": {"price": {"value": "%.2f" % price[o]}}}]})
    if "bulk_update_price_quantity" in u:
        out = []
        for q in body["requests"]:
            for of in q.get("offers", []): price[of["offerId"]] = float(of["price"]["value"])
            out.append({"statusCode": 200, "sku": q["sku"]})
        return R({"responses": out})
    if "/withdraw" in u:
        status[u.split("/offer/")[1].split("/")[0]] = "UNPUBLISHED"; return R({"listingId": "2"})
    if "bulk_migrate_listing" in u:
        return R({"responses": [{"listingId": "3", "statusCode": 200, "inventoryItems": [{"sku": "S-MIG", "offerId": "O3"}]}]})
    raise AssertionError("想定していない呼び出し " + u)
common.Ebay.__init__.__defaults__ = (opener,)
assert pa.main() == 0
rows = {r["SKU"]: r for r in common.read_ledger()}
f = common.floor_price(rows["S-LOSS"], common.settings())
print("S-LOSS", price["O1"], "最低利益", f, "| S-OLD", status["O2"], rows["S-OLD"]["状態"])
assert abs(price["O1"] - f) < 0.006 and rows["S-LOSS"]["売値(ドル)"] == "%.2f" % f, "赤字は最低利益まで上げて台帳も直す"
assert status["O2"] == "UNPUBLISHED" and rows["S-OLD"]["状態"] == "終了", "60日以上は終える"
rec = sorted(x for x in os.listdir(os.path.join(tmp, "data", "値段の調整")) if x[0].isdigit())
assert rec, "記録が残る"
assert mg.main() == 0
rows = {r["SKU"]: r for r in common.read_ledger()}
assert rows["S-MIG"]["offerId"] == "O3" and json.load(open(os.path.join(tmp, "data", "移行", "移した出品.json")))["S-MIG"]["offerId"] == "O3", "移行"
print("OK 偽物のeBayで通った")
