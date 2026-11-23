"""予備の仕入れ先に付け替えた品を、元の仕入れ先・元の仕入値に戻す（手で動かす）。
11/24 06:48 オーナー「至急1〜4やって」：在庫の監視の付け替えが、香水（1,540円）を BOSS SP-1（69,900円）とまちがえ、値段が $858.99→$85.44 まで下がって売れた事故。
- メモの「予備の仕入れ先に付け替え（前：URL 円）」のうち、いちばん最初の（前：…）を元の仕入れ先として戻す。
- 戻したあとは、在庫の監視が元の仕入れ先を見る（売り切れなら在庫0）。値段は値段の調整が赤字の品を最低利益まで上げる。
- data/判定/仕入れ先の戻し.json：{"本番": false}。結果は data/判定/仕入れ先の戻し_結果.json"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, load_json, save_json, read_ledger, save_ledger

P = os.path.join(ROOT, "data", "判定", "仕入れ先の戻し.json")
RP = os.path.join(ROOT, "data", "判定", "仕入れ先の戻し_結果.json")
RX = re.compile(r"予備の仕入れ先に付け替え（前：(\S+) (\d+)円）")
cfg = load_json(P, {"本番": False})
live = bool(cfg.get("本番"))
rows = read_ledger()
out = {"時刻": jst(), "本番": live, "戻した": []}
ch = []
for r in rows:
    m = RX.search(r.get("メモ") or "")
    if not m:
        continue
    url, cost = m.group(1), m.group(2)
    out["戻した"].append({"SKU": r["SKU"], "状態": r.get("状態"), "売値": r.get("売値(ドル)"), "今": [r.get("仕入元URL"), r.get("仕入値(円)")], "元": [url, cost]})
    r["仕入元URL"], r["仕入値(円)"] = url, cost
    r["メモ"] = ((r.get("メモ") or "").replace("予備の仕入れ先に付け替え（前：", "予備の付け替え（取り消し済み・前：") + "・%s 元の仕入れ先に戻した" % jst())[:500]
    ch.append(r)
if live and ch:
    save_ledger(ch, ["仕入元URL", "仕入値(円)", "メモ"], "仕入れ先の戻し")
    cfg["本番"] = False
    save_json(P, cfg)
save_json(RP, out)
print("本番" if live else "ドライラン", "戻した", len(out["戻した"]))
