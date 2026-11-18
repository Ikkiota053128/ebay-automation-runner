"""⑥ 朝の報告（毎日 日本時間 9:40）：昨日（米国太平洋時間の1日）の売れた件数・出品の数と上限・止まっているプログラム・気をつけること。

- 売れた件数は data/注文の記録/ から数える（プログラムの中だけで読む。知らせには件数と SKU だけ）。PT の前日 0:00〜23:59 に作られた、支払い済みの注文。
- 止まり判定：時刻表.json の「止まり判定_時間」より、実行記録の「最後に成功した時刻」が古いプログラム（導入済みのものだけ）。
- 出品の上限：data/上限/ の最新・止めている印（data/停止/出品の上限.json）。
- refresh_token の期限：店の設定.json に日付があれば、30日前から知らせる。
"""
import datetime as dt, glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, PT, JST, now, jst, notify, load_json, write_run, mark_started, read_ledger, settings, num, listing_limit_stopped

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
    lines.append("昨日（PT %s）売れた：%d品 %s" % (y.strftime("%m/%d"), len(sold),
                                             ("（" + "・".join(s.get("SKU") or "SKUなし" for s in sold[:15]) + "）") if sold else ""))
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
