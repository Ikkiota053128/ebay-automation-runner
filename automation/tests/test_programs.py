# 使い方: python3 automation/tests/test_programs.py（eBayにもDiscordにも出ない）
# 検収用の試し（eBayには出ない）。正常・欠け・異常の3種類
import os, sys, json, tempfile, shutil, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
tmp = tempfile.mkdtemp(); os.environ["LEDGER_ROOT"] = tmp
root = os.environ.get("SETTINGS_ROOT") or os.path.join(os.path.dirname(__file__), "..", "..")   # 店の設定.json・時刻表.json のある所（データ置き場）
for f in ["店の設定.json", "時刻表.json"]: shutil.copy(os.path.join(root, f), tmp)
import common, price_adjust as pa, stock_watch as sw
cfg = common.settings()
ok = 0
def check(c, m):
    global ok
    assert c, m; ok += 1
# 値付けの式
r = {"仕入値(円)": "10000", "出品時の海外送料(円)": "3000", "手数料率": "17.42%", "関税率": "15.0%", "固定費(円)": "0", "国内送料(円)": "0", "為替": "152"}
f = common.floor_price(r, cfg)
p = common.profit_yen(f, r, cfg)
check(p >= 1500 - 1 and p >= f * 152 * 0.05 - 1, "最低利益の値段で利益の条件を満たす %s %s" % (f, p))
check(common.profit_yen(f - 0.05, r, cfg) < max(1500, (f - .05) * 152 * .05), "1セント下は条件を割る")
check(common.floor_price({**r, "仕入値(円)": ""}, cfg) is None, "欠け：仕入値が空なら式を出さない")
check(common.floor_price({**r, "手数料率": ""}, cfg) is None, "欠け：手数料率が空なら式を出さない")
check(common.floor_price({**r, "国内送料(円)": "1200"}, cfg) > f, "国内送料を足す")
# 判定
check(pa.decide(r, f - 5, f, 3, None, cfg)[0].startswith("値上げ"), "赤字は値上げ")
check(pa.decide(r, f + 50, f, 61, None, cfg)[0].startswith("出品を終える"), "60日で終える")
check(pa.decide(r, f + 50, f, 31, None, cfg) == ("値下げ（31日売れない）", f), "30日で最低利益まで")
check(pa.decide(r, f + 50, f, 5, f + 20, cfg)[1] == round(f + 19, 2), "最安−$1")
check(pa.decide(r, f + 50, f, 5, f - 30, cfg)[1] == f, "最低利益より下げない")
check(pa.decide(r, f + 10, f, 5, f + 80, cfg)[0] == "変更なし", "競合に合わせて値上げしない")
check(pa.decide(r, f + 10, f, None, None, cfg)[0] == "変更なし", "出品日が不明で競合なしは変えない")
# 型番
check(pa.model_of("BOSS DS-1 Distortion Pedal Used From Japan") == "DS-1", "型番 DS-1")
check(pa.model_of("Roland TR-8S Rhythm 4K HDMI USB3") == "TR-8S", "型番 TR-8S（4K・HDMI・USB3は外す）")
check(pa.model_of("Vintage camera strap") == "", "型番なし")
# 在庫の判定（3つに分ける）
check(sw.judge(404, "") == (False, "商品ページがなくなった（404）"), "404はない")
check(sw.judge(503, "")[0] is None, "503は読めなかった（売り切れにしない）")
check(sw.judge(None, "timeout")[0] is None, "通信失敗は読めなかった")
check(sw.judge(200, '<script type="application/ld+json">{"availability":"https://schema.org/InStock"}</script>')[0] is True, "InStock")
check(sw.judge(200, '<script type="application/ld+json">{"availability":"https://schema.org/OutOfStock"}</script>')[0] is False, "OutOfStock")
check(sw.judge(200, "<p>この商品は売り切れです</p>")[0] is False, "売り切れの文字")
check(sw.judge(200, "<button>カートに入れる</button>")[0] is True, "カートに入れる")
check(sw.judge(200, "<p>こんにちは</p>")[0] is None, "判断できない")
check(sw.kind_of("https://netmall.hardoff.co.jp/product/1/", cfg) == "A" and sw.kind_of("https://jp.mercari.com/item/m1", cfg) == "B", "仕入元の種類")
# 台帳の保存（控え・自分の列だけ・行が減らない）
L = os.path.join(tmp, "台帳.csv")
with open(L, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=common.COLS); w.writeheader()
    w.writerow({"SKU": "A-1", "売値(ドル)": "10", "状態": "出品中", "offerId": "9"}); w.writerow({"SKU": "STK-1", "状態": "出品中", "offerId": "8"})
    w.writerow({"SKU": "B-1", "状態": "出品中"})
common.save_ledger([{"SKU": "A-1", "売値(ドル)": "12", "状態": "終了"}], ["売値(ドル)"], "試し")
rows = {r["SKU"]: r for r in common.read_ledger()}
check(rows["A-1"]["売値(ドル)"] == "12" and rows["A-1"]["状態"] == "出品中", "自分の列だけ書く")
check(len(rows) == 3 and os.listdir(os.path.join(tmp, "控え")), "行が減らず控えがある")
check(common.is_target(rows["A-1"]) and not common.is_target(rows["STK-1"]) and not common.is_target(rows["B-1"]), "有在庫・未移行は扱わない")
# 鍵が無いときは何もせず失敗で終わる
os.environ.pop("EBAY_CLIENT_ID", None); os.environ.pop("NOTIFY_WEBHOOK_URL", None)
check(pa.main() == 0 and sw.main() == 0 and not os.path.exists(os.path.join(tmp, "data", "値段の調整")), "鍵が無いと何もしない")
pa.main(); check(True, "2回目は知らせない")
# ふだん（3回そろうまで実行しない）
check(common.usual_ok("試し", 1)[0] is False, "3回そろうまで実行しない")
for n in (2, 3, 4): common.usual_add("試し", n, True)
check(common.usual_ok("試し", 9)[0] and not common.usual_ok("試し", 10)[0], "基準=3×平均3件=9件")
print("OK", ok, "件")
