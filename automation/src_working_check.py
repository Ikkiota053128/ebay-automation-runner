"""出品中で、まだタイトルに Tested Working が無い品の仕入れ先を読み直し、仕入れ先が「動作確認済み」と書いているかを数える（読むだけ）。
11/28 10:10 オーナー「GASの頃に出した品は…本当は動作確認済みでも数に入っていない品があるかもしれません。ここ確認できないか調べて」
- 仕入れ先の説明：cond_note.source_text（楽天は公式APIの itemCaption、ほかは商品ページ。メルカリ・Amazon・ラクマはここでは読めない）。
- 見分け：cond_note.notes の func が Reported working（ジャンク・動作未確認は外す）。
- 結果は data/判定/動作確認済みの読み直し.json。eBay は変えない。"""
import collections, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, read_ledger, save_json
import cond_note

def src_of(u):
    for k, n in [("paypayfleamarket", "Yahoo!フリマ"), ("auctions.yahoo", "ヤフオク"), ("rakuten", "楽天"), ("shopping.yahoo", "Yahoo!ショッピング"),
                 ("mercari", "メルカリ"), ("fril", "ラクマ"), ("amazon", "Amazon")]:
        if k in (u or ""):
            return n
    return "店ほか" if u else "仕入元URLなし"

rows = [r for r in read_ledger() if r.get("状態") == "出品中" and r.get("offerId") and not r["SKU"].startswith("STK-")
        and not re.search(r"\btested\b|\bworking\b", r.get("タイトル") or "", re.I)]
out = {"時刻": jst(), "見た": 0, "仕入れ先ごと": {}, "動作確認済み": [], "読めない理由": collections.Counter()}
cnt = collections.defaultdict(lambda: collections.Counter())
t_end = time.time() + 50 * 60
for r in rows:
    if time.time() > t_end:
        break
    u, s = r.get("仕入元URL") or "", src_of(r.get("仕入元URL"))
    out["見た"] += 1
    cnt[s]["品"] += 1
    if s in ("メルカリ", "Amazon", "ラクマ", "仕入元URLなし"):
        cnt[s]["ここでは読めない"] += 1
        continue
    txt = cond_note.source_text({"url": u})
    time.sleep(1.5 if s == "楽天" else 3)
    if not txt:
        cnt[s]["読めない（売り切れ・消えた・ページの形）"] += 1
        continue
    cnt[s]["読めた"] += 1
    cn = cond_note.notes(txt, "")
    if (cn.get("func") or "").startswith("Reported working") and not re.search(r"ジャンク|部品取り|動作未確認", txt[:300]):
        cnt[s]["動作確認済み"] += 1
        out["動作確認済み"].append({"SKU": r["SKU"], "仕入れ先": s, "タイトル": r.get("タイトル"), "出品日": r.get("出品日") or "（GASの頃）"})
out["仕入れ先ごと"] = {k: dict(v) for k, v in cnt.items()}
out["読めない理由"] = dict(out["読めない理由"])
save_json(os.path.join(ROOT, "data", "判定", "動作確認済みの読み直し.json"), out)
print("見た", out["見た"], "動作確認済み", len(out["動作確認済み"]), out["仕入れ先ごと"])
