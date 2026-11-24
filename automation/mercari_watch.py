"""メルカリの在庫の見回り（GitHub の中のブラウザ・Playwright で表示してから読む）。
11/24 08:41 オーナー「AとC」（規約は承知済み）。11/24 08:48 の試しで、在庫あり2品・在庫なし2品を正しく見分けた。
- 出品中で仕入元が jp.mercari.com/item/ の品を、最後に仕入元を確認した日時が古い順に、1回 時刻表 メルカリの見回り → 1回の上限_件（はじめ30）まで見る。
- 品と品の間は 20〜35秒 あける（人の速さ）。ロボットの確認・アクセス制限の画面が出たら、その場でやめる。
- 「売り切れました」「削除されています」「見つかりません」→ ない／「購入手続きへ」→ ある／どちらも無い → 読めない（答えを書かない）。
- 答えは data/答え/（日時）_仕入元を見た_（SKU）.json（在庫の監視が取り込む・オーナーの人の答えと同じ形）。結果は data/判定/メルカリの見回り.json"""
import json, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, now, save_json, read_ledger, timetable, notify

tt = timetable("メルカリの見回り") or {}
SITE_RX = re.compile(r"jp\.mercari\.com/item/|item\.fril\.jp/")   # 11/24 09:01 オーナー「楽天ラクマ…仕入れ先入れて」：ラクマ（GitHub から読める）も同じブラウザで見る
if tt.get("実行") is False:
    print("止めている")
    sys.exit(0)
n_max = int(tt.get("1回の上限_件", 40))
gap = tt.get("品の間_秒", [15, 25])
led = read_ledger()
# 11/24 08:54 オーナー「1〜3やって」：③ 見る順番を賢く。売れた品（売れたらすぐ見る）→ 見てから時間がたった品。
# 安い品（売れやすい）は 安い品の間隔_時間 ごと、ほかは ふつうの間隔_時間、出品から30日を超えた品は 古い品の間隔_時間 ごと
from common import load_json, num
import datetime as _dt
qp = os.path.join(ROOT, "data", "判定", "売れたらすぐ見る.json")
sold_q = load_json(qp, {"待ち": []}).get("待ち", [])
sold_rows = [r for r in led if r["SKU"] in sold_q and SITE_RX.search(r.get("仕入元URL") or "")]
def due(r):
    last = r.get("最後に仕入元を確認した日時") or ""
    try:
        t = _dt.datetime.strptime(last[:16], "%Y-%m-%d %H:%M")
    except Exception:
        try:
            t = _dt.datetime.strptime(last[:16], "%Y/%m/%d %H:%M")
        except Exception:
            return 1e9
    age_h = (_dt.datetime.utcnow() + _dt.timedelta(hours=9) - t).total_seconds() / 3600
    iv = float(tt.get("ふつうの間隔_時間", 8))
    if (num(r.get("売値(ドル)")) or 0) < float(tt.get("安い品の線_ドル", 200)):
        iv = float(tt.get("安い品の間隔_時間", 4))
    try:
        if (_dt.date.today() - _dt.date.fromisoformat((r.get("出品日") or "")[:10].replace("/", "-"))).days > 30:
            iv = float(tt.get("古い品の間隔_時間", 24))
    except Exception:
        pass
    return age_h / iv   # 1 以上なら見る時期
live = [r for r in led if r.get("状態") == "出品中" and SITE_RX.search(r.get("仕入元URL") or "")]
live = sorted([r for r in live if due(r) >= 1], key=lambda r: -due(r))
rows = (sold_rows + live)[:n_max]
out = {"時刻": jst(), "ある": [], "ない": [], "読めない": [], "止めた": ""}
if rows:
    from playwright.sync_api import sync_playwright
    ans_dir = os.path.join(ROOT, "data", "答え")
    os.makedirs(ans_dir, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(locale="ja-JP", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36")
        for i, r in enumerate(rows):
            if i:
                time.sleep(random.uniform(float(gap[0]), float(gap[1])))
            url = r["仕入元URL"].split("?")[0]
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                pg.wait_for_timeout(8000)
                txt = pg.inner_text("body")[:30000]
            except Exception as e:
                out["読めない"].append({"SKU": r["SKU"], "理由": str(e)[:150]})
                continue
            if re.search(r"ロボットではありません|captcha|アクセスが集中|アクセスを制限|しばらくしてから", txt, re.I):
                out["止めた"] = "ロボットの確認・アクセス制限の画面（%s）" % r["SKU"]
                break
            if "fril.jp" in url:   # ラクマ：売り切れは「SOLD OUT」、販売中は「購入に進む」（11/24 09:04 の試し）
                if re.search(r"SOLD ?OUT", txt[:4000]) or re.search(r"削除されました|ページが見つかりません|存在しません", txt):
                    res = "ない"
                elif "購入に進む" in txt:
                    res = "ある"
                else:
                    out["読めない"].append({"SKU": r["SKU"], "理由": "ラクマ：印が無い"})
                    continue
            elif re.search(r"売り切れました|削除されています|ページが見つかりません|見つかりませんでした", txt):
                res = "ない"
            elif "購入手続きへ" in txt:
                res = "ある"
            else:
                out["読めない"].append({"SKU": r["SKU"], "理由": "印が無い：" + txt[:80].replace("\n", " ")})
                continue
            out[res].append(r["SKU"])
            if r["SKU"] in sold_q:
                out.setdefault("売れた品", []).append({"SKU": r["SKU"], "結果": res})
            stamp = now().strftime("%Y%m%d_%H%M%S")
            with open(os.path.join(ans_dir, "%s_仕入元を見た_%s.json" % (stamp, r["SKU"])), "w", encoding="utf-8") as f:
                json.dump({"種類": "仕入元を見た", "SKU": r["SKU"], "結果": res, "見た日時": jst(), "見方": "GitHubのブラウザ"}, f, ensure_ascii=False)
        b.close()
save_json(os.path.join(ROOT, "data", "判定", "メルカリの見回り.json"), out)
done_sold = {x["SKU"] for x in out.get("売れた品", [])}
if done_sold:
    from common import save_json as _sj
    q = load_json(qp, {"待ち": []})
    q["待ち"] = [s for s in q.get("待ち", []) if s not in done_sold]
    _sj(qp, q)
    acc = [x["SKU"] for x in out["売れた品"] if x["結果"] == "ない"]
    if acc:
        notify("【メルカリ・事故】売れたのに仕入れ先（メルカリ）が売り切れ：" + ", ".join(acc) + "\n→ ほかで仕入れるか、買い手に連絡してください")
msg = "【メルカリの見回り】%s 見た %d品（ある %d・ない %d・読めない %d）" % (jst(), len(rows), len(out["ある"]), len(out["ない"]), len(out["読めない"]))
if out["ない"]:
    msg += "\n在庫なし（次の在庫の監視で eBay を0に）：" + ", ".join(out["ない"])
if out["止めた"]:
    msg += "\n⛔ 止めた：" + out["止めた"]
if out["ない"] or out["止めた"]:
    notify(msg)
print(msg)
