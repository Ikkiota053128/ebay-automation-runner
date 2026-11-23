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
if tt.get("実行") is False:
    print("止めている")
    sys.exit(0)
n_max = int(tt.get("1回の上限_件", 30))
rows = [r for r in read_ledger() if r.get("状態") == "出品中" and "jp.mercari.com/item/" in (r.get("仕入元URL") or "")]
rows.sort(key=lambda r: r.get("最後に仕入元を確認した日時") or "")
rows = rows[:n_max]
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
                time.sleep(random.uniform(20, 35))
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
            if re.search(r"売り切れました|削除されています|ページが見つかりません|見つかりませんでした", txt):
                res = "ない"
            elif "購入手続きへ" in txt:
                res = "ある"
            else:
                out["読めない"].append({"SKU": r["SKU"], "理由": "印が無い：" + txt[:80].replace("\n", " ")})
                continue
            out[res].append(r["SKU"])
            stamp = now().strftime("%Y%m%d_%H%M%S")
            with open(os.path.join(ans_dir, "%s_仕入元を見た_%s.json" % (stamp, r["SKU"])), "w", encoding="utf-8") as f:
                json.dump({"種類": "仕入元を見た", "SKU": r["SKU"], "結果": res, "見た日時": jst(), "見方": "GitHubのブラウザ"}, f, ensure_ascii=False)
        b.close()
save_json(os.path.join(ROOT, "data", "判定", "メルカリの見回り.json"), out)
msg = "【メルカリの見回り】%s 見た %d品（ある %d・ない %d・読めない %d）" % (jst(), len(rows), len(out["ある"]), len(out["ない"]), len(out["読めない"]))
if out["ない"]:
    msg += "\n在庫なし（次の在庫の監視で eBay を0に）：" + ", ".join(out["ない"])
if out["止めた"]:
    msg += "\n⛔ 止めた：" + out["止めた"]
if out["ない"] or out["止めた"]:
    notify(msg)
print(msg)
