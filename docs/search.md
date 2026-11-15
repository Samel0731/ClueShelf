# 分類與搜尋

## 資料組織

Save 保存 nullable manual_topics/manual_tags。null 使用 AI 分類，空陣列代表使用者明確清空。API 回傳 effective_topics/effective_tags 作為篩選與介面的單一來源。人工分類更新具版本檢查，處理中的收藏須先等工作完成。

SearchChunk 保存可追溯欄位、原文分段、NFKC 與小寫的搜尋文字、內容指紋、模型名稱、向量與索引嘗試次數。長文以 400 字分段、80 字重疊。來源包括顯示標題、平台原標題、有效作者內文、不同的原始內文、目前有效的摘要、有效分類及 Threads 留言。

來源保存、人工修改、分類修改和標題切換都在同一交易同步索引。未變片段保留原向量，變更與刪除片段移除舊向量。刪除原收藏時，重新同步因外鍵 SET NULL 而恢復為獨立收藏的草稿。

## 三種搜尋

- 關鍵字：SQLite FTS5 trigram 比對三字以上詞彙，一至二字詞用參數化子字串查詢。查詢視為字面內容，不執行 FTS 操作符；空白分隔詞彙須全部命中，可分散在不同欄位。主題和標籤亦採全部符合。
- 語意：官方 intfloat/multilingual-e5-small，固定 revision 614241f622f53c4eeff9890bdc4f31cfecc418b3。ONNX CPU 推論、384 維、平均池化與正規化、query/passage 前綴、最多 512 token。
- 智慧：關鍵字與語意各自排序，再以 RRF 合併。同一收藏只出現一次。語意排名不是信心百分比，尚未建立代表性資料集來校準相關性門檻。

所有檢索先依 owner、平台、有效主題及標籤限制候選，排除指向原收藏的重複草稿。命中片段優先顯示原始文字證據，再考慮生成標籤。留言片段保留 source ID 並在畫面標示 Threads 留言。

## 背景索引與降級

沒有 embedding_model 的片段就是持久化待處理佇列。worker 每次最多取八筆，以 CPU 在交易外推論，再用片段 ID、收藏 ID、內容指紋檢查後提交。刪除或變更期間產生的舊向量不會寫回新內容。

模型未安裝時不消耗索引嘗試次數。推論失敗最多三次，之後顯示失敗計數，不再假裝準備中；使用者可按「更新搜尋資料」重試。模型不就緒或沒有可用向量時，語意及智慧模式會標示降級為關鍵字。部分索引缺失會提示結果尚不完整。

模型只在 setup_search.py 明確下載。執行時只讀本機檔案，不使用 CUDA，不與 Ollama 爭用 GPU。

## API

- GET /api/v1/search：q、mode=keyword/semantic/hybrid、platform、可重複的 topic/tag、limit 上限 50。回傳收藏、排名分數、命中欄位、片段及降級資訊。
- GET /api/v1/search/facets：owner 範圍的分類計數及索引 pending/failed/ready/model_ready。
- POST /api/v1/search/reindex：同步現有收藏的文字索引，重設待處理片段的失敗次數。
- PATCH /api/v1/saves/{id}/classification：version、topics、tags；省略欄位保持不變，null 恢復該欄位的 AI 值。

## 本次驗證

73 項後端測試、TypeScript 與正式建置通過。既有真實收藏中，「棠記」命中 Threads 留言；「冷凍備餐料理」的語意搜尋第一筆為日文食譜；「日文現場演唱」智慧搜尋優先返回音樂內容。這是功能案例，不代表完整 60 筆品質評估已完成。

介面實測包括音樂篩選、測試收藏的人工分類保存與恢復 AI 值、留言命中來源及繁中對日文語意搜尋。公開示範圖保存於 outputs/search-keyword.jpg 與 outputs/search-semantic.jpg。
