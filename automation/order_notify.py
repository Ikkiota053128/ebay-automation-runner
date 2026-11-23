"""① 受注の通知（CLAUDE.md 2章・5章・9章）：支払い済みの新しい注文をスマホ（Discord）に知らせ、台帳を「売れた」にする。

- 注文は Fulfillment API（getOrders）。数えるのは支払い済み（PAID）だけ。キャンセルは数えない。
- 買い手の名前・住所・ID・注文番号は、知らせにもログにも出さない（AIに見せない・設計書4章）。
  記録（data/注文の記録/）には注文番号と SKU・金額・時刻だけ。買い手の欄は保存しない。知らせは SKU・タイトル・売値・仕入元URL。
- 同じ注文を2回知らせない（通知済みは注文番号のハッシュで data/受注の通知/通知済み.json に残す）。
- 始めた日時より前の注文は一斉に知らせない。ただし始める前から「支払い済み・まだ発送していない」注文は、1回だけ一覧（SKUだけ）で知らせる。
- 見張り：朝の報告が「導入済み」なら、その実行記録が26時間より古いときに知らせる。
"""
import datetime as dt, hashlib, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (ROOT, Ebay, EbayError, err_text, now, jst, timetable, notify, notify_once_a_day, read_ledger, save_ledger, hand_links,
                    write_run, mark_started, load_json, save_json, num)

NAME = "受注の通知"


def h(s):
    return hashlib.sha256(str(s).encode()).hexdigest()[:24]


def orders_since(eb, since_utc):
    out, off = [], 0
    while True:
        _, j = eb.call("GET", "/sell/fulfillment/v1/order?filter=creationdate:%%5B%s..%%5D&limit=200&offset=%d" % (since_utc, off))
        out += j.get("orders", [])
        if len(j.get("orders", [])) < 200 or off > 2000:
            return out
        off += 200


def take_answers(led):
    """人の答え（data/答え/*.json・Claude Code が書く。設計書 5章）を取り込む：
    {"種類": "仕入れた", "SKU": …, "仕入値": 円(任意), "仕入先": 名前(任意)} → 古物台帳（data/古物台帳/年月.csv）に1行
    {"種類": "発送した", "SKU": …, "台帳の状態": "出品中"|"終了"} → 台帳の状態を直す
    取り込んだファイルは data/答え/取り込み済み/ へ。注文番号は SKU から（記録の中だけで）引く"""
    import csv, glob, shutil
    d = os.path.join(ROOT, "data", "答え")
    rows, notes = [], []
    for f in sorted(glob.glob(os.path.join(d, "*.json"))):
        a = load_json(f, {})
        sku = str(a.get("SKU", ""))
        r = led.get(sku)
        kind = a.get("種類", "")
        if kind in ("仕入元を見た",):   # 在庫の監視が取り込む
            continue
        if kind == "仕入れた" and r:
            ym = now().strftime("%Y%m")
            fp = os.path.join(ROOT, "data", "古物台帳", ym + ".csv")
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            new = not os.path.exists(fp)
            with open(fp, "a", encoding="utf-8", newline="") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["取引の日", "区分", "品目", "数量", "代価(円)", "相手方（仕入先）", "仕入先URL", "SKU"])
                w.writerow([jst()[:10], "仕入れ", (r.get("タイトル") or "")[:80], 1, a.get("仕入値") or r.get("仕入値(円)", ""),
                            a.get("仕入先") or "", r.get("仕入元URL", ""), sku])
            notes.append("古物台帳に記帳 %s" % sku)
        elif kind == "発送した" and r and a.get("台帳の状態") in ("出品中", "終了"):
            rows.append({"SKU": sku, "状態": a["台帳の状態"]})
            notes.append("%s を %s に" % (sku, a["台帳の状態"]))
        else:
            notes.append("取り込めない答え：%s" % os.path.basename(f))
            continue
        os.makedirs(os.path.join(d, "取り込み済み"), exist_ok=True)
        shutil.move(f, os.path.join(d, "取り込み済み", os.path.basename(f)))
    if rows:
        save_ledger(rows, ["状態"], NAME)
    return notes


def main():
    tt = timetable(NAME)
    eb = Ebay()
    mark_started(NAME)
    if not eb.ready():
        notify_once_a_day("鍵なし_受注", "【受注の通知】GitHub に eBay の鍵が無いので、何もしていません")
        write_run(NAME, False, 0, 1)
        return 0
    st_p = os.path.join(ROOT, "data", "受注の通知", "始めた日時.json")
    st = load_json(st_p, {})
    first = not st
    if first:
        st = {"始めた日時_UTC": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"), "JST": jst()}
        save_json(st_p, st)
    sent_p = os.path.join(ROOT, "data", "受注の通知", "通知済み.json")
    sent = load_json(sent_p, {})
    since = (dt.datetime.utcnow() - dt.timedelta(days=int(tt.get("見る日数", 3)))).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    try:
        orders = orders_since(eb, since)
    except EbayError as e:
        notify("【受注の通知】注文を読めませんでした：" + err_text(e)[:300])
        write_run(NAME, False, 0, 1)
        return 1
    led = {r["SKU"]: r for r in read_ledger()}
    ans = take_answers(led)
    if ans:
        notify("【答えを取り込んだ】" + "・".join(ans[:20]))
        led = {r["SKU"]: r for r in read_ledger()}
    new, before_unshipped, rows = [], [], []
    for o in orders:
        if o.get("orderPaymentStatus") != "PAID" or (o.get("cancelStatus") or {}).get("cancelState") == "CANCELED":
            continue
        for li in o.get("lineItems", []):
            key = h(o.get("orderId", "") + "|" + li.get("lineItemId", ""))
            if key in sent:
                continue
            sku = li.get("sku") or ""
            item = {"SKU": sku, "出品ID": li.get("legacyItemId", ""), "数": li.get("quantity", 1),
                    "売値": (li.get("total") or li.get("lineItemCost") or {}).get("value", ""), "注文の時刻_UTC": o.get("creationDate", "")}
            if o.get("creationDate", "") < st["始めた日時_UTC"]:
                if o.get("orderFulfillmentStatus") != "FULFILLED":
                    before_unshipped.append(item)
                sent[key] = jst()
                continue
            new.append(item)
            # 記録（プログラムだけが使う。買い手の欄は入れない）
            save_json(os.path.join(ROOT, "data", "注文の記録", now().strftime("%Y%m%d") + "_" + key + ".json"),
                      dict(item, 注文番号=o.get("orderId", ""), 明細番号=li.get("lineItemId", "")))
            r = led.get(sku)
            if r and r.get("状態") in ("出品中", "在庫ゼロ"):
                rows.append({"SKU": sku, "状態": "売れた"})
            sent[key] = jst()
    if rows:
        save_ledger(rows, ["状態"], NAME)
    if new:   # 11/24 08:54 オーナー「1〜3やって」：売れたらすぐ仕入れ先を見る（在庫の監視・メルカリの見回りをすぐ動かす）
        qp = os.path.join(ROOT, "data", "判定", "売れたらすぐ見る.json")
        q = load_json(qp, {"待ち": []})
        q["待ち"] = list(dict.fromkeys(q.get("待ち", []) + [it["SKU"] for it in new if it["SKU"]]))
        save_json(qp, q)
        if os.environ.get("RUNNER_TEMP"):
            open(os.path.join(os.environ["RUNNER_TEMP"], "new_sold"), "w").write("1")
    msgs = []
    for it in new:
        r = led.get(it["SKU"]) or {}
        msgs.append("【売れた】%s %s\n%s\n売値 $%s・仕入値 %s円\n仕入元：%s\n%s\n→ すぐ仕入れて、仕入れたら「%s 仕入れた」と Claude に" % (
            jst(), it["SKU"] or "(SKUなし・GASの出品)", (r.get("タイトル") or "")[:80], it["売値"], r.get("仕入値(円)", "?"),
            r.get("仕入元URL") or "（台帳に無い：GASのシートの出品一覧を見てください）", hand_links(r.get("タイトル")), it["SKU"] or "出品ID " + str(it["出品ID"])))
    if first and before_unshipped and not st.get("前からの未発送を知らせた"):
        msgs.append("【受注の通知を始めました】始める前から「支払い済み・まだ発送していない」注文 %d件（SKU）：%s\n台帳を「売れた」にするか教えてください" % (
            len(before_unshipped), "・".join(x["SKU"] or "出品ID " + str(x["出品ID"]) for x in before_unshipped[:30])))
        st["前からの未発送を知らせた"] = jst()
        save_json(st_p, st)
    # 見張り：朝の報告が止まっていないか
    mr = load_json(os.path.join(ROOT, "時刻表.json"), {}).get("プログラム", {}).get("朝の報告", {})
    if mr.get("導入済み"):
        rec = load_json(os.path.join(ROOT, "data", "実行記録", "朝の報告.json"), {})
        try:
            last = dt.datetime.strptime(rec.get("最後に動いた時刻JST", ""), "%Y-%m-%d %H:%M").replace(tzinfo=now().tzinfo)
            if (now() - last).total_seconds() > 26 * 3600:
                notify_once_a_day("朝の報告が止まった", "【見張り】朝の報告が26時間以上動いていません")
        except Exception:
            pass
    for m in msgs:   # 知らせに失敗したら例外 → この回は失敗（通知済みにしない）
        notify(m)
    save_json(sent_p, sent)
    print("【受注の通知】%s 新しい注文 %d品・台帳を売れたに %d品%s" % (jst(), len(new), len(rows), "（初回：前からの未発送 %d件）" % len(before_unshipped) if first else ""))
    write_run(NAME, True, len(new), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
