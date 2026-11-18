# ④ 一括の出品（教科書 第4章・キット⑩・CLAUDE.md 13章）
#  リサーチ・利益計算・送料の確認・GO の判定・出品前の検査は GAS（v661）。GAS が出品データ（JSON）を「GitHubで出品（待ち）」に置く。
#  このプログラムがそれを読み、Inventory API で 商品の登録 → オファーの作成 → 公開 → 読み直し → 台帳に1行 → GAS に結果、の順に進める。
#  作る前に SKU で照会し、途中で止まった品は続きからやる（二重に作らない）。
#  時刻表.json の「実行」が false の間はドライラン（出品データを点検するだけ。eBayには出さない・GASにも返さない）。
import json, os, sys, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (listing_limit_stopped, listing_limit_stop, is_limit_error)
from common import (ROOT, Ebay, EbayError, err_text, num, now, jst, settings, timetable, notify, notify_once_a_day,
                    read_ledger, save_ledger, write_run, mark_started, load_json, save_json)
from stock_watch import kind_of
from price_adjust import model_of
import re


def mkey(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def same_model(a, b):
    """同じ型番か：一致、または短いほう（5文字以上）が長いほうの頭（DW-6900RCS と DW-6900RCS-7JF は同じ）"""
    if not a or not b:
        return False
    s, l = sorted((a, b), key=len)
    return len(s) >= 5 and l.startswith(s)


def model_in(pl):
    for k, v in pl.get("aspects") or []:
        if k == "Model" and v and v != "Does not apply":
            return mkey(v)
    return mkey(model_of(pl.get("title")))

NAME = "一括の出品"
# Trading の ConditionID → Inventory API の condition（契約表16章の値）
COND = {1000: "NEW", 1500: "NEW_OTHER", 1750: "NEW_WITH_DEFECTS", 2000: "CERTIFIED_REFURBISHED", 2500: "SELLER_REFURBISHED",
        2750: "LIKE_NEW", 3000: "USED_EXCELLENT", 4000: "USED_VERY_GOOD", 5000: "USED_GOOD", 6000: "USED_ACCEPTABLE",
        7000: "FOR_PARTS_OR_NOT_WORKING"}
CL = {"Content-Language": "en-US"}


def gas_url():
    return os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()


def gas_queue():
    url, tok = gas_url()
    q = url + "?" + urllib.parse.urlencode({"page": "ghlistq", "token": tok})
    d = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "ebay-automation"}), timeout=120).read().decode("utf-8"))
    if d.get("error"):
        raise SystemExit("GAS の受け取り口に断られた：" + d["error"])
    return d.get("items", [])


def gas_post(data):
    url, tok = gas_url()
    body = urllib.parse.urlencode({"token": tok, "data": json.dumps(data, ensure_ascii=False)}).encode()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, data=body, headers={"User-Agent": "ebay-automation"}), timeout=300)
        return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303) and e.headers.get("Location"):
            return urllib.request.urlopen(e.headers["Location"], timeout=300).read().decode("utf-8", "replace")
        raise


def location_key(eb, cfg):
    k = cfg.get("店", {}).get("発送元の場所キー_merchantLocationKey", "")
    if k and not k.startswith("【"):
        return k
    p = os.path.join(ROOT, "data", "出品", "発送元の場所.json")
    c = load_json(p, {})
    if c.get("key"):
        return c["key"]
    _, j = eb.call("GET", "/sell/inventory/v1/location?limit=100")
    locs = [x for x in j.get("locations", []) if x.get("merchantLocationStatus", "ENABLED") == "ENABLED"]
    if not locs:
        raise SystemExit("発送元の場所（merchantLocationKey）が eBay に無い")
    save_json(p, {"key": locs[0]["merchantLocationKey"], "読んだ日時": jst()})
    return locs[0]["merchantLocationKey"]


def build(pl, loc):
    """GAS の出品データ → Inventory API の本文（契約表4章・5章）。足りなければ (None, None, 理由)"""
    cond = COND.get(int(num(pl.get("conditionId")) or 0))
    imgs = [u for u in pl.get("imageUrls") or [] if str(u).startswith("https://")]
    miss = [n for n, ok in (("タイトル", pl.get("title")), ("写真（https）", imgs), ("カテゴリ", pl.get("categoryId")),
                            ("状態の対応", cond), ("値段", (pl.get("price") or 0) > 0), ("説明文", pl.get("description")),
                            ("配送ポリシー", (pl.get("policies") or {}).get("fulfillment")),
                            ("支払いポリシー", (pl.get("policies") or {}).get("payment")),
                            ("返品ポリシー", (pl.get("policies") or {}).get("returns"))) if not ok]
    if miss:
        return None, None, "必須の入力が無い：" + "・".join(miss)
    aspects = {}
    for k, v in pl.get("aspects") or []:
        aspects.setdefault(k, [])
        if v not in aspects[k]:
            aspects[k].append(v)
    # 商品（inventory_item）の説明は4,000文字までなので入れない。出品の説明文はオファーの listingDescription に全部入れる
    item = {"product": {"title": pl["title"], "aspects": aspects, "imageUrls": imgs[:24]},
            "condition": cond, "availability": {"shipToLocationAvailability": {"quantity": int(pl.get("quantity") or 1)}}}
    if pl.get("ean"):
        item["product"]["ean"] = [pl["ean"]]
    if pl.get("conditionDescription") and cond not in ("NEW",):
        item["conditionDescription"] = pl["conditionDescription"][:1000]
    k = pl.get("pkg")
    if k:
        item["packageWeightAndSize"] = {
            "dimensions": {"length": k["lengthCm"], "width": k["widthCm"], "height": k["heightCm"], "unit": "CENTIMETER"},
            "weight": {"value": round(k["weightG"] / 1000.0, 3), "unit": "KILOGRAM"}}
    pol = {"fulfillmentPolicyId": pl["policies"]["fulfillment"], "paymentPolicyId": pl["policies"]["payment"],
           "returnPolicyId": pl["policies"]["returns"]}
    if pl.get("bestOffer"):
        pol["bestOfferTerms"] = pl["bestOffer"]
    if pl.get("shippingCostOverrides"):
        pol["shippingCostOverrides"] = pl["shippingCostOverrides"]
    offer = {"sku": pl["sku"], "marketplaceId": "EBAY_US", "format": "FIXED_PRICE", "listingDuration": "GTC",
             "availableQuantity": int(pl.get("quantity") or 1), "categoryId": str(pl["categoryId"]),
             "listingDescription": pl["description"], "listingPolicies": pol,
             "pricingSummary": {"price": {"value": "%.2f" % float(pl["price"]), "currency": "USD"}},
             "merchantLocationKey": loc}
    return item, offer, ""


def list_one(eb, pl, item, offer):
    """作る前に SKU で照会して、できている所の次から続ける。返事：(listingId, offerId)"""
    sku = pl["sku"]
    offs = eb.offers_of(sku)
    pub = [o for o in offs if o.get("status") == "PUBLISHED" and (o.get("listing") or {}).get("listingId")]
    if pub:   # 公開ずみで台帳に無い → そのまま使う
        return str(pub[0]["listing"]["listingId"]), pub[0]["offerId"]
    eb.call("PUT", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""), item, headers=CL)
    if offs:   # オファーはある → 中身を合わせてから公開だけやり直す
        oid = offs[0]["offerId"]
        eb.call("PUT", "/sell/inventory/v1/offer/" + oid, offer, headers=CL)
    else:
        try:
            _, j = eb.call("POST", "/sell/inventory/v1/offer", offer, headers=CL)
            oid = j["offerId"]
        except EbayError as e:
            again = eb.offers_of(sku)   # 返事が来なかった・もうあった → 照会してから（二重に作らない）
            if not again:
                raise
            oid = again[0]["offerId"]
    _, j = eb.call("POST", "/sell/inventory/v1/offer/%s/publish" % oid, {})
    lid = str(j.get("listingId", ""))
    chk = [o for o in eb.offers_of(sku) if o.get("offerId") == oid]   # 読み直して確かめる
    if not chk or chk[0].get("status") != "PUBLISHED" or str((chk[0].get("listing") or {}).get("listingId")) != lid:
        raise RuntimeError("公開したあとの読み直しで、出品中のオファーが見つからない（offerId %s）" % oid)
    return lid, oid


def main():
    cfg, tt = settings(), timetable(NAME)
    live = bool(tt.get("実行"))
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready() or not all(gas_url()):
        miss = [k for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN", "GAS_WEBAPP_URL", "GAS_SEND_TOKEN") if not os.environ.get(k, "").strip()]
        print("Secrets が空：" + "・".join(miss))
        notify_once_a_day("鍵なし_一括の出品", "【一括の出品】GitHub の Secrets が空なので、何もしていません：" + "・".join(miss))
        write_run(NAME, False, 0, 1)
        return 0
    ls = listing_limit_stopped()
    if ls and live:
        print("eBay の出品の上限に当たったので、%s まで出品しない（待ちの品はGASのシートに残る）" % ls["再開してよい時刻"][:16])
        write_run(NAME, True, 0, 0)
        return 0
    queue = gas_queue()
    cap = int(tt.get("1回の出品の上限_件", 50))
    if live and not tt.get("カナリア済み"):
        cap = min(cap, int(tt.get("カナリアの件数", 5)))
    loc = location_key(eb, cfg)
    led = read_ledger()
    ledger_skus = {r["SKU"] for r in led}
    # 同じ型番を2品出さない（オーナーの決めごと）：台帳で出品中の型番＋この回に出す型番
    live_models = [mkey(model_of(r.get("タイトル"))) for r in led if r.get("状態") == "出品中" and r.get("タイトル")]
    live_models = [m for m in live_models if m]
    done, bad, skip, results, rows = [], [], [], [], []
    for it in queue[:cap]:
        pl = it["payload"]
        if kind_of((pl.get("ledger") or {}).get("src", ""), cfg) not in ("A", "B", "C") or "mercari" in (pl.get("ledger") or {}).get("src", ""):   # 在庫の監視が見られない仕入元（フリマなど）は出さない
            skip.append((pl.get("sku"), "仕入元がA・C以外（GASで出品し直す）"))
            results.append({"sku": pl.get("sku"), "error": "差し戻し：仕入元がフリマ・その他の店なので、GitHubの在庫の監視が見られない。GASで出品し直す"})
            continue
        mk = model_in(pl)
        dup = next((m for m in live_models if same_model(mk, m)), None) if mk else None
        if dup:
            skip.append((pl.get("sku"), "同じ型番がもう出品中（%s）" % dup))
            if live:
                results.append({"sku": pl.get("sku"), "error": "見送り：同じ型番がもう出品中（%s・同じ型番は2品出さない）" % dup})
            continue
        if mk:
            live_models.append(mk)
        item, offer, why = build(pl, loc)
        if not item:
            skip.append((pl.get("sku"), why))
            if live:
                results.append({"sku": pl.get("sku"), "error": "見送り：" + why})
            continue
        if not live:
            done.append((pl["sku"], "（ドライラン）$%.2f %s" % (pl["price"], pl["title"][:50])))
            continue
        try:
            lid, oid = list_one(eb, pl, item, offer)
        except (EbayError, RuntimeError, KeyError) as e:
            et = err_text(e)
            if is_limit_error(et):   # 月の上限：この品は「待ち」のまま残す（GASに返さない）・次の月まで止める
                listing_limit_stop(et)
                bad.append((pl["sku"], "eBayの出品の上限（月）に当たった。待ちのまま残す"))
                break
            bad.append((pl["sku"], et))
            results.append({"sku": pl["sku"], "error": et})
            continue
        done.append((pl["sku"], lid))
        results.append({"sku": pl["sku"], "itemId": lid, "offerId": oid})
        lg = pl.get("ledger") or {}
        if pl["sku"] not in ledger_skus:
            rows.append({"SKU": pl["sku"], "eBayの出品ID": lid, "offerId": oid, "仕入元URL": lg.get("src", ""),
                         "仕入元の種類": kind_of(lg.get("src", ""), cfg), "仕入値(円)": lg.get("cost", ""),
                         "出品時の海外送料(円)": lg.get("ship", ""), "売値(ドル)": "%.2f" % float(pl["price"]), "状態": "出品中",
                         "出品日": now().strftime("%Y-%m-%d"), "タイトル": pl["title"], "eBayの状態ID": pl.get("conditionId", ""),
                         "手数料率": lg.get("feeRate", ""), "関税率": lg.get("dutyRate", ""), "固定費(円)": lg.get("fixed", ""),
                         "国内送料(円)": lg.get("dom", ""), "為替": lg.get("fx", ""), "移した日時": "", "最後に値段を変えた日時": "",
                         "メモ": "GitHubの一括の出品（v661）" + ("・送料：" + lg["note"] if lg.get("note") else "")})
    if rows:   # 成功した品だけ台帳に1行
        save_ledger(rows, list(rows[0].keys()), NAME)
    gas_note = ""
    if results and (live or all(r.get("error", "").startswith("差し戻し：") for r in results)):
        try:
            gas_note = gas_post({"kind": "ghlisted", "results": results})[:200]
        except Exception as e:   # 台帳とeBayは正しい。GASのシートへの書き戻しだけ失敗 → 知らせて次の回に任せない（人が見る）
            gas_note = "GASへの書き戻しに失敗：" + str(e)[:200]
    msg = ["【一括の出品】%s %s：待ち %d品・今回 %d品まで" % (jst(), "本番" if live else "ドライラン", len(queue), cap),
           "%s %d品・失敗 %d品・見送り %d品" % ("出品した" if live else "出せる形", len(done), len(bad), len(skip))]
    if live and not tt.get("カナリア済み") and done:
        msg.append("カナリア：公開ページを目で見て、よければ 時刻表.json の カナリア済み を true に")
    msg += ["・%s %s" % d for d in done[:15]]
    msg += ["失敗 %s：%s" % b for b in bad[:10]]
    msg += ["見送り %s：%s" % s for s in skip[:10]]
    if gas_note.startswith("GASへの書き戻しに失敗"):
        msg.append(gas_note)
    save_json(os.path.join(ROOT, "data", "出品", now().strftime("%Y%m%d_%H%M%S") + ".json"),
              {"時刻": jst(), "本番": live, "待ち": len(queue), "出品": done, "失敗": bad, "見送り": skip})
    write_run(NAME, not bad, len(done), len(bad))
    print("\n".join(msg))
    notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
