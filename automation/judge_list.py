"""判定と出品（GitHubだけで）：店の地引網の「送る待ち」から、GitHub が判定（利益・送料・eBayの相場・GO）と出品データ作りをして、そのまま出品する。

- 1回に見る数は 時刻表 の「1回に判定する上限_件」。同じ型番は1回に1品（一番安い仕入値）。もう出品中の型番は出さない（台帳・この回）。
- カテゴリは eBay の同じ型番の競合のカテゴリ（多数決・半分以上）。決めてある種類（カメラ・時計・レンズ・エフェクター…）だけ扱う。
  それ以外・競合が2件未満・状態が読めない品は「GASへ」（店の地引網が今までどおり GAS に送る）。
- 重さ・箱・タイトルの言葉・項目は、種類ごとに GAS で出した実績の値（data/判定/種類.json）。送料は FedEx の表。
- 値段・利益の条件は judge.py（GAS の quotePrice_ と同じ）。
- 時刻表の「実行」が false の間は影の運転（判定と出品データを記録するだけ）。本番の最初はカナリア。
- 出した品は台帳に1行・GAS へ kind=ghnew（「GASにv664」が true のときだけ）。GAS の出品一覧に載り、GAS が同じ型番を出さない。
- 検索（Browse）の残りが「Browseの残りの下限」より少ないときは止める（GAS の分を残す）。
"""
import collections, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, Ebay, EbayError, err_text, now, jst, settings, timetable, notify, read_ledger, save_ledger, write_run,
                    mark_started, load_json, save_json, browse_stopped, browse_stop, listing_limit_stopped, listing_limit_stop,
                    is_limit_error)
from price_adjust import model_of
import judge
from bulk_list import build, list_one, location_key, mkey, same_model
from stock_watch import kind_of

NAME = "判定と出品"
HERE = os.path.dirname(os.path.abspath(__file__))
BRAND_JA = {"カシオ": "Casio", "ソニー": "Sony", "シチズン": "Citizen", "セイコー": "Seiko", "キヤノン": "Canon", "キャノン": "Canon",
            "ニコン": "Nikon", "オリンパス": "Olympus", "ペンタックス": "Pentax", "パナソニック": "Panasonic", "富士フイルム": "Fujifilm",
            "フジフイルム": "Fujifilm", "リコー": "Ricoh", "ボス": "BOSS", "ローランド": "Roland", "ヤマハ": "Yamaha", "シマノ": "Shimano",
            "ダイワ": "Daiwa", "タムロン": "Tamron", "シグマ": "Sigma", "オーディオテクニカ": "Audio-Technica", "デノン": "Denon"}
KEEP_CAPS = {"BOSS", "MXR", "TEAC", "AKAI", "JVC", "TDK", "SMC", "EHX"}
COND_DESC = "Used. NOT TESTED - we have not tested this item and its function is not confirmed. Please judge from the photos."


def brand_of(maker):
    m = str(maker or "").strip()
    if m in BRAND_JA:
        return BRAND_JA[m]
    if m.upper() in KEEP_CAPS:
        return m.upper()
    return m[:1].upper() + m[1:].lower() if m.isupper() or m.islower() else m


def photos_of(c):
    out = []
    for u in c.get("photos") or []:
        u = str(u)
        if "item-shopping.c.yimg.jp/i/" in u:   # Yahoo! の小さい画像 → 600px
            u = re.sub(r"/i/[a-z]/", "/i/n/", u)
        if u.startswith("https://") and u not in out:
            out.append(u)
    return out[:12]


BAD_CAT = re.compile(r"part|accessor|case|bag|strap|cable|charger|battery|book|manual|video game|game|toy|figure|doll|card|"
                     r"amplifier|speaker|furniture|guitar$|bass$|drum|keyboard|piano|tripod|stand", re.I)


def auto_kind(cat, kinds):
    """決めてある種類に無いカテゴリ：名前は eBay のカテゴリ名、重さと箱は前に出した実績（型番の実績）のそのカテゴリで一番多い値、
    無ければ安全側の 1,200g・26x20x16（送料を多めに見る）。付属品・ゲーム・大きい物のカテゴリは扱わない"""
    name = judge.CAT_NAMES.get(cat, "")
    if not cat or not name or BAD_CAT.search(name):
        return None
    profs = load_json(os.path.join(ROOT, "data", "判定", "型番の実績.json"), {})
    pk = collections.Counter((p["重さ_g"], p["箱"]) for p in profs.values() if str(p.get("カテゴリ")) == cat and p.get("発送") == "FedEx").most_common(1)
    w, bx = pk[0][0] if pk else (1200, "26x20x16")
    word = re.sub(r"\s*&.*$|\s*\(.*\)$", "", name).strip()
    word = re.sub(r"s$", "", word) if len(word) > 4 and not word.endswith("ss") else word
    return {"名前": "自動：" + name, "言葉": word[:30], "重さ_g": int(w), "箱": bx, "項目": ["Type"], "手数料率": 0.1742, "関税率": 0.15,
            "ポリシー": {"発送": "327189638011", "支払い": "318927569011", "返品": "318925133011"}}


_IPW = None


def ip_bad(title):
    global _IPW
    if _IPW is None:
        _IPW = [w for w in load_json(os.path.join(ROOT, "data", "判定", "IPの辞書.json"), []) if w["段階"] != "注意（条件つきで出品可）"]
    t = str(title or "").lower()
    for w in _IPW:
        if re.search(r"(?<![a-z])" + re.escape(w["言葉"].lower()) + r"(?![a-z])", t):
            return w["言葉"]
    return ""


def gas_cands():
    """GAS が見つけた候補（仕入れ先の検索結果の ✅ 上限以内・v667 page=ghcands）を、型番リストで型番を読んで候補にする"""
    try:
        import urllib.parse, urllib.request
        from flea_sweep import gas_get_models, compile_models, match
        url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
        if not (url and tok):
            return []
        q = url + "?" + urllib.parse.urlencode({"page": "ghcands", "token": tok, "hours": 48})
        d = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "ebay-automation"}), timeout=120).read().decode("utf-8"))
        ms = compile_models((gas_get_models() or {"models": []})["models"])
        out = []
        for it in d.get("items", []):
            hit = match(it["title"], ms)
            if not hit or not it.get("price"):
                continue
            m = hit[0] if isinstance(hit, list) else hit
            out.append({"id": "gas:" + it["url"], "title": it["title"], "price": int(it["price"]), "url": it["url"],
                        "photos": [u for u in str(it.get("thumb", "")).split("\n") if u.startswith("http")],
                        "型番": m["model"], "メーカー": m["maker"], "src": re.sub(r"（.*$", "", it.get("site", "GAS")) or "GAS", "cap": int(it.get("cap") or 0)})
        return out
    except Exception as e:
        print("GASの候補を読めなかった：", type(e).__name__)
        return []


def more_photos(c):
    """Yahoo!ショッピングは、APIの写真が1枚だけ。商品ページ（GitHub から読める）から同じ商品の写真（_1, _2 …）を集める。楽天のページは読めない"""
    ph = photos_of(c)
    if len(ph) >= 3:
        return ph
    if "store.shopping.yahoo.co.jp" not in c.get("url", ""):   # ほかの店・フリマ・ヤフオク：商品ページの JSON-LD とヤフオクの画像から集める（メルカリは見ない）
        if "mercari" in c.get("url", "") or "item.rakuten.co.jp" in c.get("url", ""):
            return ph
        try:
            from stock_watch import fetch
            from store_sweep import ld_product
            from flea_sweep import IMG_RX
            code, html = fetch(c["url"])
            if code == 200:
                p = ld_product(html) or {}
                ho = [u for u in re.findall(r"https://[a-z0-9\-]+\.imageflux\.jp/[^\"'\s)]+\.(?:jpe?g|png|webp)[^\"'\s)]*", html)
                      if not re.search(r"blankimg|noimage|icon|logo|banner|/portal/", u) and int((re.search(r"w=(\d+)", u) or [0, 9999])[1]) >= 600]
                for u in (p.get("photos") or []) + IMG_RX.findall(html) + ho:
                    if u.startswith("https://") and u not in ph:
                        ph.append(u)
        except Exception:
            pass
        return ph[:12]
    try:
        from stock_watch import fetch
        code, html = fetch(c["url"])
        if code != 200:
            return ph
        m = re.search(r"/i/[a-z]/([A-Za-z0-9\-]+_[A-Za-z0-9\-]+)", ph[0]) if ph else None
        base = m.group(1) if m else ""
        for u in re.findall(r"https://item-shopping\.c\.yimg\.jp/i/[a-z]/([A-Za-z0-9_\-]+)", html):
            if base and not u.startswith(base):
                continue
            uu = "https://item-shopping.c.yimg.jp/i/n/" + u
            if uu not in ph:
                ph.append(uu)
        return ph[:12]
    except Exception:
        return ph


def make_payload(c, kind, cat, cond, price, fp, ship, sku):
    brand, model = brand_of(c["メーカー"]), c["型番"]
    cw = "New" if cond < 3000 else "Used"
    title = re.sub(r"\s+", " ", "%s %s %s %s From Japan" % (brand, model, kind["言葉"], cw)).strip()[:80]
    html = open(os.path.join(HERE, "desc_template.html"), encoding="utf-8").read()
    html = (html.replace("{{TITLE}}", title).replace("{{BRAND}}", brand).replace("{{MODEL}}", model)
            .replace("{{COND}}", "New" if cond < 3000 else "Used")
            .replace("{{FUNC}}", "New item." if cond < 3000 else "Not tested. Please check the photos."))
    asp = [["Brand", brand], ["Model", model]] + [[k, "Does not apply"] for k in kind["項目"]] + \
          [["Shipping Method", "FedEx International Connect Plus (tracked)"]]
    w, (l, wd, h) = kind["重さ_g"], sorted([float(x) for x in kind["箱"].split("x")], reverse=True)
    pol = kind.get("ポリシー") or {}
    pl = {"sku": sku, "title": title, "description": html, "categoryId": cat, "conditionId": cond, "aspects": asp,
          "imageUrls": c.get("_photos") or photos_of(c), "quantity": 1, "price": price, "ean": "",
          "policies": {"fulfillment": pol.get("発送", "327189638011"), "payment": pol.get("支払い", "318927569011"),
                       "returns": pol.get("返品", "318925133011")},
          "bestOffer": {"bestOfferEnabled": True, "autoDeclinePrice": {"value": "%.2f" % fp, "currency": "USD"},
                        "autoAcceptPrice": {"value": "%.2f" % (fp + 0.01), "currency": "USD"}},
          "pkg": {"weightG": w, "lengthCm": l, "widthCm": wd, "heightCm": h},
          "ledger": {"src": c["url"], "cost": c["price"], "ship": ship, "feeRate": kind.get("手数料率", 0.1742),
                     "dutyRate": kind.get("関税率", 0.15), "fixed": 0, "dom": c.get("dom", 2000), "fx": 152,
                     "note": "GitHubの判定（%s）" % kind["名前"]}}
    if cond >= 3000:
        pl["conditionDescription"] = COND_DESC
    if fp >= price:   # フロアの値段で出すときは、値下げの交渉を受けない
        pl["bestOffer"] = {"bestOfferEnabled": False}
    return pl


AD_NAME = "eBayツール 自動広告（上限5.1%）"


def promote_new(eb, rate):
    """GitHub で出した出品（台帳のメモ「GitHubの判定と出品」・出品中）に広告（プロモーテッド・売れたときだけ払う）を付ける。
    GAS と同じキャンペーン。広告率は 手数料率（17.42%）に入れてある広告の見込みの中。1件ずつ結果を見る"""
    p = os.path.join(ROOT, "data", "判定", "広告済み.json")
    done = load_json(p, {})
    ids = [r["eBayの出品ID"] for r in read_ledger() if r.get("offerId") and r.get("状態") == "出品中"   # GitHub が見ている出品すべて（広告の点検もGitHubで）
           and r.get("eBayの出品ID") and r["eBayの出品ID"] not in done]
    if not ids:
        return ""
    try:
        _, j = eb.call("GET", "/sell/marketing/v1/ad_campaign?limit=200")
        c = [x for x in j.get("campaigns", []) if x.get("campaignName") == AD_NAME and x.get("campaignStatus") != "ENDED"]
        if not c:
            return "広告：GASのキャンペーンが見つからない"
        cid = c[0]["campaignId"]
        ok, bad = 0, []
        for i in range(0, len(ids), 50):
            part = ids[i:i + 50]
            _, r = eb.call("POST", "/sell/marketing/v1/ad_campaign/%s/bulk_create_ads_by_listing_id" % cid,
                           {"requests": [{"listingId": x, "bidPercentage": "%.1f" % rate} for x in part]})
            for res in r.get("responses", []):
                lid = str(res.get("listingId", ""))
                if int(res.get("statusCode") or 0) < 300 or "already" in json.dumps(res.get("errors", ""), ensure_ascii=False).lower():
                    done[lid] = jst()
                    ok += 1
                else:
                    bad.append("%s %s" % (lid, json.dumps(res.get("errors", ""), ensure_ascii=False)[:150]))
        save_json(p, done)
        return "広告を付けた %d品%s" % (ok, ("／できなかった：" + " / ".join(bad[:3])) if bad else "")
    except EbayError as e:
        return "広告でエラー：" + err_text(e)[:200]


def next_sku(c, n):
    p = os.path.join(ROOT, "data", "判定", "SKUの番号.json")
    d = load_json(p, {"n": 0})
    d["n"] = int(d["n"]) + 1
    save_json(p, d)
    code = {"楽天": "RK", "Yahoo!": "YS", "イシバシ楽器": "IS", "カメラの八百富": "YT", "フジヤカメラ": "FJ", "トレファク": "TF", "ハードオフ": "HO"}.get(c["src"], "ST")
    return "G%s-%06d" % (code, d["n"])


def withdraw_asked(eb, live):
    """オーナーに「出品をやめて」と言われた品（data/判定/取り下げ.json の SKU）を終える：withdraw → 読み直して UNPUBLISHED → 台帳を「終了」"""
    p = os.path.join(ROOT, "data", "判定", "取り下げ.json")
    d = load_json(p, {"待ち": [], "済み": []})
    if not d.get("待ち") or not live:
        return ""
    led = {r["SKU"]: r for r in read_ledger()}
    ok, bad, rows = [], [], []
    for sku in list(d["待ち"]):
        r = led.get(sku)
        if not r or not r.get("offerId"):
            bad.append((sku, "台帳に offerId が無い"))
            continue
        try:
            o = [x for x in eb.offers_of(sku) if x.get("offerId") == r["offerId"]]
            if o and o[0].get("status") == "PUBLISHED":
                eb.withdraw(r["offerId"])
            o = [x for x in eb.offers_of(sku) if x.get("offerId") == r["offerId"]]
            if o and o[0].get("status") != "UNPUBLISHED":
                raise RuntimeError("読み直しても UNPUBLISHED になっていない")
            rows.append({"SKU": sku, "状態": "終了", "メモ": (r.get("メモ", "") + "・%s オーナーの指示で出品をやめた" % jst())[:500]})
            ok.append(sku)
            d["待ち"].remove(sku)
            d["済み"].append({"SKU": sku, "時刻": jst()})
        except (EbayError, RuntimeError) as e:
            bad.append((sku, err_text(e)[:300]))
    if rows:
        save_ledger(rows, ["状態", "メモ"], NAME)
    save_json(p, d)
    return "出品をやめた：%s%s" % ("・".join(ok) or "なし", ("／できなかった：" + " / ".join("%s %s" % b for b in bad)) if bad else "")


def main():
    cfg, tt = settings(), timetable(NAME)
    live = bool(tt.get("実行"))
    mark_started(NAME)
    eb = Ebay()
    if not eb.ready():
        write_run(NAME, False, 0, 1)
        print("eBay の鍵が無い")
        return 0
    wd_note = withdraw_asked(eb, live)
    if wd_note:
        print(wd_note)
        notify("【判定と出品】" + wd_note)
        wd_note = ""
    ls = listing_limit_stopped()
    if ls and live:
        print("eBay の出品の上限に当たったので、%s まで出品しない（判定もしない）" % ls["再開してよい時刻"][:16])
        ad = promote_new(eb, float(tt.get("広告率", 2.0)))
        if ad:
            print(ad)
            notify("【判定と出品】" + ad)
        write_run(NAME, True, 0, 0)
        return 0
    if browse_stopped():
        write_run(NAME, True, 0, 0)
        print("検索の回数上限で止めている")
        return 0
    rem = eb.browse_remaining() or {}
    floor_left = int(tt.get("Browseの残りの下限", 1500))
    if rem.get("remaining") is not None and int(rem["remaining"]) < floor_left:
        print("Browse の残り %s 回（下限 %d）なので、今回は判定しない" % (rem["remaining"], floor_left))
        write_run(NAME, True, 0, 0)
        return 0
    kinds = load_json(os.path.join(ROOT, "data", "判定", "種類.json"), {})
    st = load_json(os.path.join(ROOT, "data", "判定", "送料表.json"), {})
    qs = {"floorYen": 1500, "floorRate": 0.05, "tol": 0.30, "high": 100, "overMax": 1.4}
    qs.update(cfg.get("判定", {}).get("値付け", {}))
    me = cfg.get("店", {}).get("セラー名", "").lower()
    led = read_ledger()
    my_ids = {r.get("eBayの出品ID") for r in led}
    ledger_skus = {r["SKU"] for r in led}
    live_models = [m for m in (mkey(model_of(r.get("タイトル"))) for r in led if r.get("状態") == "出品中" and r.get("タイトル")) if m]
    done_p = os.path.join(ROOT, "data", "判定", "判定済み.json")
    done = {k: v for k, v in load_json(done_p, {}).items() if v.get("t", 0) >= now().timestamp() - 14 * 86400}
    back = load_json(os.path.join(ROOT, "data", "店の地引網", "送る待ち.json"), []) + \
        load_json(os.path.join(ROOT, "data", "店のサイトの地引網", "送る待ち.json"), []) + (gas_cands() if tt.get("GASにv667") else [])
    # 同じ型番は一番安い1品。判定済み・出品中の型番は飛ばす
    best = {}
    for c in sorted(back, key=lambda c: c["price"]):
        k = mkey(c["型番"])
        if c["id"] in done or k in best or len(k) < 4 or not re.search(r"\d", k):
            continue
        best[k] = c
    todo = list(best.values())[: int(tt.get("1回に判定する上限_件", 40))]
    n_list = int(tt.get("1回の出品の上限_件", 20))
    if live and not tt.get("カナリア済み"):
        n_list = min(n_list, int(tt.get("カナリアの件数", 5)))
    loc = location_key(eb, cfg) if live else ""
    res, listed, rows, gas_items, errs = [], [], [], [], []
    for c in todo:
        k = mkey(c["型番"])
        r = {"id": c["id"], "url": c["url"], "型番": c["型番"], "仕入値": c["price"], "仕入元の商品名": c["title"][:80]}
        dup = next((m for m in live_models if same_model(k, m)), None)
        if dup:
            r.update(結論="見送り", 理由="同じ型番がもう出品中（%s）" % dup)
        elif judge.RULE_OUT.search(judge.plain(c["title"])) or judge.RULE_OUT.search(c["型番"]):
            r.update(結論="見送り", 理由="キャラクター・ゲーム・限定品（決めごとA）")
        elif ip_bad(c["title"]):
            r.update(結論="見送り", 理由="規約のリスクの言葉（%s）" % ip_bad(c["title"]))
        elif judge.is_acc_ja(c["title"], c["型番"]):
            r.update(結論="見送り", 理由="付属品・部品（本体ではない）")
        elif kind_of(c["url"], cfg) not in ("A", "B", "C"):
            r.update(結論="GASへ", 理由="在庫の監視が見られない仕入元")
        else:
            cond = judge.cond_of(c["title"])
            if cond is None:   # 11/18 オーナー「GitHubで」：読めない品は中古として出す（実物より悪く書く側にそろえる）
                cond = 3000
            if True:
                cats = []
                try:
                    act = judge.comps(eb, c["型番"], cond, me, my_ids, cats)
                except EbayError as e:
                    if e.status == 429:
                        browse_stop(rem.get("reset") or "")
                        r.update(結論="エラー", 理由="検索の回数上限（429）")
                        res.append(r)
                        break
                    r.update(結論="エラー", 理由=err_text(e)[:300])
                    res.append(r)
                    continue
                cc = collections.Counter(cats).most_common(1)
                cat = cc[0][0] if cc and cc[0][1] * 2 >= len(cats) else ""
                kind = kinds.get(cat) or auto_kind(cat, kinds)
                r.update(競合の数=len(act), 競合=act[:5], カテゴリ=cat)
                if len(act) < 2:
                    r.update(結論="GASへ", 理由="同じ型番の競合が2件未満")
                elif c["price"] < 0.2 * act[0] * 152:
                    r.update(結論="見送り", 理由="仕入値がeBayの最安の2割未満（付属品・別物の疑い）")
                elif not kind:
                    r.update(結論="GASへ", 理由="決めてある種類のカテゴリではない（%s）" % (cat or "多数決できない"))
                else:
                    ship = judge.ship_fedex(kind["重さ_g"], kind["箱"], st["FedEx"])
                    d = {"cost": c["price"], "dom": c.get("dom", 2000), "ship": ship, "fee": kind.get("手数料率", 0.1742),
                         "duty": kind.get("関税率", 0.15), "fixed": 0, "fx": 152}
                    price, how, fp = judge.quote(act, d, qs)
                    r.update(種類=kind["名前"], 送料=ship, 国内送料=d["dom"], フロア=fp, 値段の決め方=how)
                    if price is None:
                        r.update(結論="見送り", 理由=how)
                    else:
                        py, pr = judge.profit(price, d)
                        r.update(値段=price, 利益=py, 利益率=round(pr, 4))
                        if py < qs["floorYen"] or pr < qs["floorRate"] - 1e-9:
                            r.update(結論="見送り", 理由="利益の条件を満たさない")
                        elif len(c.setdefault("_photos", more_photos(c))) < int(tt.get("写真の最低枚数", 3)):
                            r.update(結論="GASへ", 理由="写真が%d枚未満（GASが商品ページから集める）" % int(tt.get("写真の最低枚数", 3)))
                        else:
                            r.update(結論="GO")
                            live_models.append(k)
                            if live and len(listed) < n_list and not listing_limit_stopped():
                                sku = next_sku(c, 0)
                                pl = make_payload(c, kind, cat, cond, price, fp, ship, sku)
                                item, offer, why = build(pl, loc)
                                if not item:
                                    r.update(結論="エラー", 理由="出品データが足りない：" + why)
                                else:
                                    try:
                                        lid, oid = list_one(eb, pl, item, offer)
                                        r.update(出品="eBay %s" % lid, SKU=sku)
                                        listed.append((sku, lid, pl["title"], price))
                                        gas_items.append({"itemId": lid, "offerId": oid, "sku": sku, "title": pl["title"], "price": price,
                                                          "cost": c["price"], "src": c["url"]})
                                        if sku not in ledger_skus:
                                            rows.append({"SKU": sku, "eBayの出品ID": lid, "offerId": oid, "仕入元URL": c["url"],
                                                         "仕入元の種類": kind_of(c["url"], cfg), "仕入値(円)": c["price"], "出品時の海外送料(円)": ship,
                                                         "売値(ドル)": "%.2f" % price, "状態": "出品中", "出品日": now().strftime("%Y-%m-%d"),
                                                         "タイトル": pl["title"], "eBayの状態ID": cond, "手数料率": d["fee"], "関税率": d["duty"],
                                                         "固定費(円)": 0, "国内送料(円)": d["dom"], "為替": 152, "移した日時": "",
                                                         "最後に値段を変えた日時": "", "メモ": "GitHubの判定と出品（%s・%s）" % (kind["名前"], how)})
                                    except (EbayError, RuntimeError, KeyError) as e:
                                        et = err_text(e)
                                        r.update(結論="エラー", 理由=et[:500], SKU=sku)
                                        errs.append((sku, et))
                                        if is_limit_error(et):   # 月の上限：この回はもう出さない・次の月まで止める
                                            listing_limit_stop(et)
                                            n_list = 0
        r["t"] = now().timestamp()
        res.append(r)
        if live and r["結論"] in ("GO", "見送り") and (r["結論"] == "見送り" or r.get("出品")):   # 影の運転の間は記録しない（GAS に今までどおり送る）
            done[c["id"]] = {"t": r["t"], "結論": r["結論"]}
        time.sleep(0.5)
    if rows:
        save_ledger(rows, list(rows[0].keys()), NAME)
    # 店のサイトの地引網の品で「GASへ」になったものは、ここから GAS に送る（店の地引網の品は、店の地引網が送る）
    to_gas = [c for c in todo if c.get("src") not in ("楽天", "Yahoo!") and any(r.get("id") == c["id"] and r["結論"] == "GASへ" for r in res)]
    if live and to_gas:
        try:
            from flea_sweep import gas_post
            for src in sorted({c["src"] for c in to_gas}):
                part = [c for c in to_gas if c["src"] == src]
                for i in range(0, len(part), 15):
                    gas_post({"kind": "search", "perItem": True, "noAi": True, "keyword": "", "url": part[0]["url"].split("/")[0] + "//" + part[0]["url"].split("/")[2] + "/",
                              "site": src + "（GitHubの地引網）", "items": [{"url": c["url"], "title": c["title"][:200], "price": c["price"], "sold": False,
                                                                       "thumb": "\n".join(c.get("photos") or []), "model": c["型番"], "maker": c["メーカー"]} for c in part[i:i + 15]]})
                    time.sleep(3)
            for c in to_gas:
                done[c["id"]] = {"t": now().timestamp(), "結論": "GASへ送った"}
        except Exception as e:
            print("GASへ送れなかった：", str(e)[:200])
    gas_note = ""
    if gas_items and tt.get("GASにv664"):
        try:
            from flea_sweep import gas_post
            gas_note = gas_post({"kind": "ghnew", "items": gas_items})[:200]
        except Exception as e:
            gas_note = "GASへの知らせに失敗：" + str(e)[:200]
    save_json(done_p, done)
    save_json(os.path.join(ROOT, "data", "判定", "記録", now().strftime("%Y%m%d_%H%M%S") + ".json"),
              {"時刻": jst(), "本番": live, "Browseの残り": rem.get("remaining"), "結果": res})
    cnt = collections.Counter(x["結論"] for x in res)
    msg = ["【判定と出品】%s %s：%d品を判定（GitHubだけ）" % (jst(), "本番" if live else "影の運転", len(res)),
           "・".join("%s %d" % kv for kv in cnt.most_common())]
    why = collections.Counter(x.get("理由", "") for x in res if x["結論"] in ("見送り", "GASへ"))
    if why:
        msg.append("理由：" + "・".join("%s %d" % (k[:30], v) for k, v in why.most_common(5)))
    if listed:
        msg.append("出品した %d品：" % len(listed) + "・".join("%s $%.2f" % (t[:40], p) for _, _, t, p in listed[:10]))
        if not tt.get("カナリア済み"):
            msg.append("カナリア：公開ページを目で見てから カナリア済み を true に")
    if errs:
        msg.append("エラー：" + " / ".join("%s %s" % (s, e[:120]) for s, e in errs[:5]))
    if wd_note:
        msg.append(wd_note)
    if live and tt.get("広告率", 2.0):
        ad = promote_new(eb, float(tt.get("広告率", 2.0)))
        if ad:
            msg.append(ad)
    if gas_note.startswith("GASへの知らせに失敗"):
        msg.append(gas_note)
    if gas_items and not tt.get("GASにv664"):
        msg.append("GASの出品一覧にはまだ載せていない（v664を貼ったら GASにv664 を true に）")
    print("\n".join(msg))
    notify("\n".join(msg))
    write_run(NAME, not errs, len(listed), len(errs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
