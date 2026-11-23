"""新しいタイトルの見本（読むだけ・eBay は変えない）。11/23 19:26 オーナー「OK」：直近に出した品で、前と後のタイトルを20品。
判定の記録で「出品」になった品の 仕入元の商品名・型番・種類 から、仕入れ先の説明を読み（cond_note）、新しいタイトルを作って並べる。
結果は data/判定/タイトルの見本.json。"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, load_json, save_json, read_ledger
import cond_note, title_make
from judge_list import brand_of

kinds = load_json(os.path.join(ROOT, "data", "判定", "種類.json"), {})
led = {r["SKU"]: r for r in read_ledger()}
rows = []
for f in sorted(glob.glob(os.path.join(ROOT, "data", "判定", "記録", "2026112*_*.json")), reverse=True):
    for r in json.load(open(f, encoding="utf-8")).get("結果", []):
        if r.get("結論") == "GO" and r.get("SKU") in led and led[r["SKU"]].get("状態") == "出品中":
            rows.append(r)
    if len(rows) >= 20:
        break
out = {"時刻": jst(), "品": []}
for r in rows[:20]:
    l = led[r["SKU"]]
    kind = kinds.get(str(r.get("カテゴリ"))) or {}
    c = {"url": r["url"], "id": r["id"], "title": r.get("仕入元の商品名", "")}
    src = cond_note.source_text(c)
    cn = cond_note.notes(src, c["title"])
    brand = (l.get("タイトル") or "").split(" ")[0]
    cond = 1000 if " New " in " %s " % (l.get("タイトル") or "") else 3000
    new = title_make.build(brand, r["型番"], kind.get("言葉", ""), cond, cn, src + c["title"])
    out["品"].append({"SKU": r["SKU"], "前": l.get("タイトル"), "後": new, "文字数": [len(l.get("タイトル") or ""), len(new)],
                     "型番が合う": title_make.check_model(r["型番"], c["title"], src), "仕入元の商品名": c["title"], "拾えた状態": cn})
save_json(os.path.join(ROOT, "data", "判定", "タイトルの見本.json"), out)
print(len(out["品"]))
