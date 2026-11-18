"""⑥ 朝の報告（毎日 日本時間 9:40）：昨日（米国太平洋時間の1日）の売れた件数・出品の数と上限・止まっているプログラム・気をつけること。

- 売れた件数は data/注文の記録/ から数える（プログラムの中だけで読む。知らせには件数と SKU だけ）。PT の前日 0:00〜23:59 に作られた、支払い済みの注文。
- 止まり判定：時刻表.json の「止まり判定_時間」より、実行記録の「最後に成功した時刻」が古いプログラム（導入済みのものだけ）。
- 出品の上限：data/上限/ の最新・止めている印（data/停止/出品の上限.json）。
- refresh_token の期限：店の設定.json に日付があれば、30日前から知らせる。
"""
import datetime as dt, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, PT, JST, now, jst, notify, load_json, write_run, mark_started, read_ledger, settings, num, listing_limit_stopped, Ebay

NAME = "朝の報告"


def main():
    mark_started(NAME)
    lines = ["【朝の報告】%s" % jst()]
    # 1) 昨日（PT）の売れた件数
    today_pt = now().astimezone(PT).date()
    y = today_pt - dt.timedelta(days=1)
    sold = []
    for f in glob.glob(os.path.join(ROOT, "data", "注文の記録", "*.json")):
        d = load_json(f, {})
        try:
            t = dt.datetime.fromisoformat(d.get("注文の時刻_UTC", "").replace("Z", "+00:00")).astimezone(PT).date()
        except Exception:
            continue
        if t == y:
            sold.append(d)
    # 今月（PT）の売れた数・売上（経理の目安）
    try:
        m_sold = []
        for f in glob.glob(os.path.join(ROOT, "data", "注文の記録", "*.json")):
            dd = load_json(f, {})
            try:
                tt0 = dt.datetime.fromisoformat(dd.get("注文の時刻_UTC", "").replace("Z", "+00:00")).astimezone(PT).date()
            except Exception:
                continue
            ref = y if today_pt.day == 1 else today_pt
            if (tt0.year, tt0.month) == (ref.year, ref.month):
                m_sold.append(dd)
        month_line = "%s月（PT）の売れた数 %d品・売上 $%.2f" % ((y if today_pt.day == 1 else today_pt).month, len(m_sold), sum(num(x.get("売値")) or 0 for x in m_sold))
    except Exception:
        month_line = ""
    lines.append("昨日（PT %s）売れた：%d品 %s" % (y.strftime("%m/%d"), len(sold),
                                             ("（" + "・".join(s.get("SKU") or "SKUなし" for s in sold[:15]) + "）") if sold else ""))
    if month_line:
        lines.append(month_line)
    # 古物台帳の突き合わせ（毎月1日・先月）：売れた品の SKU が古物台帳（仕入れ）に記帳されているか。記帳はプログラムだけ（設計書4章）
    if today_pt.day == 1 or os.environ.get("KOBUTSU_CHECK"):
        try:
            import csv as _csv
            pm = y
            sold_skus = set()
            for f in glob.glob(os.path.join(ROOT, "data", "注文の記録", "*.json")):
                dd = load_json(f, {})
                try:
                    t1 = dt.datetime.fromisoformat(dd.get("注文の時刻_UTC", "").replace("Z", "+00:00")).astimezone(PT).date()
                except Exception:
                    continue
                if (t1.year, t1.month) == (pm.year, pm.month) and dd.get("SKU"):
                    sold_skus.add(dd["SKU"])
            booked = set()
            for f in glob.glob(os.path.join(ROOT, "data", "古物台帳", "*.csv")):
                with open(f, encoding="utf-8") as fh:
                    booked |= {r.get("SKU", "") for r in _csv.DictReader(fh)}
            miss = sorted(sold_skus - booked)
            lines.append("古物台帳の突き合わせ（%d月）：売れた %d品・記帳漏れ %d品%s" % (pm.month, len(sold_skus), len(miss), ("（" + "・".join(miss[:15]) + "）→「SKU 仕入れた」と Claude に") if miss else ""))
        except Exception as e:
            lines.append("（古物台帳の突き合わせができなかった：%s）" % type(e).__name__)
    # 2) 出品の数と上限
    led = read_ledger()
    act = [r for r in led if r.get("状態") == "出品中"]
    tot = sum(num(r.get("売値(ドル)")) or 0 for r in act)
    lim = {}
    fs = sorted(glob.glob(os.path.join(ROOT, "data", "上限", "2*.json")))
    if fs:
        lim = (load_json(fs[-1], {}).get("eBayの返事") or {}).get("sellingLimit") or {}
    amt = num((lim.get("amount") or {}).get("value"))
    lines.append("台帳の出品中：%d品・$%s%s" % (len(act), format(round(tot), ","), "（eBayの月の上限 $%s・%s品）" % (format(int(amt), ","), lim.get("quantity")) if amt else ""))
    ls = listing_limit_stopped()
    if ls:
        lines.append("⚠ eBayの出品の上限で、出品を %s まで止めています（上限を上げてもらったら再開）" % ls["再開してよい時刻"][:10])
    n_sold_wait = sum(1 for r in led if r.get("状態") == "売れた")
    if n_sold_wait:
        lines.append("「売れた」のまま（発送後に 出品中に戻す／終了 を教えてください）：%d品" % n_sold_wait)
    # 2a) メルカリ（機械で見ない仕入元）の見回り：人が、長く見ていない品から1日○品（教科書 第18章）
    try:
        from common import is_target, hand_only, timetable as _tt
        nm = int(_tt(NAME).get("メルカリを人が見る件数_1日", 10))
        mer = sorted([r for r in led if is_target(r) and r.get("状態") in ("出品中", "売れた") and hand_only(r.get("仕入元URL"))],
                     key=lambda r: (r.get("状態") != "売れた", r.get("最後に仕入元を確認した日時", "")))
        if mer:
            lines.append("メルカリ・Amazonの見回り（%d品のうち、長く見ていない%d品）。見たら「SKU ある／ない」と Claude に：" % (len(mer), min(nm, len(mer))))
            lines += ["・%s %s（前に見た：%s）" % (r["SKU"], r.get("仕入元URL"), (r.get("最後に仕入元を確認した日時") or "まだ")[:10]) for r in mer[:nm]]
    except Exception as e:
        lines.append("（メルカリの見回りの一覧を作れなかった：%s）" % type(e).__name__)
    # 2b) 昨日の売上・利益（台帳の仕入値・送料・手数料から。買い手の情報は使わない）
    try:
        by = {r["SKU"]: r for r in led}
        sales = profit = 0.0
        for d in sold:
            r = by.get(d.get("SKU") or "")
            usd = num(d.get("売値")) or 0
            sales += usd
            if r:
                fx = num(r.get("為替")) or 152
                k = (num(r.get("手数料率")) or 0.1742) + (num(r.get("関税率")) or 0.15)
                profit += usd * fx * (1 - k) - (num(r.get("仕入値(円)")) or 0) - (num(r.get("国内送料(円)")) or 0) - (num(r.get("出品時の海外送料(円)")) or 0) - (num(r.get("固定費(円)")) or 0)
        if sold:
            lines.append("昨日の売上 $%.2f・見込みの利益 %s円（台帳の値で計算）" % (sales, format(round(profit), ",")))
    except Exception:
        pass
    # 2c) eBay のメッセージ（件数だけ。中身・買い手の名前は読まない）
    try:
        eb = Ebay()
        if eb.ready():
            x = eb.trading("GetMyMessages", "<DetailLevel>ReturnSummary</DetailLevel>")
            import re as _re
            nu = _re.search(r"<NewMessageCount>(\d+)</NewMessageCount>", x)
            fl = _re.search(r"<FlaggedMessageCount>(\d+)</FlaggedMessageCount>", x)
            if nu:
                lines.append("eBayの未読メッセージ：%s件%s（返事はあなたが Seller Hub で）" % (nu.group(1), "・旗つき %s件" % fl.group(1) if fl else ""))
    except Exception as e:
        lines.append("（メッセージの件数を読めなかった：%s）" % type(e).__name__)
    # 2d) 配送ポリシーの点検（GAS の policyAudit の代わり）：GitHub で使う配送ポリシーが、アメリカに送れる設定か（オーナー「アメリカは絶対外さないで」）
    try:
        eb2 = Ebay()
        if eb2.ready():
            pol_ids = {"327189638011", "324953444011", "324953445011", "326778157011", "326770233011"}
            _, pj = eb2.call("GET", "/sell/account/v1/fulfillment_policy?marketplace_id=EBAY_US")
            badp = []
            for fp in pj.get("fulfillmentPolicies", []):
                if str(fp.get("fulfillmentPolicyId")) not in pol_ids:
                    continue
                ex = [x.get("regionName", "") for x in (fp.get("shipToLocations") or {}).get("regionExcluded", []) or []]
                if any(e in ("US", "United States", "UNITED_STATES") for e in ex):
                    badp.append("%s（%s）" % (fp.get("name", ""), fp.get("fulfillmentPolicyId")))
            lines.append("配送ポリシー：" + ("⚠ アメリカが外れている：" + "・".join(badp) if badp else "アメリカに送れる（%d個を確かめた）" % len([f for f in pj.get("fulfillmentPolicies", []) if str(f.get("fulfillmentPolicyId")) in pol_ids])))
    except Exception as e:
        lines.append("（配送ポリシーを読めなかった：%s）" % type(e).__name__)
    # 3) 止まっているプログラム
    tt = load_json(os.path.join(ROOT, "時刻表.json"), {}).get("プログラム", {})
    stop = []
    for name, v in tt.items():
        if not v.get("導入済み") or name == NAME or not v.get("止まり判定_時間"):
            continue
        fname = {"フリマ新着の地引網": "flea_sweep"}.get(name, name)
        rec = load_json(os.path.join(ROOT, "data", "実行記録", fname + ".json"), {})
        last = rec.get("最後に成功した時刻JST") or rec.get("最後に成功した時刻") or ""
        try:
            age = (now() - dt.datetime.strptime(last[:16], "%Y-%m-%d %H:%M").replace(tzinfo=JST)).total_seconds() / 3600
        except Exception:
            age = None
        if age is None or age > float(v["止まり判定_時間"]):
            stop.append("%s（最後に成功：%s）" % (name, last or "記録なし"))
    lines.append("止まっているプログラム：" + ("・".join(stop) if stop else "なし"))
    # 4) refresh_token の期限
    tok = settings().get("トークン", {})
    try:
        exp = dt.date.fromisoformat(str(tok.get("refresh_tokenの期限の日", ""))[:10])
        left = (exp - now().date()).days
        if left <= 30:
            lines.append("⚠ eBay の refresh_token の期限まで あと%d日（%s）。取り直してください" % (left, exp))
    except Exception:
        lines.append("（refresh_token の期限の日が 店の設定.json に書かれていません）")
    msg = "\n".join(lines)
    print(msg)
    notify(msg)
    write_run(NAME, True, len(sold), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
