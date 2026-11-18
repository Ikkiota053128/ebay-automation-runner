# 一括の出品の試し（偽物のeBay・偽物のGAS。本物には出ない）
import os, sys, json, tempfile, shutil, csv, urllib.parse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["LEDGER_ROOT"] = tmp
root = os.environ.get("SETTINGS_ROOT") or os.path.join(os.path.dirname(__file__), "..", "..")   # 店の設定.json・時刻表.json のある所（データ置き場）
for f in ["店の設定.json", "時刻表.json"]: shutil.copy(os.path.join(root, f), tmp)
t = json.load(open(os.path.join(tmp, "時刻表.json"))); t["プログラム"]["一括の出品"]["実行"] = True
json.dump(t, open(os.path.join(tmp, "時刻表.json"), "w"), ensure_ascii=False)
os.environ.update(EBAY_CLIENT_ID="x", EBAY_CLIENT_SECRET="y", EBAY_REFRESH_TOKEN="z", GAS_WEBAPP_URL="https://script.google.com/x", GAS_SEND_TOKEN="t")
os.environ.pop("NOTIFY_WEBHOOK_URL", None)
import common, bulk_list as bl
with open(os.path.join(tmp, "台帳.csv"), "w", encoding="utf-8", newline="") as fh:
    csv.DictWriter(fh, fieldnames=common.COLS).writeheader()
base = {"title": "BOSS DS-1 Distortion Guitar Effects Pedal Used From Japan", "description": "<p>x</p>", "categoryId": "41415", "conditionId": 3000,
        "aspects": [["Brand", "BOSS"], ["Model", "DS-1"]], "imageUrls": ["https://i.ebayimg.com/a.jpg", "https://i.ebayimg.com/b.jpg"], "quantity": 1, "price": 120.0,
        "policies": {"fulfillment": "1", "payment": "2", "returns": "3"}, "bestOffer": {"bestOfferEnabled": True, "autoDeclinePrice": {"value": "100.00", "currency": "USD"}},
        "shippingCostOverrides": [], "pkg": {"weightG": 800, "lengthCm": 20, "widthCm": 15, "heightCm": 10},
        "ledger": {"src": "https://item.rakuten.co.jp/a/b/", "cost": 8000, "ship": 3000, "feeRate": 0.17, "dutyRate": 0.15, "fixed": 0, "dom": 0, "fx": 152}}
queue = [{"qrow": 2, "sku": "RAK-9001", "row": 10, "payload": dict(base, sku="RAK-9001")},
         {"qrow": 3, "sku": "RAK-9002", "row": 11, "payload": dict(base, sku="RAK-9002", imageUrls=["http://x/a.jpg"])},   # 欠け：https の写真なし
         {"qrow": 4, "sku": "RAK-9003", "row": 12, "payload": dict(base, sku="RAK-9003")}]                                 # 途中で止まっていた（オファーだけある）
offers = {"RAK-9003": [{"offerId": "O3", "status": "UNPUBLISHED"}]}
calls, posted = [], []
bl.gas_queue = lambda: queue
bl.gas_post = lambda d: posted.append(d) or '{"ok":true}'
class R:
    def __init__(s, b): s.b, s.status = json.dumps(b).encode(), 200
    def read(s): return s.b
def opener(req, timeout=0):
    u, m = req.full_url, req.get_method(); calls.append((m, u.split("ebay.com")[1] if "ebay.com" in u else u))
    if "oauth2/token" in u: return R({"access_token": "t", "expires_in": 7200})
    if "/location" in u: return R({"locations": [{"merchantLocationKey": "LOC1", "merchantLocationStatus": "ENABLED"}]})
    if "/offer?sku=" in u:
        sku = urllib.parse.unquote(u.split("sku=")[1].split("&")[0]); return R({"offers": offers.get(sku, [])})
    if m == "PUT" and "/inventory_item/" in u:
        b = json.loads(req.data); assert b["condition"] == "USED_EXCELLENT" and b["packageWeightAndSize"]["weight"]["unit"] == "KILOGRAM"
        assert req.headers.get("Content-language") == "en-US"; return R({})
    if m == "PUT" and "/offer/" in u: return R({})
    if m == "POST" and u.endswith("/offer"):
        b = json.loads(req.data); oid = "O" + b["sku"][-1]; offers[b["sku"]] = [{"offerId": oid, "status": "UNPUBLISHED"}]; return R({"offerId": oid})
    if "/publish" in u:
        oid = u.split("/offer/")[1].split("/")[0]
        for s, lst in offers.items():
            for o in lst:
                if o["offerId"] == oid: o["status"] = "PUBLISHED"; o["listing"] = {"listingId": "LID" + oid}
        return R({"listingId": "LID" + oid})
    raise AssertionError("想定していない呼び出し " + m + " " + u)
common.Ebay.__init__.__defaults__ = (opener,)
assert bl.main() == 0
res = {r["sku"]: r for r in posted[0]["results"]}
assert res["RAK-9001"]["itemId"] == "LIDO1" and res["RAK-9003"]["itemId"] == "LIDO3", res
assert res["RAK-9002"]["error"].startswith("見送り：必須の入力が無い：写真"), res
assert not any(m == "POST" and u.endswith("/offer") and "9003" in u for m, u in calls)
assert sum(1 for m, u in calls if m == "POST" and u.endswith("/offer")) == 1, "途中の品はオファーを作り直さない"
L = {r["SKU"]: r for r in common.read_ledger()}
assert set(L) == {"RAK-9001", "RAK-9003"} and L["RAK-9001"]["状態"] == "出品中" and L["RAK-9001"]["offerId"] == "O1"
print("OK 一括の出品（正常・欠け・途中から）")
