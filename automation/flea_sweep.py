"""フリマ新着の地引網（教科書 第3章「地引網」・付録⑯ 仕入先キット）。

Yahoo!フリマ・ヤフオク（即決）・イシバシ楽器（11/13 追加）・フジヤカメラ（11/14 追加）の「販売中」の品を、まとめ検索語（メーカー＋種類）ごとに1ページずつ読み、
型番リスト（data/型番リスト_スナップショット.csv）と照合して候補を数える。
- 節度（付録⑯ throttle）: 同じサイトへの間隔は 4秒以上、robots.txt で禁止のページは開かない、
  403/429/503 が来たら、その日はこのサイトを止める（第3章 守るライン2）
- 時刻表.json の「実行」が false の間はドライラン：集めて数えて、data/ に記録と通知をするだけ（ツールには送らない）
- 秘密（通知先）は環境変数から読む。ログに出さない
"""
from __future__ import annotations
import csv, datetime as dt, json, os, random, re, sys, time, urllib.parse, urllib.request, urllib.error, urllib.robotparser
from zoneinfo import ZoneInfo

ROOT = os.environ.get("LEDGER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 公開側で動かすときは、データ置き場（非公開）の場所
JST = ZoneInfo("Asia/Tokyo")
NAME = "フリマ新着の地引網"
HOST = "paypayfleamarket.yahoo.co.jp"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
NG = re.compile(r"ジャンク|動作未確認|未確認|現状品|現状渡し|部品取り|訳あり|通電のみ|故障|難あり|のみ|用[（(\s]|互換|対応品|ケース単品|説明書|箱だけ|空箱|ストラップ|キーホルダー|フィギュア|ガチャ|ステッカー|まとめ売り|セット売り")
BLOCK = {403, 429, 503, 999}
# 11/12 カナリアで、付属品（純正ケーブル・Z50用バッテリー）を本体の型番と取り違えた → 本体を示す語が無いときは外す（ツール側 v575 と同じ）
ACC = re.compile(r"ケーブル|コード(?!レス)|バッテリー|電池パック|充電器|チャージャー|アダプター|アダプタ|フード|レンズキャップ|ボディキャップ|ベゼル|イヤーパッド|イヤパッド|リモコン|ストラップ|フォーカシングスクリーン|交換用|互換|使い方|ガイドブック|マニュアル|ムック")
ACC_OK = re.compile(r"本体|ボディ|一式|付属品|付き|付|セット")


def now():
    return dt.datetime.now(JST)


def load_cfg():
    t = json.load(open(os.path.join(ROOT, "時刻表.json"), encoding="utf-8"))
    return t["プログラム"][NAME]


def load_models():
    out = []
    with open(os.path.join(ROOT, "data", "型番リスト_スナップショット.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            md = r["型番"].strip().upper()
            key = re.sub(r"[\s\-‐－]", "", md)
            if len(key) < 3 or not re.search(r"\d", key):
                continue
            # 型番の文字のあいだに「- や空白」があってもよい・前後は英数字でない（例 PS-6 が PS-60 に当たらない）
            pat = r"(?<![A-Z0-9])" + r"[\s\-‐－]?".join(re.escape(c) for c in key) + r"(?![A-Z0-9])"
            out.append({"maker": r["メーカー"].strip(), "model": r["型番"].strip(), "cap": int(r["仕入れ上限（円）"] or 0), "rx": re.compile(pat)})
    out.sort(key=lambda m: -len(m["model"]))  # 長い型番を先に（PS-6 より PS-6R を先に当てる）
    return out


class Polite:
    def __init__(self, gap, host=HOST):
        self.gap, self.last, self.calls, self.host = gap, 0.0, 0, host
        self.rp = urllib.robotparser.RobotFileParser()
        self.rp.set_url(f"https://{host}/robots.txt")
        # 11/14：robots.txt も同じ名乗り（UA）で読む（Python の既定の名乗りだと 403 を返す店があり、全部「禁止」に見えていた）
        try:
            req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                self.rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self.rp.disallow_all = True
            else:
                self.rp.allow_all = True
        except Exception:
            self.rp.disallow_all = True

    def get(self, path):
        url = f"https://{self.host}{path}"
        if not self.rp.can_fetch(UA, url) or not self.rp.can_fetch("*", url):
            return "robots", ""
        rest = self.gap + random.uniform(0, 2) - (time.time() - self.last)
        if rest > 0:
            time.sleep(rest)
        self.calls += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                self.last = time.time()
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            self.last = time.time()
            return e.code, ""
        except Exception:
            self.last = time.time()
            return 0, ""


def parse(html):
    """検索ページから 商品ID・名前・値段 を読む（GAS の ysParse_ と同じ読み方）。"""
    html = re.sub(r"<script[^>]*application/ld\+json[^>]*>[\s\S]*?</script>", "", html, flags=re.I).replace("<!-- -->", "")
    items, seen = [], set()
    for m in re.finditer(r'<a [^>]*data-cl-params="([^"]*)"[^>]*href="(/item/(z\d+))"', html):
        iid = m.group(3)
        if iid in seen or "_cl_link:itm" not in m.group(1):
            continue
        seen.add(iid)
        pm = re.search(r"price:(\d+)", m.group(1))
        block = html[m.end(): m.end() + 3000]
        nxt = block.find('data-cl-params="_cl_link:itm')
        if nxt > 0:
            block = block[:nxt]
        tm = re.search(r'alt="([^"]{4,200})"', block)
        if not (pm and tm):
            continue
        title = tm.group(1).replace("&amp;", "&").replace("&quot;", '"')
        items.append({"id": iid, "url": f"https://{HOST}/item/{iid}", "title": title, "price": int(pm.group(1))})
    return items


YAUC = "auctions.yahoo.co.jp"


def parse_yauc(html):
    """ヤフオクの検索ページの pageData（JSON）から、即決のある品だけ読む（即決＝その値段で買える）。"""
    m = re.search(r"var pageData = (\{.*?\});</script>", html, flags=re.S)
    if not m:
        return None
    try:
        items = json.loads(m.group(1)).get("items", [])
    except Exception:
        return None
    out = []
    for x in items:
        win = int(float(x.get("winPrice") or 0))
        if win <= 0:
            continue
        out.append({"id": "yauc:" + x["productID"], "url": f"https://{YAUC}/jp/auction/{x['productID']}", "title": x.get("productName", ""), "price": win})
    return out


ISB = "store.ishibashi.co.jp"
ISB_KW = re.compile(r"BOSS|Roland|KORG|ローランド|コルグ|YAMAHA|ヤマハ|エフェクター|ペダル|シンセ|MXR|Electro|ZOOM|ズーム|LINE ?6|TC ?Electronic|Strymon|Fender|Ibanez|アイバニーズ|Marshall|VOX|ギター|ベース|ドラム|マシン|サンプラー|ミキサー|マイク|Shure|AKAI|Teenage|Elektron|Moog|Nord|CASIO|カシオ|Digitech|Eventide|Behringer|Kemper|Line6|Jim Dunlop|Dunlop|Xotic|BOGNER|Ernie", re.I)


def parse_isb(html):
    """イシバシ楽器（11/13 オーナー承認：規約に転売・自動の禁止なし／robots.txt なし）の検索ページから 商品ID・名前・値段・写真 を読む。"""
    items, seen = [], set()
    parts = re.split(r'<a class="im-products-card"', html)
    for b in parts[1:]:
        b = b[:6000]
        m = re.search(r'href="https://store\.ishibashi\.co\.jp/view/item/(\d+)"', b)
        t = re.search(r'data-name="([^"]{4,300})"', b)
        pr = re.search(r'data-field="price">([\d,]+)<', b)
        if not (m and t and pr) or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        img = re.search(r'src="(https://makeshop-multi-images\.akamaized\.net/[^"]+)"', b)
        title = re.sub(r"【[^】]*店】", "", t.group(1).replace("&amp;", "&").replace("&quot;", '"')).strip()
        items.append({"id": "isb:" + m.group(1), "url": f"https://{ISB}/view/item/{m.group(1)}", "title": title, "price": int(pr.group(1).replace(",", "")),
                      **({"photos": [img.group(1)]} if img else {})})
    return items if parts[1:] else ([] if "検索結果" in html else None)


FJY = "www.fujiya-camera.co.jp"


def parse_fjy(html):
    """フジヤカメラ（11/14 オーナー承認：購入ガイド・特商法に転売の禁止なし。検索ページは robots で禁止なので、中古の新着順の一覧だけ読む）。"""
    items, seen = [], set()
    blocks = html.split('class="block-thumbnail-t--goods js-enhanced-ecommerce-item"')
    for b in blocks[1:]:
        b = b[:5000]
        m = re.search(r'href="/shop/g/g([A-Z0-9]+)/"', b)
        nm = re.search(r'block-thumbnail-t--goods-name">\s*([^<]{2,200}?)\s*</div>', b)
        br = re.search(r'<div class="txt-en">([^<]{1,60})</div>', b)
        pr = re.search(r'￥([\d,]+)', b)
        cond = re.search(r'secondhand_item">([^<]{1,20})<', b)
        if not (m and nm and pr) or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        img = re.search(r'data-src="(/img/goods/[^"]+)"', b)
        title = ((br.group(1).strip() + " ") if br else "") + nm.group(1).strip() + ((" " + cond.group(1).strip()) if cond else "")
        items.append({"id": "fjy:" + m.group(1), "url": f"https://{FJY}/shop/g/g{m.group(1)}/", "title": title.replace("&amp;", "&"), "price": int(pr.group(1).replace(",", "")),
                      **({"photos": [f"https://{FJY}" + img.group(1)]} if img else {})})
    return items if blocks[1:] else ([] if "中古" in html else None)


KMH = "komehyo.jp"


def parse_kmh(html):
    """コメ兵（11/14 オーナー承認：ご利用ガイド・特商法に転売の禁止なし／robots.txt は全部許可）。新入荷の一覧から 商品ID・名前・値段・写真。"""
    items, seen = [], set()
    parts = html.split('class="p-link p-link--card" href="/product/')
    for b in parts[1:]:
        b = b[:3000]
        m = re.match(r'([0-9-]{6,30})/"', b)
        nm = re.search(r'p-link__txt--productsname">([^<]{2,200})<', b)
        br = re.search(r'p-link__txt--brand">([^<]{1,60})<', b)
        rk = re.search(r'p-link__txt--rank">ランク：<span class="p-link__txt--rating">([^<]{1,20})<', b)
        pr = re.search(r'￥([\d,]+)', b)
        if not (m and nm and pr) or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        img = re.search(r'src="(https://img\.komehyo\.jp/[^"]+)"', b)
        title = nm.group(1).strip() + ((" " + br.group(1).strip()) if br else "") + ((" " + rk.group(1).strip()) if rk else "")
        items.append({"id": "kmh:" + m.group(1), "url": f"https://{KMH}/product/{m.group(1)}/", "title": html_unescape(title), "price": int(pr.group(1).replace(",", "")),
                      **({"photos": [img.group(1).replace("_icon", "")]} if img else {})})
    return items if parts[1:] else ([] if "p-lists" in html else None)


def html_unescape(t):
    return t.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")


YAO = "www.yaotomi.co.jp"
PAB = "peekaboo-camera.jp"


VEC = "www.vector-park.jp"


def parse_vec(text):
    """ベクトルパーク（11/15 オーナー承認：ご利用ガイドに転売の禁止なし・robots は Crawl-delay 10）。腕時計の一覧から 商品ID・名前・値段 を読む。
    同じ商品が同じ番号で Yahoo!ショッピングの vectorpremium 店にあるので、ツールへは Yahoo!ショッピングの商品として送る（在庫の確認・写真は今の仕組み）。"""
    out = []
    for m in re.finditer(r'<p class="item_img"><a href="/item/([\w-]+)/"[^>]*><img [^>]*alt="([^"]*)"[^>]*/?></a></p>(.*?)<div class="item_labels">', text, re.S):
        iid, title, rest = m.group(1), html_unescape(m.group(2)), m.group(3)
        pm = re.search(r'￥([\d,]+)', rest)
        if not pm:
            continue
        rank = re.search(r'rank_([a-z]+)\.gif', rest)
        out.append({"id": "vec:" + iid, "url": f"https://store.shopping.yahoo.co.jp/vectorpremium/{iid}.html", "title": title.strip() + (f"（ランク{rank.group(1).upper()}）" if rank else ""),
                    "price": int(pm.group(1).replace(",", ""))})
    return out


def parse_yao(text):
    """カメラの八百富（11/14 オーナー承認：規約は「明らかな転売目的の大量注文」だけを断る＝1点ずつは可）。中古の新着（Shopify の公開の一覧 JSON・並べ替えは robots で禁止なので使わない）。"""
    try:
        ps = json.loads(text).get("products", [])
    except Exception:
        return None
    out = []
    for p in ps:
        vs = [v for v in p.get("variants", []) if v.get("available")]
        if not vs:
            continue
        imgs = [i.get("src") for i in p.get("images", []) if i.get("src")][:10]
        out.append({"id": "yao:" + str(p["id"]), "url": f"https://{YAO}/products/{p['handle']}", "title": p.get("title", "").replace("【中古】", "").strip(),
                    "price": int(float(vs[0].get("price") or 0)), **({"photos": imgs} if imgs else {})})
    return out


def parse_pab(text):
    """PEEK A BOO CAMERA（11/14 オーナー承認：規約に転売の禁止なし）。WooCommerce の公開の商品一覧（新しい順）。"""
    try:
        ps = json.loads(text)
    except Exception:
        return None
    if not isinstance(ps, list):
        return None
    out = []
    for p in ps:
        if not p.get("is_in_stock"):
            continue
        pr = p.get("prices", {})
        price = int(pr.get("price") or 0) // (10 ** int(pr.get("currency_minor_unit") or 0))
        imgs = [i.get("src") for i in p.get("images", []) if i.get("src")][:10]
        out.append({"id": "pab:" + str(p["id"]), "url": p.get("permalink", ""), "title": html_unescape(re.sub(r"<[^>]+>", "", p.get("name", ""))), "price": price, **({"photos": imgs} if imgs else {})})
    return out


def compile_models(rows):
    out = []
    for r in rows:
        md = str(r.get("model", "")).strip().upper()
        key = re.sub(r"[\s\-‐－]", "", md)
        if len(key) < 3 or not re.search(r"\d", key):
            continue
        # 区切り（- や空白）は、型番にもともと区切りがある所だけ許す（「AM/FM 2バンド」を FM2 と取り違えない）
        # 前に英数字や - があるときは別の型番の一部（「EX-Z50」は Z50 ではない・「ATH-S100」は S100 ではない）
        parts = [p for p in re.split(r"[\s\-‐－]+", md) if p]
        pat = r"(?<![A-Z0-9\-‐－/])" + r"[\s\-‐－]?".join(re.escape(p) for p in parts) + r"(?![A-Z0-9])"
        out.append({"maker": r.get("maker", ""), "model": r.get("model", ""), "cap": int(r.get("cap") or 0), "listed": bool(r.get("listed")), "rx": re.compile(pat)})
    out.sort(key=lambda m: -len(m["model"]))
    return out


def gas_get_models():
    """ツールから最新の型番リストとまとめ検索語を読む（読めなければ None → リポジトリのスナップショットを使う）。"""
    url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
    if not (url.startswith("https://script.google.com/") and tok):
        return None
    try:
        q = url + "?" + urllib.parse.urlencode({"page": "models", "token": tok})
        d = json.loads(urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": "ebay-automation"}), timeout=120).read().decode("utf-8"))
        if d.get("models"):
            try:   # 写しを残す（GAS が止まっても、GitHub は写しで探し続ける）
                from common import ROOT as _R, save_json as _sj
                _sj(os.path.join(_R, "data", "型番リスト", "GASの写し.json"), d)
            except Exception:
                pass
            return with_github_models(d)
        return None
    except Exception as e:
        print("ツールの型番リストを読めなかった：", type(e).__name__)
        try:
            from common import ROOT as _R, load_json as _lj
            d = _lj(os.path.join(_R, "data", "型番リスト", "GASの写し.json"), {})
            if d.get("models"):
                print("型番リストは前の写しを使う")
                return with_github_models(d)
        except Exception:
            pass
        return None


def with_github_models(d):
    """GAS の型番リストに、GitHub が育てた型番（data/型番リスト/追加.json）を足す。出品中かどうかは台帳のタイトルで見る"""
    try:
        from common import ROOT as _R, load_json as _lj, read_ledger as _rl
        add = _lj(os.path.join(_R, "data", "型番リスト", "追加.json"), [])
        if not add:
            return d
        k = lambda s: re.sub(r"[^A-Z0-9]", "", str(s or "").upper())
        have = {k(m.get("model")) for m in d["models"]}
        big = "|" + "|".join(re.sub(r"[\-‐－]", "", (r.get("タイトル") or "").upper()) for r in _rl() if r.get("状態") == "出品中") + "|"
        for a in add:
            kk = k(a["model"])
            if kk in have:
                continue
            have.add(kk)
            d["models"].append({"maker": a["maker"], "model": a["model"], "cap": int(round(float(a.get("med") or 0) * 152 * 0.5)),
                                "listed": re.search(r"(?<![A-Z0-9])" + re.escape(re.sub(r"[\-‐－]", "", a["model"].upper())) + r"(?![A-Z0-9])", big) is not None})
    except Exception as e:
        print("GitHubの型番の追加を読めなかった：", type(e).__name__)
    return d


def gas_post(data):
    url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
    body = urllib.parse.urlencode({"token": tok, "data": json.dumps(data, ensure_ascii=False)}).encode()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        r = urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url, data=body, headers={"User-Agent": "ebay-automation"}), timeout=180)
        return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303) and e.headers.get("Location"):
            return urllib.request.urlopen(e.headers["Location"], timeout=180).read().decode("utf-8", "replace")
        raise


def match(title, models):
    t = title.upper()
    for m in models:
        if m["rx"].search(t):
            return m
    return None


IMG_RX = re.compile(r"https://auctions\.c\.yimg\.jp/images\.auctions\.yahoo\.co\.jp/image/[^\"'?\s<>]+?\.(?:jpg|jpeg|png)", re.I)


def add_photos(cands, cfg, t_end):
    """11/13：ツールは Yahoo の商品ページから写真を取れない（画像取得失敗）→ GitHub が商品ページを1回だけ開いて写真のURLを集めて渡す。
    同じサイトへは4〜6秒あける・断られたら、そのサイトの写真集めはやめる（出品はツール側で止まるだけ）。"""
    pols, stop = {}, set()
    n = 0
    for c in cands:
        if time.time() > t_end or n >= int(cfg.get("写真を集める上限", 60)):
            break
        if len(c.get("photos", [])) >= 2:
            continue   # 一覧で写真がそろっている店（八百富・PEEK A BOO など）は開かない
        if c["id"].startswith("vec:"):
            continue   # ベクトルパークは Yahoo!ショッピングの商品として送る（写真はツールが Yahoo!ショッピングの公式の窓口から取る）
        host = YAUC if c["id"].startswith("yauc:") else ISB if c["id"].startswith("isb:") else FJY if c["id"].startswith("fjy:") else KMH if c["id"].startswith("kmh:") else HOST
        if host in stop:
            continue
        pol = pols.get(host) or pols.setdefault(host, Polite(float(cfg.get("アクセスの間隔_秒", 4)), host))
        if host == FJY:
            # 11/14：フジヤカメラの商品ページは機械のアクセスに確認画面（202）を返すので開かない。写真は決まった場所（/img/goods/L/…_l.jpg・/img/goods/1/…_1.jpg …）にあるので、写真だけ確かめる
            gid, imgs = c["id"][4:], []
            for sub in ["L/" + gid + "_l.jpg"] + [f"{k}/{gid}_{k}.jpg" for k in range(1, 9)]:
                if time.time() > t_end:
                    break
                code, _ = pol.get("/img/goods/" + sub)
                if code == 200:
                    imgs.append(f"https://{FJY}/img/goods/" + sub)
                elif code in BLOCK:
                    stop.add(host)
                    break
                elif sub[0].isdigit():
                    break   # 番号の写真は続き番号なので、無い番号が出たら終わり
            n += 1
            if imgs:
                c["photos"] = imgs[:10]
            continue
        code, html = pol.get(c["url"].split(host, 1)[1])
        n += 1
        if code in BLOCK:
            stop.add(host)
            continue
        if code != 200:
            continue
        imgs = []
        rx = re.compile(r"https://img\.komehyo\.jp/contents/images/goods/[^\"'\s<>]*" + c["id"][4:].replace("-", "") + r"_\d+\.(?:jpg|jpeg|png)", re.I) if host == KMH else re.compile(r"/img/goods/(?!S/)[^\"'\s<>]*" + c["id"][4:] + r"[^\"'\s<>]*?\.(?:jpg|jpeg|png)", re.I) if host == FJY else re.compile(r"https://makeshop-multi-images\.akamaized\.net/1484music/itemimages/0*" + c["id"][4:] + r"[^\"'\s<>]*?\.(?:jpg|jpeg|png)", re.I) if host == ISB else IMG_RX
        for u in rx.findall(html):
            if u.startswith("/"):
                u = "https://" + host + u
            if u not in imgs:
                imgs.append(u)
        if imgs:
            c["photos"] = imgs[:10]
    return n


def send_to_tool(cands, cfg):
    """本番：候補をツールへ15品ずつ送る。ツールが型番・上限・利益・送料・付属品をもう一度判定して出品する。"""
    url, tok = os.environ.get("GAS_WEBAPP_URL", "").strip(), os.environ.get("GAS_SEND_TOKEN", "").strip()
    if not (url.startswith("https://script.google.com/") and tok):
        raise SystemExit("本番に必要な GAS_WEBAPP_URL / GAS_SEND_TOKEN が Secrets に入っていない（または形がちがう）")
    limit = int(cfg.get("カナリアの件数", 20)) if not cfg.get("カナリア済み") else 10**6
    cands = cands[:limit]
    ok = 0
    def site_of(c):
        return "ヤフオク（新着の地引網・即決）" if c["id"].startswith("yauc:") else "イシバシ楽器（地引網）" if c["id"].startswith("isb:") else "フジヤカメラ（地引網）" if c["id"].startswith("fjy:") else "コメ兵（地引網）" if c["id"].startswith("kmh:") else "カメラの八百富（地引網）" if c["id"].startswith("yao:") else "PEEK A BOO CAMERA（地引網）" if c["id"].startswith("pab:") else "Yahoo!ショッピング（ベクトルパーク・地引網）" if c["id"].startswith("vec:") else "Yahoo!フリマ（新着の地引網）"
    groups = {}
    for c in cands:
        groups.setdefault(site_of(c), []).append(c)
    batches = [(site, g[i:i + 15]) for site, g in groups.items() for i in range(0, len(g), 15)]
    for site, part in batches:
        host = YAUC if "ヤフオク" in site else ISB if "イシバシ" in site else FJY if "フジヤ" in site else KMH if "コメ兵" in site else YAO if "八百富" in site else PAB if "PEEK" in site else "store.shopping.yahoo.co.jp" if "ベクトル" in site else HOST
        txt = gas_post({"kind": "search", "perItem": True, "noAi": True, "keyword": "", "url": "https://" + host + "/", "site": site,
                        "items": [{"url": c["url"], "title": c["title"][:200], "price": c["price"], "sold": False, "thumb": "\n".join(c.get("photos", [])), "model": c.get("型番", ""), "maker": c.get("メーカー", "")} for c in part]})  # 11/15：照合した型番も送る（ツールが商品名から型番を読み直せず「型番がリストにない」で落としていた）
        if "合言葉が一致しません" in txt or "送信できませんでした" in txt:
            raise SystemExit("ツールが受け取りを断った（合言葉か住所がちがう）")
        ok += len(part)
        time.sleep(5)
    return ok, len(cands)


def notify(text):
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip().strip('"').strip("'")
    if url and not url.startswith("https://"):
        raise SystemExit("通知先（NOTIFY_WEBHOOK_URL）の形がちがう：https:// で始まるウェブフックURLを Secrets に入れ直してください")
    if not url:
        print("通知先が未設定（NOTIFY_WEBHOOK_URL）")
        return
    req = urllib.request.Request(url, data=json.dumps({"content": text[:1900]}).encode(), headers={"Content-Type": "application/json", "User-Agent": "ebay-automation"})
    urllib.request.urlopen(req, timeout=20).read()  # 失敗したら例外 → その回は失敗（CLAUDE.md 8章）


def sweep(pol, kws, parser, path_of, models, seen, stat, cands, nomatch, t_end, stop_p, today, label):
    """1つのサイトを、検索語ごとに1ページずつ読む。断られたら、そのサイトは今日は止める。"""
    for kw in kws:
        if time.time() > t_end:
            break
        code, html = pol.get(path_of(kw))
        if code == "robots":
            stat["robotsで開かない"] += 1
            continue
        if code in BLOCK:
            why = f"{label} HTTP {code}（{kw}）"
            st = json.load(open(stop_p, encoding="utf-8")) if os.path.exists(stop_p) else {}
            if st.get("日付") != today:
                st = {"日付": today}
            st[label] = now().strftime("%H:%M") + " " + why
            os.makedirs(os.path.dirname(stop_p), exist_ok=True)
            json.dump(st, open(stop_p, "w", encoding="utf-8"), ensure_ascii=False)
            return why
        stat["ページ"] += 1
        stat[label + "の語"] = stat.get(label + "の語", 0) + 1
        items = parser(html) if code == 200 else None
        if items is None or (not items and parser is parse):
            stat["読めなかったページ"] += 1
            items = []
        elif not items:
            stat["即決の品が無いページ"] = stat.get("即決の品が無いページ", 0) + 1
        for it in items:
            stat["品"] += 1
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            stat["新しい品"] += 1
            m = match(it["title"], models)
            if not m:
                nomatch.append(it["title"])
                continue
            stat["型番が合う"] += 1
            if NG.search(it["title"]):
                stat["付属品・ジャンク等"] += 1
                continue
            if ACC.search(it["title"]) and not ACC_OK.search(it["title"]):
                stat["付属品・ジャンク等"] += 1
                continue
            if m["cap"] and it["price"] < m["cap"] * 0.2:
                stat["付属品の疑い（上限の2割未満）"] = stat.get("付属品の疑い（上限の2割未満）", 0) + 1
                continue
            if m["listed"]:
                stat["もう出品中の型番"] += 1
                continue
            if not m["cap"]:
                stat["上限が未計算"] += 1
                verdict = "上限が未計算（ツールで判定）"
            elif it["price"] <= m["cap"] * 1.10:
                stat["上限以内"] += 1
                verdict = "上限以内"
            else:
                stat["上限超え"] += 1
                continue
            cands.append({**it, "検索語": kw.split("\t")[0], "サイト": label, "メーカー": m["maker"], "型番": m["model"], "仕入れ上限": m["cap"], "判定": verdict})
    return ""


def resend_latest(cfg):
    """手動：最新の記録の候補のうち、まだ送っていない品だけを送る（ページは開かない）。"""
    import glob
    f = sorted(glob.glob(os.path.join(ROOT, "data", "フリマ新着", "2*.json")))[-1]
    d = json.load(open(f, encoding="utf-8"))
    sent_p = os.path.join(ROOT, "data", "フリマ新着", "送った品.json")
    sent_ids = set(json.load(open(sent_p, encoding="utf-8"))) if os.path.exists(sent_p) else set()
    rows = [{"maker": "", "model": c["型番"], "cap": c["仕入れ上限"]} for c in d["候補"]]
    cands = []
    for c in d["候補"]:
        if c["id"] in sent_ids or NG.search(c["title"]) or (ACC.search(c["title"]) and not ACC_OK.search(c["title"])):
            continue
        m = match(c["title"], compile_models([{"model": c["型番"], "cap": c["仕入れ上限"]}]))   # 今の厳しい照合で、もう一度確かめる
        if not m:
            continue
        cands.append(c)
    cands.sort(key=lambda c: (c["判定"] != "上限以内", c["price"]))
    add_photos(cands[:60], cfg, time.time() + 600)
    ok, n = send_to_tool(cands, cfg)
    lim = int(cfg.get("カナリアの件数", 20)) if not cfg.get("カナリア済み") else 10**6
    sent_ids.update(c["id"] for c in cands[:lim])
    json.dump(sorted(sent_ids)[-40000:], open(sent_p, "w", encoding="utf-8"))
    notify(f"🛒本番｜地引網：{os.path.basename(f)} のまだ送っていない候補 {len(cands)}品のうち {ok}品をツールへ送った（ページは開いていない）")
    print("送った", ok, "/", len(cands))


def main():
    cfg = load_cfg()
    if os.environ.get("RESEND_LATEST") == "1":
        return resend_latest(cfg)
    dry = not cfg.get("実行", False)
    t0, today = now(), now().strftime("%Y%m%d")
    stop_p = os.path.join(ROOT, "data", "停止", "yahoo_furima.json")
    stopped_today = json.load(open(stop_p, encoding="utf-8")) if os.path.exists(stop_p) else {}
    if stopped_today.get("日付") != today:
        stopped_today = {}
    remote = gas_get_models()
    if remote:
        models = compile_models(remote["models"])
        words = remote.get("words") or []
        src = f"ツールの最新リスト（{len(models)}型番・検索語{len(words)}）"
    else:
        rows = [{"maker": r["メーカー"], "model": r["型番"], "cap": r["仕入れ上限（円）"]} for r in csv.DictReader(open(os.path.join(ROOT, "data", "型番リスト_スナップショット.csv"), encoding="utf-8"))]
        models = compile_models(rows)
        words = json.load(open(os.path.join(ROOT, "data", "まとめ検索語.json"), encoding="utf-8"))
        src = f"スナップショット（{len(models)}型番）"
    if not words:
        words = json.load(open(os.path.join(ROOT, "data", "まとめ検索語.json"), encoding="utf-8"))
    # 検索語は回ごとに順に回す（全部を毎回読むと回数が多すぎるので、1回 N 語ずつ）
    cur_p = os.path.join(ROOT, "data", "フリマ新着", "順番.json")
    cur = json.load(open(cur_p, encoding="utf-8")).get("次", 0) if os.path.exists(cur_p) else 0
    n = int(os.environ.get("TEST_PAGES") or cfg.get("1回に開くページの上限", 60))   # 手動の試しでは少しだけ
    kws = [words[(cur + i) % len(words)] for i in range(min(n, len(words)))]
    seen_p = os.path.join(ROOT, "data", "フリマ新着", "見た品.json")
    seen = set(json.load(open(seen_p, encoding="utf-8"))) if os.path.exists(seen_p) else set()
    stat = {"ページ": 0, "robotsで開かない": 0, "読めなかったページ": 0, "品": 0, "新しい品": 0, "型番が合う": 0, "付属品・ジャンク等": 0, "もう出品中の型番": 0, "上限以内": 0, "上限が未計算": 0, "上限超え": 0}
    cands, nomatch, stops = [], [], []
    gap = float(cfg.get("アクセスの間隔_秒", 4))
    t_end = t0.timestamp() + 60 * int(cfg.get("深掘りの時間_分", 18) if os.environ.get("DEEP") == "1" else cfg.get("時間の上限_分", 15)) - 90
    half = t0.timestamp() + (t_end - t0.timestamp()) * 0.55
    # 11/15 オーナー「教科書の人と同じやり方」：教科書 序章「夕方の定時＋週2回の深掘り」。深掘りの回（DEEP=1）は、各検索語の2〜N ページ目を読む
    deep = os.environ.get("DEEP") == "1"
    if deep:
        dp = int(cfg.get("深掘りのページ", 4))
        dcur_p = os.path.join(ROOT, "data", "フリマ新着", "深掘り順番.json")
        dcur = json.load(open(dcur_p, encoding="utf-8")).get("次", 0) if os.path.exists(dcur_p) else 0
        base = [words[(dcur + i) % len(words)] for i in range(len(words))]
        kws = [kw + "\t" + str(pg) for kw in base for pg in range(2, dp + 1)]
        stat["深掘り"] = f"2〜{dp}ページ目"
    def kp(kw):
        a = kw.split("\t")
        return a[0], (int(a[1]) if len(a) > 1 else 1)
    def ys_path(kw):
        w, pg = kp(kw)
        return "/search/" + urllib.parse.quote(w) + "?open=1" + (f"&page={pg}" if pg > 1 else "")
    def ya_path(kw):
        w, pg = kp(kw)   # ヤフオクは新しい順（教科書 第18章「新着から」）。2ページ目からは b=51,101…
        return "/search/search?p=" + urllib.parse.quote(w) + "&s1=new&o1=d" + (f"&b={(pg - 1) * 50 + 1}&n=50" if pg > 1 else "")
    if "Yahoo!フリマ" not in stopped_today:
        why = sweep(Polite(gap, HOST), kws, parse, ys_path, models, seen, stat, cands, nomatch, half, stop_p, today, "Yahoo!フリマ")
        if why:
            stops.append(why)
    if "ヤフオク" not in stopped_today:
        why = sweep(Polite(gap, YAUC), kws, parse_yauc, ya_path, models, seen, stat, cands, nomatch, t_end, stop_p, today, "ヤフオク")
        if why:
            stops.append(why)
    # 11/13 オーナー承認（「２いれて！」）：イシバシ楽器（中古楽器）も同じ網で見る。楽器の語だけ・6秒以上あける
    isb_words = [w for w in words if ISB_KW.search(w) and not re.search(r"時計|カメラ|レンズ", w)]
    if isb_words and "イシバシ楽器" not in stopped_today and time.time() < t_end:
        k = int(cfg.get("イシバシ1回の語数", 12))
        isb_kws = [isb_words[(cur + i) % len(isb_words)] for i in range(min(k, len(isb_words)))]
        why = sweep(Polite(max(gap, 6), ISB), isb_kws, parse_isb, lambda kw: "/search?q=" + urllib.parse.quote_plus(kw) + "&searchbox=1", models, seen, stat, cands, nomatch, t_end + 60, stop_p, today, "イシバシ楽器")
        if why:
            stops.append(why)
    # 11/14 オーナー承認（「はい！」）：フジヤカメラの中古の新着順（/shop/c/c20_ssd/）を、上から数ページだけ。6秒以上あける
    if "フジヤカメラ" not in stopped_today and time.time() < t_end + 60:
        k = int(cfg.get("フジヤ1回のページ", 3))
        pages = ["1"] + [str(i) for i in range(2, k + 1)]
        why = sweep(Polite(max(gap, 6), FJY), pages, parse_fjy, lambda pg: "/shop/c/c20_ssd/" if pg == "1" else f"/shop/c/c20_ssd_p{pg}/", models, seen, stat, cands, nomatch, t_end + 120, stop_p, today, "フジヤカメラ")
        if why:
            stops.append(why)
    # 11/14 オーナー承認（「はい」）：コメ兵の新入荷（時計・カメラなど）。一覧だけ・6秒以上あける
    if "コメ兵" not in stopped_today and time.time() < t_end + 120:
        paths = cfg.get("コメ兵の一覧", ["/watch/?new=0", "/camera/?new=0", "/search/?new=0"])
        why = sweep(Polite(max(gap, 6), KMH), paths, parse_kmh, lambda pth: pth, models, seen, stat, cands, nomatch, t_end + 180, stop_p, today, "コメ兵")
        if why:
            stops.append(why)
    # 11/15 オーナー承認（「はい」）：ベクトルパークの腕時計（メーカーごとの一覧の1ページ目）。robots の Crawl-delay 10 を守って11秒あける
    if "ベクトルパーク" not in stopped_today and time.time() < t_end + 120 and not deep:
        makers = [w.split()[0] for w in words if "腕時計" in w]
        k = int(cfg.get("ベクトルパーク1回の語数", 4))
        vkw = [makers[(cur + i) % len(makers)] for i in range(min(k, len(makers)))] if makers else []
        why = sweep(Polite(max(gap, 11), VEC), vkw, parse_vec, lambda kw: "/list/?kw=" + urllib.parse.quote((kw.upper() + " 腕時計").encode("euc-jp")), models, seen, stat, cands, nomatch, t_end + 180, stop_p, today, "ベクトルパーク")
        if why:
            stops.append(why)
    # 11/14 オーナー承認（「はい」）：カメラの八百富・PEEK A BOO CAMERA の新着（公開の一覧 JSON）。6秒以上あける
    for lab, host, prs, paths in [("カメラの八百富", YAO, parse_yao, ["/collections/used/products.json?limit=50", "/collections/used/products.json?limit=50&page=2"]),
                                  ("PEEK A BOO CAMERA", PAB, parse_pab, ["/wp-json/wc/store/v1/products?orderby=date&order=desc&per_page=50"])]:
        if lab not in stopped_today and time.time() < t_end + 180:
            why = sweep(Polite(max(gap, 6), host), paths, prs, lambda pth: pth, models, seen, stat, cands, nomatch, t_end + 240, stop_p, today, lab)
            if why:
                stops.append(why)
    os.makedirs(os.path.dirname(cur_p), exist_ok=True)
    # 11/14：時間の上限で途中で止まったら、読めた語の分だけ進める（読まずに飛ばす語を作らない）
    done_n = max(stat.get("Yahoo!フリマの語", 0), stat.get("ヤフオクの語", 0)) or len(kws)
    if deep:   # 深掘りは別の順番で進める（毎日の新着の順番は動かさない）
        json.dump({"次": (dcur + done_n // max(dp - 1, 1)) % max(len(words), 1)}, open(dcur_p, "w", encoding="utf-8"))
    else:
        json.dump({"次": (cur + done_n) % max(len(words), 1)}, open(cur_p, "w", encoding="utf-8"))
    json.dump(sorted(seen)[-40000:], open(seen_p, "w", encoding="utf-8"))
    # 網を育てる：リストにない品の名前をツールへ（知らない型番を追加候補に。出品はしない）
    ml = ""
    if remote and nomatch:
        try:
            r = json.loads(gas_post({"kind": "mlcand", "titles": nomatch[:300]}))
            ml = f"リストにない品 {r.get('got')}件 → 型番の候補 {r.get('cand')}件"
        except Exception as e:
            ml = "リストにない品を送れなかった（" + type(e).__name__ + "）"
    sent = None
    sent_p = os.path.join(ROOT, "data", "フリマ新着", "送った品.json")
    sent_ids = set(json.load(open(sent_p, encoding="utf-8"))) if os.path.exists(sent_p) else set()
    if False:
        # はじめての本番：ドライランで見つけていた直近24時間の候補も合わせる（同じ品は二重に送らない）
        import glob
        have = {c["id"] for c in cands}
        for fp in sorted(glob.glob(os.path.join(ROOT, "data", "フリマ新着", "2*.json")))[-8:]:
            try:
                old = json.load(open(fp, encoding="utf-8"))
                if (t0 - dt.datetime.strptime(old["開始JST"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)).total_seconds() > 86400:
                    continue
                for c in old.get("候補", []):
                    if c["id"] not in have:
                        have.add(c["id"]); c.setdefault("サイト", "Yahoo!フリマ"); cands.append(c)
            except Exception:
                pass
    # 11/13：前のドライランの候補を合わせる仕組みで、同じ品を2回送っていた → 送った品は二度と送らない・前の候補は使わない
    cands = [c for c in cands if c["id"] not in sent_ids]
    cands.sort(key=lambda c: (c["判定"] != "上限以内", c["price"]))
    if not dry and cands:
        lim0 = int(cfg.get("カナリアの件数", 20)) if not cfg.get("カナリア済み") else 10**6
        stat["写真を集めた"] = add_photos(cands[:lim0], cfg, t0.timestamp() + 60 * int(cfg.get("時間の上限_分", 15)) + 300)
        cands = [c for c in cands if c.get("photos")] + [c for c in cands if not c.get("photos")]
        sent = send_to_tool(cands, cfg)
        stat["ツールへ送った"] = sent[0]
        lim = int(cfg.get("カナリアの件数", 20)) if not cfg.get("カナリア済み") else 10**6
        sent_ids.update(c["id"] for c in cands[:lim])
        json.dump(sorted(sent_ids)[-40000:], open(sent_p, "w", encoding="utf-8"))
    stamp = t0.strftime("%Y%m%d_%H%M")
    json.dump({"ドライラン": dry, "開始JST": t0.strftime("%Y-%m-%d %H:%M"), "型番リスト": src, "検索語": kws, "数": stat, "止めた": stops, "網を育てる": ml, "候補": cands},
              open(os.path.join(ROOT, "data", "フリマ新着", f"{stamp}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.makedirs(os.path.join(ROOT, "data", "実行記録"), exist_ok=True)
    json.dump({"最後に動いた時刻JST": now().strftime("%Y-%m-%d %H:%M"), "最後に成功した時刻JST": now().strftime("%Y-%m-%d %H:%M"), "件数": stat["上限以内"], "エラー数": len(stops)},
              open(os.path.join(ROOT, "data", "実行記録", "flea_sweep.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    head = ("🧪ドライラン" if dry else "🛒本番") + f"｜フリマ新着の地引網（Yahoo!フリマ＋ヤフオク即決） {t0.strftime('%m/%d %H:%M')} JST｜{src}"
    body = "・".join(f"{k} {v}" for k, v in stat.items())
    top = "\n".join(f"- [{c['サイト']}] {c['型番']} {c['price']:,}円（上限 {c['仕入れ上限']:,}円）" for c in cands if c["判定"] == "上限以内")
    notify(head + "\n" + body + ("\n🌱 " + ml if ml else "") + ("\n⛔ 断られたので今日は止めた：" + " / ".join(stops) if stops else "") + ("\n" + top[:900] if top else ""))
    print(head, body, stops, ml)


if __name__ == "__main__":
    main()
