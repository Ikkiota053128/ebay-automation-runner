"""規約の点検（GAS の IPリスク監査と同じ辞書・月1回）：出品中の品のタイトルを data/判定/IPの辞書.json で照らし、
「出品しない」「要確認」の言葉がある品を知らせる（読むだけ・終えるのはオーナーの承認のあと）"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, notify, load_json, save_json, read_ledger, write_run, mark_started

NAME = "規約の点検"


def check(title, words):
    t = str(title or "").lower()
    hits = [w for w in words if re.search(r"(?<![a-z])" + re.escape(w["言葉"].lower()) + r"(?![a-z])", t)]
    order = ["出品しない", "要確認（自動では出品しない）", "注意（条件つきで出品可）"]
    return sorted(hits, key=lambda w: order.index(w["段階"]) if w["段階"] in order else 9)


def main():
    mark_started(NAME)
    words = load_json(os.path.join(ROOT, "data", "判定", "IPの辞書.json"), [])
    rows = [r for r in read_ledger() if r.get("状態") == "出品中"]
    out = []
    for r in rows:
        h = check(r.get("タイトル"), words)
        if h and h[0]["段階"] != "注意（条件つきで出品可）":
            out.append({"SKU": r["SKU"], "出品ID": r.get("eBayの出品ID"), "タイトル": r.get("タイトル", "")[:80], "段階": h[0]["段階"], "言葉": [x["言葉"] for x in h]})
    save_json(os.path.join(ROOT, "data", "規約の点検", jst()[:7] + ".json"), {"時刻": jst(), "見た": len(rows), "見つかった": out})
    ng = sum(1 for x in out if x["段階"] == "出品しない")
    msg = "【規約の点検】%s 出品中 %d品を辞書（%d語）で見た → 出品しない言葉 %d品・要確認 %d品%s" % (
        jst(), len(rows), len(words), ng, len(out) - ng, ("：" + "・".join("%s(%s)" % (x["SKU"], "/".join(x["言葉"][:2])) for x in out[:15])) if out else "")
    print(msg)
    notify(msg)
    write_run(NAME, True, len(out), 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
