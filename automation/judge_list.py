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
import collections, json, os, re, statistics, sys, time, urllib.parse
import title_make
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (hand_only, ROOT, Ebay, EbayError, err_text, now, jst, settings, timetable, notify, read_ledger, save_ledger, write_run,
                    mark_started, load_json, save_json, browse_stopped, browse_stop, listing_limit_stopped, listing_limit_stop, listing_limit_left, listing_limit_spend,
                    is_limit_error)
from price_adjust import model_of
import judge
from bulk_list import build, list_one, location_key, mkey, same_model
from stock_watch import kind_of
from shop_sweep import bad_shop

NAME = "判定と出品"
HERE = os.path.dirname(os.path.abspath(__file__))
BRAND_JA = {"カシオ": "Casio", "ソニー": "Sony", "シチズン": "Citizen", "セイコー": "Seiko", "キヤノン": "Canon", "キャノン": "Canon",
            "ニコン": "Nikon", "オリンパス": "Olympus", "ペンタックス": "Pentax", "パナソニック": "Panasonic", "富士フイルム": "Fujifilm",
            "フジフイルム": "Fujifilm", "リコー": "Ricoh", "ボス": "BOSS", "ローランド": "Roland", "ヤマハ": "Yamaha", "シマノ": "Shimano",
            "ダイワ": "Daiwa", "タムロン": "Tamron", "シグマ": "Sigma", "オーディオテクニカ": "Audio-Technica", "デノン": "Denon"}
KEEP_CAPS = {"BOSS", "MXR", "TEAC", "AKAI", "JVC", "TDK", "SMC", "EHX"}
NO_GAS = ("ラクマ", "Amazon")   # 11/24 09:45 オーナー「絶対Amazon，楽天ラクマ全ての工程GAS使わないで！」
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
    return out[:24]


BAD_CAT = re.compile(r"part|accessor|case|bag|strap|cable|charger|battery|book|manual|video game|game|toy|figure|doll|card|"
                     r"amplifier|speaker|furniture|guitar$|bass$|drum|keyboard|piano|tripod|stand|autres|sonstiges|animation|automation|bicycle|cycling", re.I)


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
        raw = (gas_get_models() or {"models": []})["models"]
        ms = compile_models(raw)
        # 11/21 19:04 オーナー「教科書の人はこれを自動化してる！私のショップもやって！規約は承知済み」：
        # メルカリの品は、型番リストに無くても、メーカー名と型番らしい文字が読めれば判定する（フリマのリスト外と同じ guess_model）
        import flea_sweep as _fs
        _fs.MAKERS |= {str(x.get("maker", "")).upper() for x in raw if x.get("maker")}
        kana = {"ニコン": "NIKON", "キヤノン": "CANON", "キャノン": "CANON", "オリンパス": "OLYMPUS", "ソニー": "SONY", "カシオ": "CASIO",
                "セイコー": "SEIKO", "シチズン": "CITIZEN", "ボス": "BOSS", "ローランド": "ROLAND", "コルグ": "KORG", "ヤマハ": "YAMAHA",
                "パナソニック": "PANASONIC", "ペンタックス": "PENTAX", "富士フイルム": "FUJIFILM", "フジフイルム": "FUJIFILM", "リコー": "RICOH",
                "ミノルタ": "MINOLTA", "タムロン": "TAMRON", "シグマ": "SIGMA", "オーディオテクニカ": "AUDIO-TECHNICA", "マミヤ": "MAMIYA",
                "コンタックス": "CONTAX", "ライカ": "LEICA", "オメガ": "OMEGA", "テクニクス": "TECHNICS", "ケンウッド": "KENWOOD", "パイオニア": "PIONEER"}
        out = []
        for it in d.get("items", []):
            hit = match(it["title"], ms)
            if not hit and "mercari.com" in str(it.get("url", "")) and it.get("price"):
                t2 = " ".join([v for k, v in kana.items() if k in it["title"]] + [it["title"], str(it.get("desc", ""))[:300]])
                g = _fs.guess_model(t2)
                if g:
                    hit = {"maker": g[0], "model": g[1]}
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


SELLER_RX = re.compile(r"images\.auctions\.yahoo\.co\.jp/image/[^/]+/[^/]+/users?/([0-9a-f]{32,64})/")


def same_seller(ph, html, c):
    """Yahoo!フリマ・ヤフオクの写真を、この品の出品者の写真だけにする（ほかの出品者の写真は外す）"""
    if not any(SELLER_RX.search(u) for u in ph):
        return ph
    main = None
    # この品の出品者は、商品ページの og:image（この品の1枚目）で決める。検索の一覧から来た写真（photos_of）は、ほかの品の写真のことがあるので後回し
    for u in re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html or "") + \
            re.findall(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"', html or "") + photos_of(c):
        m = SELLER_RX.search(u)
        if m:
            main = m.group(1)
            break
    if not main:
        return ph[:1]   # 出品者が分からないときは1枚目だけ（混ぜない）
    return [u for u in ph if (SELLER_RX.search(u) or [None, None])[1] == main]


def more_photos(c):
    """Yahoo!ショッピングは、APIの写真が1枚だけ。商品ページ（GitHub から読める）から同じ商品の写真（_1, _2 …）を集める。楽天のページは読めない"""
    ph = photos_of(c)
    # 11/22 7:52 オーナー「仕入れ先の写真はすべて取得して」：3枚あっても止めずに、商品ページの写真を全部集める（eBay の上限24枚まで）
    if "store.shopping.yahoo.co.jp" not in c.get("url", ""):   # ほかの店・フリマ・ヤフオク：商品ページの JSON-LD とヤフオクの画像から集める（メルカリは見ない）
        if hand_only(c.get("url")):
            return ph
        if "item.rakuten.co.jp" in c.get("url", ""):
            # 11/21 18:47 オーナー「1 → 2 → 3」：楽天は公式API（itemCode）の写真（mediumImageUrls・最大3枚）を、元の大きさ（?_ex= を外す）で使う。ページは開かない
            try:
                from stock_watch import rakuten_item
                it = rakuten_item(c["url"], c.get("title") or c.get("name") or "")
                for u in (it or {}).get("mediumImageUrls") or []:
                    u = (u.get("imageUrl") if isinstance(u, dict) else u) or ""
                    u = u.split("?")[0]
                    if u.startswith("https://") and u not in ph:
                        ph.append(u)
            except Exception:
                pass
            return ph
        try:
            from stock_watch import fetch
            from store_sweep import ld_product
            from flea_sweep import IMG_RX
            code, html = fetch(c["url"])
            if code == 200:
                # 11/20 9:41 オーナー「A→Bでお願い」：Yahoo!フリマ・ヤフオクの写真は、画像の中継（auc-pctr など）や JSON の中（\u002F）にあって
                # 今までの読み方では拾えなかった。中継の後ろの元の写真のアドレスも拾う
                html = html.replace("\\u002F", "/").replace("\\/", "/")
                # 11/22：ほかの品（おすすめ・この出品者のほかの品）の写真を拾わないように、ページの中で
                # 「ほかの品へのリンク」が最初に出てくる所より前だけを見る（この品の写真はページの上の方にまとまっている）
                if re.search(r"paypayfleamarket|auctions\.yahoo", c.get("url", "")):
                    own = (re.search(r"/(?:item|auction)/([a-z]?\d{6,})", c.get("url", "")) or [None, ""])[1]
                    for mm in re.finditer(r"(?:/item/|/jp/auction/)([a-z]?\d{6,})", html):
                        if mm.group(1) != own and mm.start() > 3000:
                            html = html[:mm.start()]
                            break
                for m in re.findall(r"(?:https?:)?//?(?:[a-z0-9\-]+\.c\.yimg\.jp/(?:i/)?)?(auctions\.c\.yimg\.jp/images\.auctions\.yahoo\.co\.jp/image/[^\"'?\s<>]+?\.(?:jpe?g|png))", html, re.I):
                    u = "https://" + m
                    if u not in ph:
                        ph.append(u)
                for u in re.findall(r"https://[a-z0-9\-\.]*paypayfleamarket[a-z0-9\-\.]*\.(?:yimg\.jp|yahoo\.co\.jp)/[^\"'\s<>]+?\.(?:jpe?g|png|webp)", html, re.I):
                    if not re.search(r"icon|logo|banner|avatar|profile|noimage|blank", u, re.I) and u not in ph:
                        ph.append(u)
                p = ld_product(html) or {}
                ho = [u for u in re.findall(r"https://[a-z0-9\-]+\.imageflux\.jp/[^\"'\s)]+\.(?:jpe?g|png|webp)[^\"'\s)]*", html)
                      if not re.search(r"blankimg|noimage|icon|logo|banner|/portal/", u) and int((re.search(r"w=(\d+)", u) or [0, 9999])[1]) >= 600]
                for u in (p.get("photos") or []) + IMG_RX.findall(html) + ho:
                    if u.startswith("https://") and u not in ph:
                        ph.append(u)
                # 11/22 オーナー「写真はすべて」で見つけた間違い：Yahoo!フリマ・ヤフオクのページには、ほかの出品者の品（おすすめ）の写真も入っている。
                # 写真のアドレスの users/<出品者の印> が、この品の1枚目（og:image）と同じ写真だけを残す
                ph = same_seller(ph, html, c)
        except Exception:
            pass
        return ph[:24]
    try:
        from stock_watch import fetch
        code, html = fetch(c["url"])
        if code != 200:
            return ph
        m = re.search(r"/i/[a-z]/([A-Za-z0-9\-]+_[A-Za-z0-9\-]+)", ph[0]) if ph else None
        base = m.group(1) if m else ""
        if not base:   # 写真がまだ無いとき：URL の 店/商品コード.html から（ほかの商品の写真を拾わない）
            mm = re.search(r"store\.shopping\.yahoo\.co\.jp/([^/]+)/([^/.?]+)\.html", c.get("url", ""))
            base = "%s_%s" % (mm.group(1), mm.group(2)) if mm else None
        if base is None:
            return ph
        for u in re.findall(r"https://item-shopping\.c\.yimg\.jp/i/[a-z]/([A-Za-z0-9_\-]+)", html):
            if not (u == base or u.startswith(base + "_")):
                continue
            uu = "https://item-shopping.c.yimg.jp/i/n/" + u
            if uu not in ph:
                ph.append(uu)
        return ph[:24]
    except Exception:
        return ph


tt_title = {}


def make_payload(c, kind, cat, cond, price, fp, ship, sku):
    brand, model = brand_of(c["メーカー"]), c["型番"]
    cw = "New" if cond < 3000 else "Used"
    title = re.sub(r"\s+", " ", "%s %s %s %s From Japan" % (brand, model, kind["言葉"], cw)).strip()[:80]
    html = open(os.path.join(HERE, "desc_template.html"), encoding="utf-8").read()
    # 11/21 13:07 オーナー「1と3」：仕入れ先の状態の説明を読んで英語の「Condition notes」にし、eBay の状態の説明の欄にも入れる
    try:
        import cond_note
        _src = cond_note.source_text(c)
        cn = cond_note.notes(_src, c.get("title", ""))
        cn["_src"] = _src
    except Exception:
        cn = {"notes": [], "func": "", "box": ""}
    # 11/23 19:26 オーナー「OK」：タイトルを教科書の形に（ブランド＋型番＋種類＋状態＋付属品＋From Japan・80文字まで）・型番を仕入れ先と照合
    if tt_title.get("教科書のタイトル"):
        import title_make
        if not title_make.check_model(model, c.get("title", ""), cn.get("_src", "")):
            raise RuntimeError("型番が仕入れ先の商品名・説明と合わない（%s）" % model)
        # 11/23 20:40：状態と付属品は仕入れ先の「商品名」だけから（店のページの説明にはランクの一覧表や「ジャンク」の案内があり、まちがえる）
        nm = c.get("title", "")
        title = title_make.build(brand, model, kind["言葉"], cond, cond_note.notes("", nm), nm)
    func = "New item." if cond < 3000 else (cn["func"] or "Not tested. Please check the photos.")
    nts = [] if cond < 3000 else cn["notes"]
    def esc(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (html.replace("{{TITLE}}", title).replace("{{BRAND}}", brand).replace("{{MODEL}}", model)
            .replace("{{COND}}", "New" if cond < 3000 else "Used")
            .replace("{{FUNC}}", esc(func))
            .replace("{{NOTES}}", esc("; ".join(nts)) if nts else "Please check the photos.")
            .replace("{{INCLUDED}}", esc(cn["box"]) if cn.get("box") else "Only the items in the photos"))
    vals = kind.get("項目の値") or {}
    def aval(k):
        v = vals.get(k, "Does not apply")
        if v == "{型番}":
            return model
        if v == "{接続}":   # 11/23：ヘッドホンの Connectivity（必ず入れる項目）
            return "Wireless" if re.search(r"TW|BT|Bluetooth|Wireless|ワイヤレス", "%s %s" % (model, c.get("title", "")), re.I) else "Wired"
        if v == "{色}":   # 11/23：ヘッドホンの Color（必ず入れる項目）。商品名に色が1つだけのときだけ
            from title_make import colors_in
            cs = colors_in(c.get("title", ""))
            if len(cs) != 1:
                raise RuntimeError("色が商品名から分からない（ヘッドホンは色が必ず要る）")
            return cs.pop()
        return v
    asp = [["Brand", brand], ["Model", model]] + [[k, aval(k)] for k in kind["項目"]] + \
          [["Shipping Method", "FedEx International Connect Plus (tracked)"]]
    w, (l, wd, h) = kind["重さ_g"], sorted([float(x) for x in kind["箱"].split("x")], reverse=True)
    pol = dict(kind.get("ポリシー") or {})
    if re.search(r"netmall\.hardoff\.co\.jp|ec\.treasure-f\.com", c.get("url", "")):   # 発送まで日数がかかる店：発送10営業日（11/18 21:46 オーナー）
        p10 = load_json(os.path.join(ROOT, "data", "判定", "発送10日のポリシー.json"), {}).get("id")
        if not p10:
            raise RuntimeError("発送10日のポリシーがまだ無い（policy_10d.py）")
        pol["発送"] = p10
        html = html.replace("3 business days", "10 business days")
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
        cd = "Used. " + (" ".join(x.rstrip(".") + "." for x in nts) + " " if nts else "") + \
             (cn["func"] if cn["func"] else "NOT TESTED - we have not tested this item and its function is not confirmed.") + \
             (" Included: %s." % cn["box"] if cn.get("box") else "") + " Please judge from the photos."
        pl["conditionDescription"] = cd[:1000]
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
    code = {"楽天": "RK", "Yahoo!": "YS", "イシバシ楽器": "IS", "カメラの八百富": "YT", "フジヤカメラ": "FJ", "トレファク": "TF", "ハードオフ": "HO", "メルカリ（人）": "MR", "Amazon（人）": "AZ", "Yahoo!フリマ": "YF", "ヤフオク": "YA", "ラクマ": "RM", "Amazon": "AZ"}.get(c["src"], "ST")
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
    tt_title.update(tt)
    t_bright_end = time.time() + 60 * float(tt.get("写真を明るくする時間_分", 12))   # 30分で切られないよう、補正は始めてから12分まで
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
    left = listing_limit_left()
    cap_usd = float(tt.get("今出す売値の上限_ドル", 0) or 0)   # 今は出さない（後回し）線。11/20 7:46 オーナー「今は高額商品出品控えて」（0 なら上限なし）
    never_usd = float(tt.get("出さない売値の上限_ドル", 0) or 0)   # これを超える品は出さない（見送り）。11/20 7:44 オーナー「今後は1000以上の商品出品しないで」
    min_usd = float(tt.get("上限の残りで出す最低の売値_ドル", 60))
    # 11/21 18:47 オーナー「1 → 2 → 3」：今月の残りの枠が少ないときは、安めの品（$200 まで）を先に出す（同じ枠で多く出して実績を積む）
    if left is not None and left < float(tt.get("安めを先に出す残り_ドル", 3000)):
        cheap = float(tt.get("枠が少ないときの売値の上限_ドル", 200))
        if not cap_usd or cap_usd > cheap:
            cap_usd = cheap
            print("今月の残り $%.0f：$%.0f を超える品は後回し（安めを先に出す）" % (left, cheap))
    if ls and live and left is not None and left >= min_usd:
        print("eBay の出品の上限：今月の残り $%.2f に収まる品だけ出す（11/19 14:08 オーナー「出品枠額がなくなるまで出品して」）" % left)
        ls = None
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
    new_cat = load_json(os.path.join(ROOT, "data", "判定", "新しいカテゴリの出品.json"), {})
    cpd = load_json(os.path.join(ROOT, "data", "判定", "コストプラスの数.json"), {})
    cp_today = int(cpd.get(now().strftime("%Y-%m-%d"), 0))
    cp_cfg = (settings().get("値付けの式_第5章") or {})
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
        load_json(os.path.join(ROOT, "data", "店のサイトの地引網", "送る待ち.json"), []) + (gas_cands() if tt.get("GASにv667") else []) + \
        load_json(os.path.join(ROOT, "data", "人の候補", "送る待ち.json"), []) + \
        load_json(os.path.join(ROOT, "data", "フリマ新着", "リスト外の候補.json"), []) + \
        load_json(os.path.join(ROOT, "data", "ラクマ", "送る待ち.json"), []) + \
        load_json(os.path.join(ROOT, "data", "Amazon", "送る待ち.json"), [])   # 11/24 09:34 オーナー「Amazonも定期タスクで探して」：パソコンの定期タスクが集めた品   # 11/19 10:32 オーナー「1と使い回し3日」：型番リストに無いフリマの品   # メルカリ：人が集めた候補（教科書 第18章。プログラムはメルカリを開かない）
    # メルカリ（メール・ブラウザで集めた品）は、オーナーがGOを出した品だけ出品する（11/18 21:45 オーナー「メルカリはこれをやって」）
    import glob as _glob
    mgo_p = os.path.join(ROOT, "data", "判定", "メルカリGO待ち.json")
    mgo = {k: v for k, v in load_json(mgo_p, {}).items() if v.get("t", 0) >= now().timestamp() - 7 * 86400}
    mauto_p = os.path.join(ROOT, "data", "判定", "メルカリの自動出品.json")
    mauto = load_json(mauto_p, {})
    # 11/21 21:34 オーナー「在庫管理もしっかりして！」：出品中のメルカリの品が、1日に見回れる数（時刻表 メルカリの見回り_1日）に届いたら、
    # メルカリの自動出品を止める（見回れない品を増やさない）。止めた品は今までどおり「GO確認待ち」。
    m_live = sum(1 for r in led if r.get("状態") == "出品中" and "mercari.com/item/" in str(r.get("仕入元URL", "")))
    m_cap = int(tt.get("メルカリの見回り_1日", 180))
    m_day_cap = min(int(tt.get("メルカリの自動出品_1日", 5)), mauto.get(now().strftime("%Y-%m-%d"), 0) + max(0, m_cap - m_live))   # 空きの分だけ
    if m_live >= m_cap:
        print("メルカリ：出品中 %d 品が見回りの上限 %d に届いたので、自動出品を止める" % (m_live, m_cap))
    approved, ans_files = set(), []
    for f in sorted(_glob.glob(os.path.join(ROOT, "data", "答え", "*.json"))):
        a = load_json(f, {})
        if a.get("種類") == "メルカリGO":
            approved |= {str(x) for x in (a.get("商品") or [])}
            ans_files.append(f)
    for k, v in mgo.items():
        # 11/21 19:04 オーナー「…私のショップもやって」：GO確認待ちのうち、集めてから24時間以内の品も自動で出す（1日の上限の中）
        recent = v.get("t", 0) >= now().timestamp() - 86400 and mauto.get(now().strftime("%Y-%m-%d"), 0) < m_day_cap
        if v.get("商品") in approved or recent:
            if recent and v.get("商品") not in approved:
                mauto[now().strftime("%Y-%m-%d")] = mauto.get(now().strftime("%Y-%m-%d"), 0) + 1
            back.append(dict(v["候補"], _approved=True))
    # 同じ型番は一番安い1品。判定済み・出品中の型番は飛ばす
    best, pre = {}, collections.Counter()
    for c in sorted(back, key=lambda c: (not c.get("_approved"), c["price"])):
        k = mkey(c["型番"])
        if (c["id"] in done and not c.get("_approved")) or k in best or len(k) < 4 or not re.search(r"\d", k):
            continue
        # 11/19 9:11 オーナー「やって」：付属品・出品中の型番は、判定の枠（1回の上限）を使わずに先に外す（検索も使わない）
        if not c.get("_approved"):
            why = ""
            if judge.is_acc_ja(c["title"], c["型番"]):
                why = "付属品・部品（本体ではない）"
            elif any(same_model(k, m) for m in live_models):
                why = "同じ型番がもう出品中"
            if why:
                done[c["id"]] = {"t": now().timestamp(), "結論": "見送り", "理由": why + "（先に外した）"}
                pre[why] += 1
                continue
        best[k] = c
    judge.comp_cache_load(os.path.join(ROOT, "data", "判定", "相場の写し.json"), tt.get("相場の使い回し_時間", 6), tt.get("相場の使い回し_競合なし_時間"))   # 11/19 10:32 オーナー「使い回し3日」   # 11/19 8:52 オーナー「おすすめは1から」
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
        elif bad_shop(c["url"]):
            r.update(結論="見送り", 理由="店の規約で使わない店（転売の購入を断る・転載の禁止）")
        elif judge.RULE_OUT.search(judge.plain(c["title"])) or judge.RULE_OUT.search(c["型番"]):
            r.update(結論="見送り", 理由="キャラクター・ゲーム・限定品（決めごとA）")
        elif ip_bad(c["title"]):
            r.update(結論="見送り", 理由="規約のリスクの言葉（%s）" % ip_bad(c["title"]))
        elif judge.is_acc_ja(c["title"], c["型番"]):
            r.update(結論="見送り", 理由="付属品・部品（本体ではない）")
        elif kind_of(c["url"], cfg) not in ("A", "B", "C") and c.get("src") not in NO_GAS:   # ラクマ＝GitHub のブラウザ、Amazon＝パソコンの定期タスクが在庫を見る（11/24 15:05）
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
                # 11/24 19:23 オーナー「おすすめは 2でお願いします」：競合が無い品は、教科書 第5章のコストプラスで出す。
                # ただし型番が商品名にそのまま入っていて、ブランド名も商品名にある品だけ。1日の上限 時刻表 判定と出品 → コストプラス_1日。
                cp = False
                if len(act) < int(tt.get("競合の最低件数", 1)) and cp_today < int(tt.get("コストプラス_1日", 5)):
                    mk = (c.get("メーカー") or "").strip()
                    if title_make.check_model(c.get("型番", ""), c.get("title", ""), "") and mk and mk.lower() in c.get("title", "").lower():
                        try:
                            _, sg = eb.call("GET", "/commerce/taxonomy/v1/category_tree/0/get_category_suggestions?q=" + urllib.parse.quote("%s %s" % (c.get("brand_en") or mk, c.get("型番", ""))))
                            sugg = [x["category"]["categoryId"] for x in (sg or {}).get("categorySuggestions") or []]
                        except EbayError:
                            sugg = []
                        cat = next((x for x in sugg if x in kinds), "")
                        cp = bool(cat)
                # 11/23 19:07 オーナー「1〜3やって」：①まちがったカテゴリの直し（ビデオカメラがアニメのグッズに出る など）③店に合わないカテゴリは見送り
                skip_cat = False
                fx = (tt.get("カテゴリの直し") or {}).get(cat)
                if fx:
                    if re.search(fx["型番の形"], "%s %s" % (c.get("型番", ""), c.get("name", "")), re.I):
                        cat = fx["先"]
                    else:
                        skip_cat = True
                if cat in set(tt.get("見送りのカテゴリ") or []):
                    skip_cat = True
                kind = None if skip_cat else (kinds.get(cat) or auto_kind(cat, kinds))
                r.update(競合の数=len(act), 競合=act[:5], カテゴリ=cat)
                if len(act) < int(tt.get("競合の最低件数", 1)) and not cp:   # 11/20 9:41 オーナー「A→Bでお願い」：競合1件でも、その値段とフロアで値付けする（前は2件未満を GAS へ）
                    r.update(結論="見送り", 理由="eBayに同じ型番の競合が無い（相場と比べられない）")
                elif not cp and c["price"] > float(qs.get("相場の中央値に対する仕入値の上限", 0.6)) * statistics.median(act) * 152:
                    r.update(結論="見送り", 理由="仕入値が相場の中央値の%d割を超える（教科書 第21章）" % round(float(qs.get("相場の中央値に対する仕入値の上限", 0.6)) * 10))
                elif not cp and c["price"] < 0.2 * act[0] * 152:
                    r.update(結論="見送り", 理由="仕入値がeBayの最安の2割未満（付属品・別物の疑い）")
                elif skip_cat:
                    r.update(結論="見送り", 理由="店に合わないカテゴリ（%s %s）" % (cat, judge.CAT_NAMES.get(cat, "")))
                elif not kind:
                    r.update(結論="GASへ", 理由="決めてある種類のカテゴリではない（%s）" % (cat or "多数決できない"))
                elif kind.get("新しい") and new_cat.get(cat, 0) >= int(tt.get("新しいカテゴリのカナリア_件", 2)):
                    r.update(結論="GO（後回し）", 理由="新しいカテゴリのカナリア（%s）はオーナーが見てから" % kind["名前"])
                else:
                    ship = judge.ship_fedex(kind["重さ_g"], kind["箱"], st["FedEx"])
                    d = {"cost": c["price"], "dom": c.get("dom", 2000), "ship": ship, "fee": kind.get("手数料率", 0.1742),
                         "duty": kind.get("関税率", 0.15), "fixed": 0, "fx": 152}
                    price, how, fp = judge.cost_plus(d, qs, cp_cfg) if cp else judge.quote(act, d, qs)
                    if cp and price is not None:
                        cp_today += 1
                        cpd[now().strftime("%Y-%m-%d")] = cp_today
                        save_json(os.path.join(ROOT, "data", "判定", "コストプラスの数.json"), cpd)
                    r.update(種類=kind["名前"], 送料=ship, 国内送料=d["dom"], フロア=fp, 値段の決め方=how)
                    if price is None:
                        r.update(結論="見送り", 理由=how)
                    else:
                        py, pr = judge.profit(price, d)
                        r.update(値段=price, 利益=py, 利益率=round(pr, 4))
                        if py < qs["floorYen"] or pr < qs["floorRate"] - 1e-9:
                            r.update(結論="見送り", 理由="利益の条件を満たさない")
                        elif c.get("写真ファイル") and len(c["写真ファイル"]) < int(tt.get("写真の最低枚数", 3)):
                            r.update(結論="人に返す", 理由="送られた写真が%d枚未満" % int(tt.get("写真の最低枚数", 3)))
                        elif not c.get("写真ファイル") and len(c.setdefault("_photos", more_photos(c))) < int(tt.get("写真の最低枚数", 3)):
                            r.update(結論="GASへ", 理由="写真が%d枚未満（GASが商品ページから集める）" % int(tt.get("写真の最低枚数", 3)))
                        else:
                            r.update(結論="GO")
                            live_models.append(k)
                            if kind.get("新しい"):
                                new_cat[cat] = new_cat.get(cat, 0) + 1
                                save_json(os.path.join(ROOT, "data", "判定", "新しいカテゴリの出品.json"), new_cat)
                            mid = (re.search(r"mercari\.com/item/(m\d+)", c["url"]) or [None, ""])[1]
                            # 11/21 19:04 オーナー「…私のショップもやって！規約は承知済み」：メルカリも自動で出す（1日の上限 時刻表 メルカリの自動出品_1日）。
                            # 上限を超えた品だけ、今までどおり「GO確認待ち」
                            mday = now().strftime("%Y-%m-%d")
                            if mid and not str(c["id"]).startswith("人:") and not c.get("_approved") and \
                                    mauto.get(mday, 0) < m_day_cap:
                                c["_approved"] = True
                                mauto[mday] = mauto.get(mday, 0) + 1
                            if mid and not str(c["id"]).startswith("人:") and not c.get("_approved"):
                                r.update(結論="GO確認待ち", 理由="メルカリはオーナーのGOで出品")
                                mgo[c["id"]] = {"t": now().timestamp(), "商品": mid, "型番": c["型番"], "仕入値": c["price"], "値段": price, "利益": py, "url": c["url"],
                                                "候補": {kk: vv for kk, vv in c.items() if not kk.startswith("_")}}
                            if live and len(listed) < n_list and (not listing_limit_stopped() or (listing_limit_left() or 0) >= min_usd) and c.get("写真ファイル") and not c.get("_photos"):
                                try:
                                    c["_photos"] = [eb.upload_image(os.path.join(ROOT, f)) for f in c["写真ファイル"][:24]]
                                except Exception as e:
                                    r.update(結論="エラー", 理由="写真を eBay に上げられない：" + err_text(e)[:300] if isinstance(e, EbayError) else str(e)[:300])
                            if r["結論"] == "GO" and live and never_usd and price > never_usd:
                                r.update(結論="見送り", 理由="売値 $%.2f が出す上限 $%.0f を超える（11/20 7:44 オーナー「今後は1000以上の商品出品しないで」）" % (price, never_usd))
                            if r["結論"] == "GO" and live and (cap_usd and price > cap_usd or (listing_limit_left() is not None and price > listing_limit_left())):
                                r.update(結論="GO（後回し）", 理由="今は出さない：%s" % ("高額（$%.0f 超え・11/20 7:46 オーナー「今は高額商品出品控えて」）" % cap_usd if cap_usd and price > cap_usd else "今月の出品の上限の残り $%.2f を超える" % listing_limit_left()))
                            if r["結論"] == "GO" and live and len(listed) < n_list and (not listing_limit_stopped() or (listing_limit_left() or 0) >= price):
                                sku = next_sku(c, 0)
                                # 11/22 11:13 オーナー「教科書に合わせて」：出品前に全部の写真の明るさを補正して eBay に上げる（失敗したら元の写真のまま）
                                if tt.get("写真を明るく") and time.time() < t_bright_end:
                                    try:
                                        import photo_bright
                                        b = photo_bright.brighten_all(c.get("_photos") or photos_of(c), eb, sku, tt.get("写真の補正") or {})
                                        if b:
                                            c["_photos"] = b
                                    except Exception:
                                        pass
                                try:
                                    pl = make_payload(c, kind, cat, cond, price, fp, ship, sku)
                                    item, offer, why = build(pl, loc)
                                except RuntimeError as e:
                                    item, why = None, str(e)
                                if not item:
                                    r.update(結論="エラー", 理由="出品データが足りない：" + why)
                                else:
                                    try:
                                        lid, oid = list_one(eb, pl, item, offer)
                                        r.update(出品="eBay %s" % lid, SKU=sku)
                                        listed.append((sku, lid, pl["title"], price))
                                        if listing_limit_left() is not None:
                                            listing_limit_spend(price)
                                        if c.get("src") not in NO_GAS:   # 11/24 09:45 オーナー「絶対Amazon，楽天ラクマ全ての工程GAS使わないで」
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
                                        if is_limit_error(et):   # 月の上限：残りの金額を記録。残りが最低の売値より少なければ、この回はもう出さない
                                            listing_limit_stop(et)
                                            r["結論"] = "GO（後回し）"
                                            if (listing_limit_left() or 0) < min_usd:
                                                n_list = 0
        r["t"] = now().timestamp()
        res.append(r)
        if str(c.get("id", "")).startswith("人:") and r["結論"] == "GASへ":
            r["結論"] = "人に返す"
        if live and r["結論"] == "GO確認待ち":
            done[c["id"]] = {"t": now().timestamp(), "結論": "GO確認待ち"}
        if live and c.get("_approved") and (r.get("出品") or r["結論"] not in ("GO", "GO（後回し）", "エラー")):
            mgo.pop(c["id"], None)
        if live and r["結論"] == "エラー" and re.search(r"already have on eBay|item specific .* is missing|duplicate", str(r.get("理由", "")), re.I):
            r["結論"] = "見送り"   # eBay が重複・必須の項目で止めた品は、毎時やり直さない（同じエラーで枠を使わない）
        if live and r["結論"] in ("GO", "見送り", "人に返す") and (r["結論"] != "GO" or r.get("出品")):   # 影の運転の間は記録しない（GAS に今までどおり送る）
            done[c["id"]] = {"t": r["t"], "結論": r["結論"]}
        time.sleep(0.5)
    if rows:
        save_ledger(rows, list(rows[0].keys()), NAME)
    # 11/24 09:45 オーナー「絶対Amazon，楽天ラクマ全ての工程GAS使わないで！」：この2つの品は GAS へ回さず「見送り」にする
    no_gas_ids = {c["id"] for c in todo if c.get("src") in NO_GAS}
    for r in res:
        if r.get("id") in no_gas_ids and r.get("結論") == "GASへ":
            r["結論"], r["理由"] = "見送り", "GitHub で出せない（GASは使わない：Amazon・ラクマ）／" + str(r.get("理由") or "")
            done[r["id"]] = {"t": now().timestamp(), "結論": "見送り"}
    # 店のサイトの地引網の品で「GASへ」になったものは、ここから GAS に送る（店の地引網の品は、店の地引網が送る）
    to_gas = [c for c in todo if c.get("src") not in ("楽天", "Yahoo!", "ラクマ", "Amazon") and not str(c.get("id", "")).startswith("人:") and any(r.get("id") == c["id"] and r["結論"] == "GASへ" for r in res)]
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
    save_json(mgo_p, mgo)
    save_json(mauto_p, mauto)
    ch, cm = judge.comp_cache_save()
    if live and ans_files:   # 取り込んだ GO の答え（出品できた・できなかったに関わらず）は取り込み済みへ
        import shutil as _sh
        os.makedirs(os.path.join(ROOT, "data", "答え", "取り込み済み"), exist_ok=True)
        for f in ans_files:
            _sh.move(f, os.path.join(ROOT, "data", "答え", "取り込み済み", os.path.basename(f)))
    save_json(os.path.join(ROOT, "data", "判定", "記録", now().strftime("%Y%m%d_%H%M%S") + ".json"),
              {"時刻": jst(), "本番": live, "Browseの残り": rem.get("remaining"), "結果": res})
    cnt = collections.Counter(x["結論"] for x in res)
    msg = ["【判定と出品】%s %s：%d品を判定（GitHubだけ）" % (jst(), "本番" if live else "影の運転", len(res)),
           "・".join("%s %d" % kv for kv in cnt.most_common())]
    msg.append("相場の使い回し：%d回・eBayの検索 %d回" % (ch, cm))
    if pre:
        msg.append("判定の前に外した：" + "・".join("%s %d" % kv for kv in pre.most_common()))
    why = collections.Counter(x.get("理由", "") for x in res if x["結論"] in ("見送り", "GASへ"))
    if why:
        msg.append("理由：" + "・".join("%s %d" % (k[:30], v) for k, v in why.most_common(5)))
    hum = [x for x in res if str(x.get("id", "")).startswith("人:")]
    if hum:
        msg.append("メルカリ・Amazon（あなたが送った品）：" + " / ".join("%s %s%s" % (x["型番"], x["結論"], "（%s）" % x.get("理由", "")[:40] if x.get("理由") else "") for x in hum[:10]))
    new_wait = [x for x in res if x.get("結論") == "GO確認待ち"]
    if new_wait:
        msg.append("【メルカリのGO確認】まだ売っているか確かめて、出すなら「メルカリGO 番号」と Claude に（番号は m から始まる商品番号）：\n" + "\n".join(
            "・%s %s 仕入 %s円 → $%.2f 利益 %s円 %s" % (mgo[c["id"]]["商品"], x["型番"], format(int(x["仕入値"]), ","), x.get("値段") or 0, format(int(x.get("利益") or 0), ","), x["url"])
            for x in new_wait for c in [next(cc for cc in todo if cc["id"] == x["id"])]))
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
