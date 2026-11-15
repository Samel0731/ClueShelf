# Search evaluation

60 golden saves, 20 queries, k=5. Source text only; no AI summary or tags are indexed.

Embedding model: `intfloat/multilingual-e5-small` @ `614241f6` (ONNX, CPU).

| Mode | Hit@5 | Recall@5 | MRR | p50 ms | p95 ms |
|---|---|---|---|---|---|
| keyword | 40.0% | 30.0% | 0.400 | 2.2 | 4.5 |
| semantic | 100.0% | 94.2% | 1.000 | 32.1 | 33.7 |
| hybrid | 100.0% | 94.2% | 1.000 | 32.7 | 33.9 |

Rank of the first relevant save per query (– = not returned):

| Query | Kind | keyword | semantic | hybrid |
|---|---|---|---|---|
| 拉麵 | exact | 1 | 1 | 1 |
| 台中 生魚片 | exact | 1 | 1 | 1 |
| 冷凍備餐料理 | cross-lingual | – | 1 | 1 |
| 大阪燒肉 | cross-lingual | – | 1 | 1 |
| 京都賞楓 | cross-lingual | – | 1 | 1 |
| 首爾咖啡廳 | exact | 1 | 1 | 1 |
| 韓國自由行 | paraphrase | – | 1 | 1 |
| MLOps | exact | 1 | 1 | 1 |
| 本地 RAG | exact | 1 | 1 | 1 |
| 面試準備 | paraphrase | – | 1 | 1 |
| 履歷 | exact | 1 | 1 | 1 |
| 日文文法 | cross-lingual | – | 1 | 1 |
| 韓文聽力 | exact | – | 1 | 1 |
| 演唱會 | exact | 1 | 1 | 1 |
| 電鍋料理 | paraphrase | – | 1 | 1 |
| 高蛋白便當 | paraphrase | – | 1 | 1 |
| 沖繩自駕 | exact | 1 | 1 | 1 |
| 市集活動 | paraphrase | – | 1 | 1 |
| 東京 一個人吃飯 | paraphrase | – | 1 | 1 |
| 北海道景點 | cross-lingual | – | 1 | 1 |
