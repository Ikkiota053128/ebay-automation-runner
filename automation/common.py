# 共通部品（在庫の監視・値段の調整・今の出品の移行で使う）
# 決めごとは CLAUDE.md、窓口の形は docs_APIの最小契約表.md のとおり。秘密の情報は環境変数（GitHub Secrets）からだけ読む。
import base64, csv, datetime as dt, json, os, shutil, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

ROOT = os.environ.get("LEDGER_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JST, PT = ZoneInfo("Asia/Tokyo"), ZoneInfo("America/Los_Angeles")
API = "https://api.ebay.com"


def now():
    return dt.datetime.now(JST)


def jst(t=None):
    return (t or now()).astimezone(JST).strftime("%Y-%m-%d %H:%M") + " JST"


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def settings():
    return load_json(os.path.join(ROOT, "店の設定.json"), {})


def timetable(name):
    return load_json(os.path.join(ROOT, "時刻表.json"), {}).get("プログラム", {}).get(name, {})


# ---------------------------------------------------------------- 通知（8章）
def notify(text):
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip().strip('"').strip("'")
    if not url:
        print("[通知先が未設定] " + text)
        return
    if not url.startswith("https://"):
        raise SystemExit("通知先（NOTIFY_WEBHOOK_URL）の形がちがう")
    for i in range(0, max(len(text), 1), 1900):
        req = urllib.request.Request(url, data=json.dumps({"content": text[i:i + 1900]}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "ebay-automation"})
        urllib.request.urlopen(req, timeout=20).read()  # 失敗したら例外 → その回は失敗


def notify_once_a_day(key, text):
    """同じ知らせを1日に何回も送らない（8章）"""
    p = os.path.join(ROOT, "data", "通知済み.json")
    d = load_json(p, {})
    today = now().strftime("%Y-%m-%d")
    if d.get(key) == today:
        print("[今日はもう知らせた] " + text)
        return
    notify(text)
    d[key] = today
    save_json(p, d)


# ---------------------------------------------------------------- 実行記録（9章）
def write_run(name, ok, count, errors, extra=None):
    p = os.path.join(ROOT, "data", "実行記録", name + ".json")
    old = load_json(p, {})
    rec = {"最後に動いた時刻JST": now().strftime("%Y-%m-%d %H:%M"),
           "最後に成功した時刻JST": now().strftime("%Y-%m-%d %H:%M") if ok else old.get("最後に成功した時刻JST", ""),
           "件数": count, "エラー数": errors}
    if extra:
        rec.update(extra)
    save_json(p, rec)


def mark_started(name):
    """ドライランを最初に動かした時刻（9章）。プログラムごとに別のファイル（同時に動くプログラムどうしで保存がぶつからないように）"""
    old = load_json(os.path.join(ROOT, "data", "始めた日時.json"), {})
    if name in old:
        return
    p = os.path.join(ROOT, "data", "始めた日時", name + ".json")
    if not os.path.exists(p):
        save_json(p, {"始めた日時": jst()})


# ---------------------------------------------------------------- eBay（契約表 0・1・15章）
class EbayError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__("HTTP %s %s" % (status, json.dumps(body, ensure_ascii=False)[:3000]))


class Ebay:
    def __init__(self, opener=None):
        self.cid = os.environ.get("EBAY_CLIENT_ID", "")
        self.sec = os.environ.get("EBAY_CLIENT_SECRET", "")
        self.rt = os.environ.get("EBAY_REFRESH_TOKEN", "")
        self.tok = {}
        self.open = opener or urllib.request.urlopen
        self.calls = 0
        self.browse_n = 0

    def ready(self):
        return bool(self.cid and self.sec and self.rt)

    def _token(self, kind):
        t = self.tok.get(kind)
        if t and t[1] > time.time() + 300:   # 2時間は使い回す
            return t[0]
        if kind == "user":
            body = {"grant_type": "refresh_token", "refresh_token": self.rt}
        else:
            body = {"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}
        req = urllib.request.Request(API + "/identity/v1/oauth2/token", data=urllib.parse.urlencode(body).encode(), headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": "Basic " + base64.b64encode((self.cid + ":" + self.sec).encode()).decode()})
        j = json.loads(self.open(req, timeout=30).read())
        self.tok[kind] = (j["access_token"], time.time() + int(j.get("expires_in", 7200)))
        return j["access_token"]

    def call(self, method, path, body=None, kind="user", headers=None, retry=3):
        """5xxは少し待って3回まで送り直す。4xxは送り直さない（10章 8）。エラーの本文は全部持って返す。"""
        h = {"Authorization": "Bearer " + self._token(kind), "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        for i in range(retry + 1):
            self.calls += 1
            req = urllib.request.Request(API + path, data=data, method=method, headers=h)
            try:
                r = self.open(req, timeout=60)
                raw = r.read()
                return (r.status if hasattr(r, "status") else 200), (json.loads(raw) if raw else {})
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    j = json.loads(raw) if raw else {}
                except ValueError:
                    j = {"raw": raw.decode("utf-8", "replace")[:2000]}
                if e.code >= 500 and i < retry:
                    time.sleep(5 * (i + 1))
                    continue
                raise EbayError(e.code, j)

    def upload_image(self, path):
        """手元の写真を eBay に上げて、eBay の写真のアドレスを返す（Media API。人が送った写真用）"""
        import mimetypes, uuid
        bd = "----ebay" + uuid.uuid4().hex
        data = open(path, "rb").read()
        ct = mimetypes.guess_type(path)[0] or "image/jpeg"
        body = ("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (bd, os.path.basename(path), ct)).encode() + data + ("\r\n--%s--\r\n" % bd).encode()
        base = "https://apim.ebay.com/commerce/media/v1_beta/image"
        h = {"Authorization": "Bearer " + self._token("user"), "Content-Type": "multipart/form-data; boundary=" + bd}
        try:
            r = self.open(urllib.request.Request(base + "/create_image_from_file", data=body, method="POST", headers=h), timeout=120)
        except urllib.error.HTTPError as e:
            raise EbayError(e.code, {"raw": e.read().decode("utf-8", "replace")[:2000]})
        raw = r.read()
        j = json.loads(raw) if raw else {}
        if j.get("imageUrl"):
            return j["imageUrl"]
        loc = r.headers.get("Location", "")
        iid = loc.rstrip("/").split("/")[-1]
        r2 = self.open(urllib.request.Request(base + "/" + iid, headers={"Authorization": "Bearer " + self._token("user"), "Accept": "application/json"}), timeout=60)
        return json.loads(r2.read()).get("imageUrl", "")

    def trading(self, call, xml_body):
        """Trading API（XML）。読むだけの呼び出しにだけ使う（GetMyMessages の件数など）"""
        body = ('<?xml version="1.0" encoding="utf-8"?><%sRequest xmlns="urn:ebay:apis:eBLBaseComponents">%s</%sRequest>' % (call, xml_body, call)).encode()
        h = {"X-EBAY-API-IAF-TOKEN": self._token("user"), "X-EBAY-API-CALL-NAME": call, "X-EBAY-API-SITEID": "0",
             "X-EBAY-API-COMPATIBILITY-LEVEL": "1193", "Content-Type": "text/xml"}
        r = self.open(urllib.request.Request(API + "/ws/api.dll", data=body, method="POST", headers=h), timeout=60)
        return r.read().decode("utf-8", "replace")

    # Inventory（契約表 4・5・6・16章）
    def offers_of(self, sku):
        try:
            _, j = self.call("GET", "/sell/inventory/v1/offer?sku=" + urllib.parse.quote(sku) + "&marketplace_id=EBAY_US")
        except EbayError as e:
            if e.status == 404:
                return []
            raise
        return j.get("offers", [])

    def inventory_item(self, sku):
        _, j = self.call("GET", "/sell/inventory/v1/inventory_item/" + urllib.parse.quote(sku, safe=""))
        return j

    def bulk_update(self, reqs):
        """25件以下ずつ送り、中の1件ずつの statusCode を見る（10章 3）。返事は SKU→(成功か, 本文)"""
        out = {}
        for i in range(0, len(reqs), 25):
            part = reqs[i:i + 25]
            _, j = self.call("POST", "/sell/inventory/v1/bulk_update_price_quantity", {"requests": part})
            got = {r.get("sku"): r for r in j.get("responses", [])}
            for q in part:
                r = got.get(q["sku"])
                out[q["sku"]] = (bool(r) and r.get("statusCode") == 200, r or {"errors": [{"message": "返事に入っていない"}]})
        return out

    def withdraw(self, offer_id):
        return self.call("POST", "/sell/inventory/v1/offer/%s/withdraw" % offer_id, {})

    def browse(self, q, filt, limit=100, category=None):
        self.browse_n += 1
        prm = {"q": q, "filter": filt, "limit": limit}
        if category:
            prm["category_ids"] = category
        path = "/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(prm)
        _, j = self.call("GET", path, kind="app", headers={
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "X-EBAY-C-ENDUSERCTX": "contextualLocation=country=US,zip=10001"})
        return j.get("itemSummaries", [])

    def browse_remaining(self):
        try:
            _, j = self.call("GET", "/developer/analytics/v1_beta/rate_limit/?api_name=browse&api_context=buy", kind="app")
        except EbayError:
            return None
        for a in j.get("rateLimits", []):
            for res in a.get("resources", []):
                for r in res.get("rates", []):
                    return {"remaining": r.get("remaining"), "reset": r.get("reset")}
        return None


def err_text(e):
    """エラーは本文（message・longMessage・parameters）を全文で（10章 7）"""
    if isinstance(e, EbayError):
        errs = (e.body or {}).get("errors") or []
        if errs:
            return " / ".join("%s %s %s %s" % (x.get("errorId", ""), x.get("message", ""), x.get("longMessage", ""),
                                               json.dumps(x.get("parameters", []), ensure_ascii=False)) for x in errs)
        return "HTTP %s %s" % (e.status, json.dumps(e.body, ensure_ascii=False))
    if isinstance(e, dict):
        return " / ".join("%s %s %s %s" % (x.get("errorId", ""), x.get("message", ""), x.get("longMessage", ""),
                                           json.dumps(x.get("parameters", []), ensure_ascii=False)) for x in e.get("errors", []))
    return str(e)


# ---------------------------------------------------------------- 検索の止め（9章）
STOP = os.path.join(ROOT, "data", "停止", "browse.json")


LIMIT_STOP = os.path.join(ROOT, "data", "停止", "出品の上限.json")


def is_limit_error(text):
    """eBay の出品の上限（金額・件数）に当たった：25002 ... exceed the amount you can list"""
    t = str(text or "")
    return "exceed the amount you can list" in t or "exceed the number of items you can list" in t or "selling limit" in t.lower()


def listing_limit_stopped():
    d = load_json(LIMIT_STOP)
    if not d:
        return None
    try:
        if now() < dt.datetime.fromisoformat(d["再開してよい時刻"]):
            return d
    except Exception:
        return None
    return None


def listing_limit_stop(msg):
    """月の上限なので、次の月の1日（米国太平洋時間 0:00 ＝ 日本時間 17:00）まで出品を止める。上限を上げてもらったら、このファイルを消せば再開"""
    pt = now().astimezone(dt.timezone(dt.timedelta(hours=-8)))
    nxt = (pt.replace(day=28) + dt.timedelta(days=4)).replace(day=1, hour=0, minute=5, second=0, microsecond=0)
    save_json(LIMIT_STOP, {"止めた時刻": jst(), "再開してよい時刻": nxt.astimezone(JST).isoformat(), "eBayの返事": str(msg)[:600],
                           "_説明": "eBay の出品の上限（月）。上限を上げてもらったら、このファイルを消すと再開"})


def browse_stopped():
    d = load_json(STOP)
    if not d:
        return False
    try:
        return now() < dt.datetime.fromisoformat(d["再開してよい時刻"])
    except Exception:
        return False


def browse_stop(reset_iso):
    try:
        until = dt.datetime.fromisoformat(reset_iso.replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        until = now() + dt.timedelta(hours=24)
    save_json(STOP, {"止めた時刻": now().isoformat(), "再開してよい時刻": until.isoformat()})


# ---------------------------------------------------------------- 値付けの式（第5章・14章）
def floor_price(row, cfg):
    """利益の条件（率5%・1,500円）を満たす一番安い売値（ドル）。必要な値が欠けていれば None。"""
    f = cfg.get("値付けの式_第5章", {})
    fx = num(row.get("為替")) or f.get("為替_円per米ドル")
    fee, duty = pct(row.get("手数料率")), pct(row.get("関税率"))
    cost, ship = num(row.get("仕入値(円)")), num(row.get("出品時の海外送料(円)"))
    fixed = (num(row.get("固定費(円)")) or 0) + (num(row.get("国内送料(円)")) or 0)
    if not fx or fee is None or duty is None or not cost or not ship:
        return None
    rate, minyen = f.get("フロア_利益率の下限", 0.05), f.get("フロア_利益の下限_円", 1500)
    keep = 1 - fee - duty
    p1 = (cost + ship + fixed + minyen) / (fx * keep)
    p2 = (cost + ship + fixed) / (fx * (keep - rate)) if keep - rate > 0 else None
    if p2 is None:
        return None
    return round(max(p1, p2) + 0.005, 2)


def profit_yen(price, row, cfg):
    f = cfg.get("値付けの式_第5章", {})
    fx = num(row.get("為替")) or f.get("為替_円per米ドル")
    return price * fx * (1 - pct(row.get("手数料率")) - pct(row.get("関税率"))) - num(row.get("仕入値(円)")) \
        - num(row.get("出品時の海外送料(円)")) - (num(row.get("固定費(円)")) or 0) - (num(row.get("国内送料(円)")) or 0)


def num(v):
    try:
        return float(str(v).replace(",", "").replace("¥", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def pct(v):
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    n = num(s.rstrip("%"))
    if n is None:
        return None
    return n / 100 if s.endswith("%") or n > 1 else n


# ---------------------------------------------------------------- 台帳（5章）
LEDGER = "台帳.csv"
COLS = ["SKU", "eBayの出品ID", "offerId", "仕入元URL", "仕入元の種類", "仕入値(円)", "出品時の海外送料(円)", "売値(ドル)",
        "状態", "最後に仕入元を確認した日時", "出品日",
        # プログラムで使う列（14章の式・比べる相手）
        "タイトル", "eBayの状態ID", "手数料率", "関税率", "固定費(円)", "国内送料(円)", "為替", "移した日時", "最後に値段を変えた日時", "メモ"]


def ledger_path():
    return os.path.join(ROOT, LEDGER)


def read_ledger(path=None):
    path = path or ledger_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def save_ledger(rows, my_cols, who):
    """控えを取る → 最新を読み直し、SKUごとに自分の列だけ合わせる → 行数が減っていたら止める。"""
    path = ledger_path()
    latest = read_ledger(path)
    if latest:
        os.makedirs(os.path.join(ROOT, "控え"), exist_ok=True)
        shutil.copy(path, os.path.join(ROOT, "控え", "台帳_%s.csv" % now().strftime("%Y%m%d_%H%M%S")))
    mine = {r["SKU"]: r for r in rows}
    jp = os.environ.get("LEDGER_JOURNAL")
    if jp:   # 保存の直前に最新の台帳へ当て直すための、この回の変更の記録（ledger_merge.py）
        try:
            j = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else []
        except Exception:
            j = []
        j.append({"rows": [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows], "cols": list(my_cols)})
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False)
    by = {r["SKU"]: r for r in latest}
    for sku, r in mine.items():
        if sku in by:
            for c in my_cols:
                by[sku][c] = r.get(c, "")
        else:
            latest.append({c: r.get(c, "") for c in COLS})
    if len(latest) < len(read_ledger(path)):
        notify("【%s】台帳の行が減るので保存をやめました" % who)
        raise SystemExit("台帳の行数が減る")
    cols = COLS + [c for c in (latest[0].keys() if latest else []) if c not in COLS]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in latest:
            w.writerow({c: r.get(c, "") for c in cols})
    os.replace(tmp, path)


def is_target(row):
    """自動化プログラムが扱う品：有在庫（STK-）でなく、移し終えた（offerId がある）品だけ（14章）"""
    stk = settings().get("有在庫の目印_SKUの頭", "STK-")
    return row.get("SKU") and not row["SKU"].startswith(stk) and row.get("offerId")


# ---------------------------------------------------------------- 「ふだん」（10章 6）
def usual_ok(name, n_changes):
    """直近7日の定時の回1回あたりの平均の3倍（最低3件）を超えたら止める。定時の回が3回そろうまでは実行しない。"""
    p = os.path.join(ROOT, "data", "実行記録", name + "_回ごと.json")
    hist = [h for h in load_json(p, []) if h.get("t", "") >= (now() - dt.timedelta(days=7)).isoformat()]
    if len(hist) < 3:
        return False, "定時の回がまだ%d回（3回そろうまで実行しない）" % len(hist)
    avg = sum(h["n"] for h in hist) / len(hist)
    lim = 3 * max(avg, 1)
    return (n_changes <= lim), "ふだん %.1f件 → 上限 %.0f件" % (avg, lim)


def usual_add(name, n_changes, scheduled):
    if not scheduled:
        return
    p = os.path.join(ROOT, "data", "実行記録", name + "_回ごと.json")
    hist = [h for h in load_json(p, []) if h.get("t", "") >= (now() - dt.timedelta(days=8)).isoformat()]
    hist.append({"t": now().isoformat(), "n": n_changes})
    save_json(p, hist)


def hand_links(title):
    """人が手で探すためのリンク（メルカリ・Amazon）。プログラムはこのページを開かない（メルカリは機械で見ない決めごと・Amazon は規約）。"""
    import urllib.parse as _u, re as _r
    words = [w for w in _r.sub(r"[^\w\-/ ]", " ", str(title or "")).split()
             if not _r.match(r"(?i)^(used|new|japan|from|excellent|mint|near|tested|w/|with|the|and|for|exc\+*\d*)$", w)][:5]
    q = _u.quote(" ".join(words))
    if not q:
        return ""
    return "手で探す：メルカリ https://jp.mercari.com/search?keyword=%s&status=on_sale ／ Amazon https://www.amazon.co.jp/s?k=%s" % (q, q)
