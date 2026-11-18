# ebay-automation-runner

eBay の店の自動化プログラム（プログラムだけを置く公開リポジトリ）。

- 台帳・記録・店の設定・時刻表は、非公開のデータ置き場（別のリポジトリ）にあり、ここには置かない。
- 鍵はすべて GitHub の Secrets。コードには書かない。
- 実行ログには中身を出さない（結果はデータ置き場の `data/ログ/` に保存する）。

| プログラム | 中身 |
|---|---|
| `automation/flea_sweep.py` | フリマ新着の地引網 |
| `automation/stock_watch.py` | 在庫の監視（Inventory API） |
| `automation/price_adjust.py` | 値段の調整（Inventory API） |
| `automation/bulk_list.py` | 一括の出品（Inventory API） |
| `automation/migrate.py` | 今の出品の移行（bulkMigrateListing） |

試し方：`SETTINGS_ROOT=<データ置き場> python3 automation/tests/test_programs.py`（eBay にも通知先にも出ない）
