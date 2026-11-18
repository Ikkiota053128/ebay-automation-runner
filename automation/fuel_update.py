"""送料の表の更新：FedEx の燃油サーチャージ（公式ページ・日本からの輸出）を読み、data/判定/送料表.json の「燃油」を直す。
読めなかったときは今までの率を使い続け（0%にはしない）、知らせる。率は 20%〜80% の間のときだけ使う"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, jst, notify, load_json, save_json, write_run, mark_started
from stock_watch import fetch

NAME = "送料の表の更新"
URL = "https://www.fedex.com/ja-jp/shipping/surcharges.html"


def main():
    mark_started(NAME)
    p = os.path.join(ROOT, "data", "判定", "送料表.json")
    st = load_json(p, {})
    old = (st.get("FedEx") or {}).get("燃油")
    code, html = fetch(URL)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html or "", flags=re.I)))
    i = text.find("燃油")
    near = text[i: i + 3000] if i >= 0 else ""
    # 「輸出」の行の % を優先。無ければ燃油の近くで最初の % 
    m = re.search(r"輸出[^%]{0,120}?(\d{1,2}(?:\.\d{1,2})?)\s*%", near) or re.search(r"(\d{1,2}(?:\.\d{1,2})?)\s*%", near)
    save_json(os.path.join(ROOT, "data", "送料の表", "FedExのページ.json"), {"時刻": jst(), "HTTP": code, "燃油のあたり": near[:2500]})
    if not m:
        msg = "【送料の表】%s FedEx の燃油サーチャージを公式ページから読めませんでした（HTTP %s）。今までの %.2f%% を使い続けます" % (jst(), code, (old or 0) * 100)
        print(msg)
        notify(msg)
        write_run(NAME, False, 0, 1)
        return 0
    rate = float(m.group(1)) / 100
    if not (0.2 <= rate <= 0.8):
        msg = "【送料の表】%s 読めた率 %.2f%% がおかしいので使いません（今までの %.2f%%）" % (jst(), rate * 100, (old or 0) * 100)
    elif old is None or abs(rate - old) > 1e-6:
        st.setdefault("FedEx", {})["燃油"] = rate
        st["燃油を直した日時"] = jst()
        save_json(p, st)
        msg = "【送料の表】%s FedEx の燃油サーチャージ %.2f%% → %.2f%%（公式ページ）。判定の送料に使います" % (jst(), (old or 0) * 100, rate * 100)
    else:
        msg = "【送料の表】%s FedEx の燃油サーチャージは %.2f%% のまま" % (jst(), rate * 100)
    print(msg)
    notify(msg)
    write_run(NAME, True, 1, 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
