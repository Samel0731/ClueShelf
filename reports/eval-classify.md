# Classification evaluation

Prompt `classify-v1`, 60 golden saves. Primary accuracy = the expected main topic is among the predicted topics. Failed calls count as wrong.

| Model | Primary acc. | Exact set | Micro F1 | Failures | p50 s | p95 s |
|---|---|---|---|---|---|---|
| qwen3:4b | 80.0% | 75.0% | 0.816 | 1/60 | 1.49 | 1.93 |

## qwen3:4b

| Topic | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| 其他 | 0.0% | 0.0% | 0.000 | 5 |
| 旅遊 | 84.6% | 91.7% | 0.880 | 12 |
| 求職 | 71.4% | 100.0% | 0.833 | 5 |
| 活動 | 75.0% | 50.0% | 0.600 | 6 |
| 程式 | 85.7% | 75.0% | 0.800 | 8 |
| 語言學習 | 100.0% | 100.0% | 1.000 | 5 |
| 音樂 | 100.0% | 100.0% | 1.000 | 7 |
| 食譜 | 77.8% | 87.5% | 0.824 | 8 |
| 餐廳 | 100.0% | 70.0% | 0.824 | 10 |

Missed primary topic:

- `y01` expected ['食譜'], got call failed
- `y03` expected ['餐廳', '旅遊'], got ['旅遊']
- `y16` expected ['活動', '音樂'], got ['音樂']
- `y17` expected ['其他'], got ['食譜']
- `y18` expected ['其他'], got ['求職']
- `i03` expected ['餐廳'], got ['食譜']
- `i04` expected ['餐廳', '旅遊'], got ['旅遊']
- `i15` expected ['活動'], got ['旅遊']
- `i19` expected ['其他'], got ['活動']
- `t15` expected ['活動'], got ['旅遊']
- `t17` expected ['其他'], got ['程式']
- `t18` expected ['其他'], got ['求職']
