# Classification evaluation

Prompt `classify-v2`, 60 golden saves. Primary accuracy = the expected main topic is among the predicted topics. Failed calls count as wrong.

| Model | Primary acc. | Exact set | Micro F1 | Failures | p50 s | p95 s |
|---|---|---|---|---|---|---|
| qwen3:4b | 93.3% | 83.3% | 0.906 | 1/60 | 1.52 | 1.98 |

## qwen3:4b

| Topic | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| 其他 | 100.0% | 60.0% | 0.750 | 5 |
| 旅遊 | 83.3% | 83.3% | 0.833 | 12 |
| 求職 | 71.4% | 100.0% | 0.833 | 5 |
| 活動 | 100.0% | 83.3% | 0.909 | 6 |
| 程式 | 100.0% | 75.0% | 0.857 | 8 |
| 語言學習 | 100.0% | 100.0% | 1.000 | 5 |
| 音樂 | 100.0% | 100.0% | 1.000 | 7 |
| 食譜 | 100.0% | 87.5% | 0.933 | 8 |
| 餐廳 | 100.0% | 100.0% | 1.000 | 10 |

Missed primary topic:

- `y01` expected ['食譜'], got call failed
- `y16` expected ['活動', '音樂'], got ['音樂']
- `y18` expected ['其他'], got ['求職']
- `t17` expected ['其他'], got ['求職']
