# ⑤ 値段の調整（教科書 第22章④・CLAUDE.md 14章）
#  1) 赤字の品（利益5%・1,500円を割った品）→ 最低利益の値段まで上げる
#  2) 出品（数え始め）から60日売れない品 → 出品を終える（withdrawOffer）
#  3) 30日売れない品 → 最低利益の値段まで下げる
#  4) それ以外 → 同じ型番・同じ状態の一番安い競合（自分の出品は除く・送料込み）より $1 安く。最低利益の値段より下げない。競合に合わせた値上げはしない
#  扱うのは、Inventory API へ移し終えた品（台帳に offerId がある品）だけ。
#  時刻表.json の「実行」が false の間はドライラン（eBayは読むだけ。変える案を data/値段の調整/ に書いて知らせる）
import datetime as dt, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (best_offer_terms, ROOT, Ebay, EbayError, err_text, floor_price, profit_yen, num, now, jst, settings, timetable, notify, notify_once_a_day,
                    read_ledger, save_ledger, is_target, write_run, mark_started, browse_stopped, browse_stop, usual_ok,
                    usual_add, load_json, save_json)

NAME = "値段の調整"
# 相場の相手にしない出品（GASのツール v652・v599 と同じ決まり。11/18 オーナー「変な最安値に合わせないで」）
JUNK = re.compile(r"for parts|not working|\bjunk\b|broken|as[- ]is|\blot of\b|\blot\b|bundle|set of|adapter only|battery (door|cover)|"
                  r"footswitch (cap|rubber)|rubber (pad|feet)|\bscrews?\b|\bpcb\b|circuit board|board only|enclosure only|housing only|"
                  r"spare spool|replacement spool|\bspool only\b|handle knob|reel stand|knob set|cap only|hood only|strap only|charger only|"
                  r"\buntested\b|not tested|parts only|\bdamaged\b|\bdefect(ive)?\b|\bcracked\b|read (the )?description|no battery|"
                  r"without battery|battery not included|no charger|without charger|lens only|\bno lens\b|manual only|box only|empty box|"
                  r"\bmissing\b|\bfaulty\b|needs repair|for repair", re.I)
ACC = re.compile(r"\b(case only|carrying case|protective case|cover|skin|sticker|decal|ear ?tips?|eartips|ear ?pads?|replacement|"
                 r"compatible|protector|screen film|manual only|box only|empty box|knobs?|spool only|handle only|lens cap|front cap|rear cap)\b", re.I)
BOOK = re.compile(r"\b(for dummies|dummies|books?|guide|guidebook|manuals?|instructions?|brochure|catalog(ue)?|posters?|advert(isement)?|"
                  r"print ad|magazine|snapshots|great shots|field guide|service notes|clock|t-?shirt|shirt|keychain|mug|patch|sticker|decal|"
                  r"grommet|mod service|service only)\b", re.I)
REF_ACC = re.compile(r"\b(hood|lens hood|battery grip|grip|housing|underwater|case|bag|pouch|strap|charger|adapter|adaptor|batter(y|ies)|"
                     r"board|motherboard|pcb|parts?|repair|replacement|light seal|seal kit|lens cap|body cap|cap|cover|holder|film back|winder|"
                     r"motor drive|power supply|footswitch|knobs?|screen protector|protector|cable|cord|remote|eyecup|viewfinder|finder|loupe|"
                     r"extension tube|converter|conversion lens|led light)\b", re.I)
NOT_MODEL = re.compile(r"^(PS\d?|PSP\d*|DS\d*|[23]DS|GBA?|N64|HDMI\d*|USB\d*|[48]K|TYPE\d*|VER\d*|CD\d*|DVD\d*|BD\d*|"
                       r"\d*GB|\d*TB|\d*MB|MM\d*|CM\d*|V\d+|W\d+|JAN\d*|AC\d{2,3}V?|DC\d+V?|NO\d+|VOL\d+)$")


def model_of(title):
    t = re.sub(r"[‐‑–—－−]", "-", str(title or "")).upper()
    c = re.findall(r"\b[A-Z]{2,5}-[A-Z]{1,4}\d{1,5}[A-Z]{0,4}(?:-\d{1,4}[A-Z]{0,3})?\b|\b[A-Z]{1,6}-?\d{2,5}[A-Z]{0,4}"
                   r"(?:-\d{1,4}[A-Z]{0,3})?\b|\b[A-Z]{2,6}\d[A-Z]{0,3}\b|\b[A-Z]{2,5}-\d[A-Z]{0,2}\b", t)
    c = [x for x in c if ("-" in x or not NOT_MODEL.match(x)) and re.search(r"\d", x)]   # BOSS DS-1 のようにハイフンがあれば型番
    return max(c, key=len) if c else ""


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def cond_filter(cid):
    c = int(num(cid) or 3000)
    return "7000" if c >= 7000 else ("1000|1500" if c < 3000 else "3000|4000|5000|6000")


def is_acc(title, md):
    """付属品・「for 型番」の出品（例：Case for BOSS DS-1）"""
    t = str(title or "")
    if ACC.search(t):
        return True
    tl = re.sub(r"[-\s]", "", t.lower())
    i, j = tl.find(md.replace("-", "").lower()), tl.find("for")
    return j >= 0 and i >= 0 and j < i


def clean(items):
    """本・グッズを外す → 付属品の言葉を外す（型番そのものが付属品なら残す）→ 中央値の30%未満を外す"""
    k0 = [x for x in items if not BOOK.search(x["t"])]
    k1 = [x for x in k0 if not REF_ACC.search(x["t"])]
    keep = k1 if (len(k1) >= 3 or len(k1) >= len(k0)) else k0
    ts = sorted(x["p"] for x in keep)
    if ts and len(keep) >= 3:
        md = ts[len(ts) // 2]
        keep = [x for x in keep if x["p"] >= md * 0.3]
    return keep


def cheapest_comp(eb, row, me, my_ids, cfg):
    """同じ型番・同じ状態・即決・自分を除く・送料込みの「本物の最安」。判定（judge.py）と同じ外し方：
    付属品・ジャンク・本・外れ値（GAS quotePrice_ の v303・v394・v652：真ん中の半分・35%・65%より安い品、すぐ上より15%安い品）を外す"""
    import judge
    from over_check import market
    md = model_of(row.get("タイトル"))
    if not md:
        return None, "型番が読めない"
    from model_grow import size_code
    if size_code((row.get("タイトル") or "").split(" ")[0], md):
        return None, "リールの大きさの記号（%s）は型番ではないので比べない" % md
    act = judge.comps(eb, md, int(num(row.get("eBayの状態ID")) or 3000), me, my_ids)
    m = market(act)
    if not m:
        return None, "同じ型番の競合なし"
    return m["最安"], "競合%d件・最安$%.2f・真ん中$%.2f（%s）" % (m["件数"], m["最安"], m["真ん中"], md)


def sold_skus(eb, days):
    """支払い済みの注文に入っていたSKUと、その注文の日（JST）だけを使う（買い手の情報は読まない・残さない）"""
    since = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    out, off = {}, 0
    while True:
        _, j = eb.call("GET", "/sell/fulfillment/v1/order?filter=creationdate:%%5B%s..%%5D&limit=200&offset=%d" % (since, off))
        for o in j.get("orders", []):
            if o.get("orderPaymentStatus") != "PAID" or (o.get("cancelStatus") or {}).get("cancelState") == "CANCELED":
                continue
            d = o.get("creationDate", "")[:10]
            for li in o.get("lineItems", []):
                if li.get("sku"):
                    out[li["sku"]] = max(out.get(li["sku"], ""), d)
        off += 200
        if off >= int(j.get("total", 0)):
            return out


def age_days(row, sold):
    start = row.get("出品日") or row.get("移した日時", "")[:10]
    last = max(start, sold.get(row["SKU"], ""))
    try:
        return (now().date() - dt.date.fromisoformat(last[:10])).days
    except ValueError:
        return None


def decide(row, price, floor, age, comp, cfg):
    u = cfg.get("売れない品", {})
    lower_d, end_d = u.get("下げる日数", 30), u.get("終える日数", 60)
    if price < floor - 0.004:
        return "値上げ（赤字）", floor
    if age is not None and age >= end_d:
        return "出品を終える（%d日売れない）" % age, None
    big = float(cfg.get("_1回に下げる割合の上限", 0.3))   # 11/24 06:48 オーナー「至急1〜4やって」：1回で30%より大きい値下げは自動でしない（$858.99→$85.44 の事故）
    if age is not None and age >= lower_d and price > floor + 0.004:
        if floor < price * (1 - big):
            return "要確認（大きすぎる値下げ %d%%）" % round((1 - floor / price) * 100), None
        return "値下げ（%d日売れない）" % age, floor
    if comp:
        step = cfg.get("プログラムの数字_キット⑨⑩⑪", {}).get("値下げ_最安からいくら下げるか_ドル", 1.0)
        new = round(max(floor, comp - step), 2)
        if new < price * (1 - big):
            return "要確認（大きすぎる値下げ %d%%）" % round((1 - new / price) * 100), None
        if new < price - 0.004:
            return "値下げ（最安−$%g）" % step if new > floor else "値下げ（最低利益まで）", new
    return "変更なし", None


def preview(eb, cfg):
    """まだ1品も移していない間の下見（読むだけ）。鍵が使えるかと、移したら何が起きるかを見せる。
    値段は台帳の値（GASの出品一覧から作った値）。競合は先頭20品だけ検索する。"""
    from stock_watch import kind_of
    rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("SKU") and not r["SKU"].startswith("要付与-")
            and kind_of(r.get("仕入元URL"), cfg) in ("A", "C")]
    msg = ["【値段の調整・下見】%s（まだ移した品が無いので読むだけ。移す予定の %d品で計算）" % (jst(), len(rows))]
    keys = []
    try:
        sold = sold_skus(eb, 60)
        keys.append("ユーザーの鍵OK（支払い済みの注文に入っていたSKU %d個）" % len(sold))
    except EbayError as e:
        keys.append("ユーザーの鍵で注文が読めない：" + err_text(e))
    rem = eb.browse_remaining()
    keys.append("アプリの鍵OK（検索の残り %s回）" % rem.get("remaining") if rem else "アプリの鍵で回数上限が読めない")
    me = cfg.get("店", {}).get("セラー名", "").lower()
    my_ids = {r.get("eBayの出品ID") for r in read_ledger()}
    plan, nof = [], 0
    for i, r in enumerate(rows):
        floor = floor_price(r, cfg)
        if floor is None:
            nof += 1
            continue
        price = num(r.get("売値(ドル)")) or 0
        comp, why = None, ""
        if i < 20 and rem and not browse_stopped():
            try:
                comp, why = cheapest_comp(eb, r, me, my_ids, cfg)
            except EbayError as e:
                why = err_text(e)
        act, new = decide(r, price, floor, None, comp, cfg)
        plan.append({"SKU": r["SKU"], "判定": act, "今$": price, "案$": new, "最低利益$": floor, "競合": why})
    ups = [p for p in plan if p["判定"].startswith("値上げ")]
    downs = [p for p in plan if p["判定"].startswith("値下げ")]
    msg += keys
    msg.append("最低利益の値段を割っている品（移したら上げる）%d品・足りない分 合計$%.0f" %
               (len(ups), sum(p["案$"] - p["今$"] for p in ups)))
    msg.append("競合を見た20品のうち値下げの案 %d品／最低利益の値段が出せない品 %d品" % (len(downs), nof))
    for p in (ups[:8] + downs[:4]):
        msg.append("・%s %s $%.2f → $%.2f" % (p["SKU"], p["判定"], p["今$"], p["案$"]))
    save_json(os.path.join(ROOT, "data", "値段の調整", "下見_" + now().strftime("%Y%m%d_%H%M") + ".json"), {"時刻": jst(), "案": plan, "鍵": keys})
    write_run(NAME, True, 0, 0, {"Browse回数": eb.calls})
    notify("\n".join(msg))
    return 0


def main():
    cfg, tt = settings(), timetable(NAME)
    live = bool(tt.get("実行"))
    scheduled = os.environ.get("GITHUB_EVENT_NAME") == "schedule"
    eb = Ebay()
    mark_started(NAME)
    if not eb.ready():
        notify_once_a_day("鍵なし_値段の調整", "【値段の調整】GitHub に eBay の鍵（EBAY_CLIENT_ID・EBAY_CLIENT_SECRET・EBAY_REFRESH_TOKEN）が無いので、何もしていません")
        write_run(NAME, False, 0, 1)
        return 0   # 鍵が入るまでは毎回赤くしない（知らせは1日1回）
    rows = [r for r in read_ledger() if is_target(r) and r.get("状態") == "出品中"]
    if not rows:
        return preview(eb, cfg)
    me = cfg.get("店", {}).get("セラー名", "").lower()
    my_ids = {r.get("eBayの出品ID") for r in read_ledger()}
    fails = load_json(os.path.join(ROOT, "data", "値段の調整", "失敗.json"), {})
    sold = sold_skus(eb, max(cfg.get("売れない品", {}).get("終える日数", 60), 60)) if rows else {}
    can_browse = not browse_stopped()
    rem = eb.browse_remaining() if rows and can_browse else None
    if rem and (rem.get("remaining") or 0) < 300:
        can_browse = False
    browse_cap = int(tt.get("1回に検索する上限_回", 100))
    rows.sort(key=lambda r: r.get("最後に値段を変えた日時", ""))   # 長く見ていない品から
    plan, errs, noformula = [], [], []
    for r in rows:
        floor = floor_price(r, cfg)
        if floor is None:
            noformula.append(r["SKU"])
            continue
        try:
            offs = [o for o in eb.offers_of(r["SKU"]) if o.get("offerId") == r["offerId"]]
        except EbayError as e:
            errs.append((r["SKU"], err_text(e)))
            continue
        if not offs or offs[0].get("status") != "PUBLISHED":
            errs.append((r["SKU"], "オファーが見つからないか出品中でない"))
            continue
        price = num(offs[0]["pricingSummary"]["price"]["value"])
        comp, why = None, ""
        if can_browse and eb.browse_n >= browse_cap:
            can_browse, why = False, "今日の検索の上限（%d回）" % browse_cap
        if can_browse:
            try:
                comp, why = cheapest_comp(eb, r, me, my_ids, cfg)
            except EbayError as e:
                if e.status == 429:
                    rr = eb.browse_remaining() or {}
                    browse_stop(rr.get("reset", ""))
                    can_browse = False
                why = err_text(e)
        act, new = decide(r, price, floor, age_days(r, sold), comp, cfg)
        plan.append({"SKU": r["SKU"], "出品ID": r.get("eBayの出品ID"), "判定": act, "今$": price, "案$": new,
                     "最低利益$": floor, "競合": why, "利益(円)_今": round(profit_yen(price, r, cfg)),
                     "利益(円)_案": round(profit_yen(new, r, cfg)) if new else None})
    changes = [p for p in plan if p["判定"] != "変更なし"]
    ups = [p for p in changes if p["判定"].startswith("値上げ")][: int(tt.get("1回に値上げする上限_件", 30))]
    ends = [p for p in changes if p["判定"].startswith("出品を終える")][: int(tt.get("1回に出品を終える上限_件", 10))]
    downs = [p for p in changes if p["判定"].startswith("値下げ")]
    downs = downs[: max(0, int(tt.get("1回に値段を変える上限_件", 50)) - len(ups))]
    todo = ups + ends + downs
    bigs = [p for p in changes if p["判定"].startswith("要確認")]
    rec_dir = os.path.join(ROOT, "data", "値段の調整")
    stamp = now().strftime("%Y%m%d_%H%M")
    msg = ["【値段の調整】%s %s：見た %d品・案 %d件（値上げ %d・終える %d・値下げ %d）" %
           (jst(), "本番" if live else "ドライラン", len(plan), len(todo), len(ups), len(ends), len(downs))]
    if bigs:
        msg.append("大きすぎる値下げで止めた（オーナーが確かめる）%d品：%s" % (len(bigs), ", ".join("%s $%s %s" % (p["SKU"], p["今$"], p["判定"]) for p in bigs[:10])))
    if noformula:
        msg.append("最低利益の値段が出せない品 %d件（台帳に仕入値・送料・手数料率・関税率が無い）：%s" % (len(noformula), ", ".join(noformula[:10])))
    for s, e in errs[:5]:
        msg.append("読めなかった %s：%s" % (s, e))
    done, bad = [], []
    if live:
        ok, why = usual_ok(NAME, len(todo))
        canary = int(tt.get("カナリアの件数", 20)) if not tt.get("カナリア済み") else None
        if canary is not None:
            todo = todo[:canary]
            msg.append("カナリア：最初の%d件だけ変えます（確かめたら 時刻表.json の カナリア済み を true に）" % len(todo))
        elif not ok:
            msg.append("止めました：" + why)
            todo = []
        todo = [p for p in todo if fails.get(p["SKU"], 0) < 2]
        reqs = [{"sku": p["SKU"], "offers": [{"offerId": next(r["offerId"] for r in rows if r["SKU"] == p["SKU"]),
                                              "price": {"value": "%.2f" % p["案$"], "currency": "USD"}}]}
                for p in todo if p["案$"]]
        res = eb.bulk_update(reqs) if reqs else {}
        for p in todo:
            if p["案$"] is None:   # 出品を終える
                oid = next(r["offerId"] for r in rows if r["SKU"] == p["SKU"])
                try:
                    eb.withdraw(oid)
                    st = [o for o in eb.offers_of(p["SKU"]) if o.get("offerId") == oid]
                    (done if st and st[0].get("status") == "UNPUBLISHED" else bad).append(p)
                    if not (st and st[0].get("status") == "UNPUBLISHED"):
                        p["エラー"] = "終えたあとの読み直しで未公開になっていない"
                except EbayError as e:
                    p["エラー"] = err_text(e)
                    bad.append(p)
                continue
            okp, body = res.get(p["SKU"], (False, {}))
            if okp:   # 読み直して本当に変わったか
                oid = next(r["offerId"] for r in rows if r["SKU"] == p["SKU"])
                st = [o for o in eb.offers_of(p["SKU"]) if o.get("offerId") == oid]
                cur = num(st[0]["pricingSummary"]["price"]["value"]) if st else None
                okp = cur is not None and abs(cur - p["案$"]) < 0.005
                if not okp:
                    p["エラー"] = "読み直した値段が $%s" % cur
            else:
                p["エラー"] = err_text(body)
                # 25016：値下げ交渉の「自動で断る値段」が新しい値段以上 → オファーごと（値段と値下げ交渉を一緒に）直す（11/21 17:47 オーナー「1〜3お願いします」）
                if "25016" in p["エラー"]:
                    try:
                        oid = next(r["offerId"] for r in rows if r["SKU"] == p["SKU"])
                        _, o = eb.call("GET", "/sell/inventory/v1/offer/" + oid)
                        fpv = p.get("最低利益$") or 0
                        o.setdefault("pricingSummary", {})["price"] = {"value": "%.2f" % p["案$"], "currency": "USD"}
                        pol = o.get("listingPolicies") or {}
                        row = next(r for r in rows if r["SKU"] == p["SKU"])
                        pol["bestOfferTerms"] = best_offer_terms(row, cfg, p["案$"], fp=fpv or None)
                        o["listingPolicies"] = pol
                        for k in ("offerId", "status", "listing"):
                            o.pop(k, None)
                        eb.call("PUT", "/sell/inventory/v1/offer/" + oid, o, headers={"Content-Language": "en-US"})
                        st = [x for x in eb.offers_of(p["SKU"]) if x.get("offerId") == oid]
                        cur = num(st[0]["pricingSummary"]["price"]["value"]) if st else None
                        okp = cur is not None and abs(cur - p["案$"]) < 0.005
                        p["エラー"] = "" if okp else "オファーごと直したが、読み直した値段が $%s" % cur
                    except EbayError as e:
                        p["エラー"] += " ／オファーごと直すのも失敗：" + err_text(e)
            (done if okp else bad).append(p)
        for p in done:
            fails.pop(p["SKU"], None)
        for p in bad:
            fails[p["SKU"]] = fails.get(p["SKU"], 0) + 1
            if fails[p["SKU"]] >= 2:
                msg.append("2回続けて失敗（もう送りません）%s：%s" % (p["SKU"], p.get("エラー", "")))
        save_json(os.path.join(rec_dir, "失敗.json"), fails)
        upd = []
        by = {r["SKU"]: r for r in rows}
        for p in done:
            r = dict(by[p["SKU"]])
            if p["案$"] is None:
                r["状態"] = "終了"
            else:
                r["売値(ドル)"] = "%.2f" % p["案$"]
            r["最後に値段を変えた日時"] = jst()
            upd.append(r)
        if upd:
            save_ledger(upd, ["売値(ドル)", "状態", "最後に値段を変えた日時"], NAME)
        msg.append("変えた %d件・失敗 %d件" % (len(done), len(bad)))
    usual_add(NAME, len(todo), scheduled)
    for p in todo[:15]:
        msg.append("・%s %s $%s → %s（最低利益 $%s）" % (p["SKU"], p["判定"], p["今$"], ("$%.2f" % p["案$"]) if p["案$"] else "終了", p["最低利益$"]))
    save_json(os.path.join(rec_dir, stamp + ".json"), {"時刻": jst(), "本番": live, "案": plan, "変えた": done, "失敗": bad})
    write_run(NAME, not bad, len(done) if live else len(todo), len(errs) + len(bad), {"Browse回数": eb.calls})
    notify("\n".join(msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
