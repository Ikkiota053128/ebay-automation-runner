"""出品中の品の商品説明を、新しい明るい説明（desc_template.html）に入れかえる（手で動かす）。
11/23 12:31 オーナー「商品説明全て変えて」。10章：まずドライラン → 20品 → オーナーが見て OK → 残り。
- data/判定/説明の直し.json：{"本番": false, "件数": 20, "時間の上限_分": 22}
- 前の説明が GitHub の説明（表がある形）なら、表の中身（ブランド・型番・状態・状態の説明・動作・付属品）をそのまま使う。
- それ以外（GAS で出した説明）は、eBay の商品の項目（Brand・Model）と状態の説明（conditionDescription）から作る。
  前の説明の文は「From the original listing」に残す（品ごとの大事な説明を消さない）。
- オファーを読み（GET）→ 説明だけ差しかえ → 保存（PUT）→ 読み直して確かめる（10章 3）。取り下げの一覧の品は外す。
- 結果は data/判定/説明の直し_結果.json。"""
import html as H, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, Ebay, EbayError, err_text, jst, load_json, save_json, read_ledger

CL = {"Content-Language": "en-US"}
P = os.path.join(ROOT, "data", "判定", "説明の直し.json")
RP = os.path.join(ROOT, "data", "判定", "説明の直し_結果.json")
TPL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "desc_template.html"), encoding="utf-8").read()


def esc(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_of(h):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</tr>", "\n", t)
    t = H.unescape(re.sub(r"<[^>]+>", " ", t))
    t = "\n".join(re.sub(r"[ \t　]+", " ", x).strip() for x in t.splitlines())
    return re.sub(r"\n{2,}", "\n", t).strip()


def cell(old, label):
    m = re.search(r">\s*%s\s*</td>\s*<td[^>]*>(.*?)</td>" % re.escape(label), old or "", re.S)
    return H.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else None


def aspect(item, *names):
    a = (item.get("product") or {}).get("aspects") or {}
    for n in names:
        v = a.get(n)
        if v:
            return v[0] if isinstance(v, list) else v
    return ""


def build(o, item, r):
    old = o.get("listingDescription") or ""
    p = item.get("product") or {}
    title = p.get("title") or r.get("タイトル") or ""
    new = str(item.get("condition") or "").startswith("NEW")
    v = {k: cell(old, k) for k in ("Brand", "Model", "Condition", "Condition notes", "Function", "Included")}
    ours = "OTA JAPAN GEAR" in old and v["Brand"] is not None
    if ours:
        d = {"BRAND": v["Brand"], "MODEL": v["Model"] or "", "COND": v["Condition"] or ("New" if new else "Used"),
             "NOTES": v["Condition notes"] or "Please check the photos.", "FUNC": v["Function"] or "",
             "INCLUDED": v["Included"] or "Only the items in the photos"}
        extra = ""
    else:
        cd = (item.get("conditionDescription") or "").strip()
        d = {"BRAND": aspect(item, "Brand") or "-", "MODEL": aspect(item, "Model", "MPN") or "-",
             "COND": "New" if new else "Used",
             "NOTES": cd or "Please check the photos and the notes below.",
             "FUNC": "New item." if new else "Please see the notes below and the photos.",
             "INCLUDED": "Only the items in the photos"}
        t = text_of(old)
        skip = re.compile(r"^(OTA JAPAN GEAR.*|✈.*|CONDITION|SHIPS IN|RETURNS|60 days, free|\d+ business days|◆.*|New|Used|Rank [A-Z]+)$")
        t = "\n".join(x for x in t.splitlines() if x and x != title and not skip.match(x))
        extra = ""
        if t:   # 前の説明の文を残す（品ごとの大事な説明を消さない）
            extra = ('<div style="background:#ffffff;border:1px solid #f1dcc0;border-left:5px solid #13294b;border-radius:12px;'
                     'padding:14px 16px;margin:0 0 16px 0;"><div style="font-size:19px;font-weight:bold;color:#13294b;margin-bottom:6px;">'
                     'From the original listing</div><div style="white-space:pre-line;font-size:15px;">%s</div></div>' % esc(t[:3500]))
    h = TPL
    for k, x in [("TITLE", title)] + list(d.items()):
        h = h.replace("{{%s}}" % k, esc(x) if k != "TITLE" else esc(x))
    # 発送日数は前の説明に書いてあった日数のまま（品ごとの配送ポリシーに合わせる）
    m = re.search(r"(\d+)\s*(?:<[^>]+>\s*)*business days", old)
    days = m.group(1) if m else ("10" if re.search(r"netmall\.hardoff\.co\.jp|ec\.treasure-f\.com", r.get("仕入元URL", "")) else "3")
    h = h.replace("3 business days", "%s business days" % days)
    if "FedEx" not in old:   # FedEx 以外で送る品（前の説明に FedEx が無い）は、FedEx と書かない
        h = (h.replace("by <b>FedEx</b> with tracking", "with tracking").replace("FedEx from Japan", "shipping from Japan")
               .replace("Tracked FedEx", "Tracked shipping"))
    if extra:
        mark = '<div style="background:#ffffff;border:1px solid #f1dcc0;border-left:5px solid #13294b;border-radius:12px;padding:14px 16px;margin:0 0 16px 0;"><div style="font-size:19px;font-weight:bold;color:#13294b;margin-bottom:6px;">About This Item'
        h = h.replace(mark, extra + mark, 1)
    return h, ("GitHubの説明" if ours else "GASの説明")


cfg = load_json(P, {"本番": False, "件数": 20})
live = bool(cfg.get("本番"))
eb = Ebay()
res = load_json(RP, {"品": {}})
done = res.setdefault("品", {})
out = {"時刻": jst(), "本番": live, "直した": [], "予定": [], "失敗": [], "見た": 0}
t_end = time.time() + 60 * float(cfg.get("時間の上限_分", 22))
n_max = int(cfg.get("件数", 20))
wd = set(load_json(os.path.join(ROOT, "data", "判定", "取り下げ.json"), {}).get("待ち") or [])
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-") and r["SKU"] not in wd]
first = list(cfg.get("先に") or [])
rows.sort(key=lambda r: (r["SKU"] not in first, first.index(r["SKU"]) if r["SKU"] in first else 0))
for r in rows:
    if time.time() > t_end:
        out["時間切れ"] = True
        break
    if len(out["直した"]) + len(out["予定"]) >= n_max:
        break
    sku = r["SKU"]
    d0 = done.get(sku, {})
    if d0.get("直した日時") or d0.get("失敗", 0) >= 2:
        continue
    out["見た"] += 1
    try:
        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
        item = eb.inventory_item(sku)
        new, kind = build(o, item, r)
        if not live:
            if sum(1 for x in out["予定"] if x["形"] == kind) < 2:
                od = os.path.join(ROOT, "data", "ログ", "説明の見本"); os.makedirs(od, exist_ok=True)
                open(os.path.join(od, sku + ".html"), "w", encoding="utf-8").write(new)
            out["予定"].append({"SKU": sku, "形": kind, "出品ID": r.get("eBayの出品ID"), "前の説明の文": text_of(o.get("listingDescription"))[:300]})
            continue
        o["listingDescription"] = new
        for k in ("offerId", "status", "listing"):
            o.pop(k, None)
        eb.call("PUT", "/sell/inventory/v1/offer/" + r["offerId"], o, headers=CL)
        _, chk = eb.call("GET", "/sell/inventory/v1/offer/" + r["offerId"])
        if "Thank you for visiting" not in (chk.get("listingDescription") or ""):
            raise EbayError(0, {"raw": "読み直したら説明が変わっていない"})
        done[sku] = {"直した日時": jst(), "形": kind}
        out["直した"].append({"SKU": sku, "形": kind, "出品ID": r.get("eBayの出品ID")})
    except EbayError as e:
        done[sku] = dict(d0, 失敗=d0.get("失敗", 0) + 1)
        out["失敗"].append({"SKU": sku, "エラー": err_text(e)[:400]})
save_json(RP, dict(res, 最後=out))
print("本番" if live else "ドライラン", "見た", out["見た"], "直した", len(out["直した"]), "予定", len(out["予定"]), "失敗", len(out["失敗"]))
