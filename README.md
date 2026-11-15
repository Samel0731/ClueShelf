# ClueShelf 集緒

> A local-first personal knowledge base for things you save on YouTube, Instagram and Threads. Public-source extraction, structured classification with a local LLM (Ollama), hybrid multilingual search (SQLite FTS5 trigram + multilingual-e5 ONNX embeddings, fused with RRF), a lease-based durable job queue, and an offline evaluation harness that gates CI. Traditional Chinese UI; Chinese and Japanese content.

```mermaid
flowchart LR
  UI[Next.js UI] -->|HTTP /api/v1| API[FastAPI]
  API --> DB[(SQLite WAL + FTS5)]
  DB --> IO[IO worker: public source extraction]
  DB --> AIW[AI worker: Ollama structured output]
  DB --> IDX[Indexer: e5 ONNX on CPU]
  IO --> DB
  AIW --> DB
  IDX --> DB
  GOLD[Golden set] --> EVAL[scripts/eval.py]
  EVAL -->|hit@5 gate| CI[GitHub Actions]
```

將 YouTube、Instagram 與 Threads 的主動收藏集中保存。支援公開原文讀取、Threads 留言取樣、本地 AI 標題與分類、人工修正和可恢復的背景工作。

支援自訂主題與標籤管理、人工分類修正、繁中與日文關鍵字搜尋，以及本地語意與智慧搜尋。收藏每批載入 30 筆，可切換主題推薦模板、卡片、清單與 Graph 關係圖；標籤提供文字雲與數量清單。地圖、手動／動態清單及完整備份介面尚未實作。

YouTube 官方唯讀帳號連結支援手動匯入 API 可取得的按讚影片標題與說明，不下載影音。首次使用請依 [YouTube 帳號設定](docs/youtube.md) 建立 Google Web OAuth client；沒有憑證時，首頁會顯示尚未設定，不會嘗試授權。

## 在 Windows 啟動

需要 Python 3.12 以上與 Node.js 24 LTS。所有命令從專案根目錄執行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e ./backend
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts/dev.py
```

開啟 http://127.0.0.1:3000。API 文件位於 http://127.0.0.1:8000/docs。在啟動命令所在視窗按 Ctrl+C，停止網站、API 與 worker。

網站及 API 僅監聽本機。沒有正式登入功能，不要透過通道或反向代理公開此版本。

## 準備本地模型

如果已有 Ollama，啟動服務並下載 `qwen3:4b`。也可以使用專案內的 Windows 可攜版，需要數 GB 的下載與磁碟空間。

```powershell
.\.venv\Scripts\python.exe scripts/setup_ai.py
.\.venv\Scripts\python.exe scripts/dev.py
```

`dev.py` 在找到專案內 Ollama 且連接埠 11434 未被使用時，自動啟動本地模型服務。另開終端機下載模型一次。

```powershell
.\.venv\Scripts\python.exe scripts/pull_model.py
```

模型放在 `data/ollama-models`，可攜版放在 `data/ollama`。原文透過本機 HTTP 傳給 Ollama，不使用雲端推論。Ollama 自身可能在使用者目錄建立其執行金鑰。

## 解析 YouTube 影片

新貼上的 YouTube 連結會自動讀取公開說明、章節、留言與可用字幕。舊收藏和按讚匯入的影片可在詳細頁按「解析影片」。解析結果會標示觀眾提供的資訊，並附上可以核對的片段。可從搜尋欄查歌名、公司或股票代號。

從舊版升級時，先重新執行後端套件安裝，再用上方的 dev.py 命令啟動。公開文字解析需要已在 PATH 的 Node.js 24 和準備好的 Ollama。

需要「本機轉錄音訊」時，另外安裝套件並下載模型一次：

```powershell
.\.venv\Scripts\python.exe -m pip install -e "./backend[transcribe]"
.\.venv\Scripts\hf.exe download Systran/faster-whisper-small --local-dir data/models/faster-whisper-small
```

點選轉錄前需確認已獲准下載音訊。四小時內的已結束影片可在 CPU 上轉錄，長影片需要較久。平台限制、缺少原語字幕或只取得部分內容時，詳細頁會標出原因或解析範圍。歌曲辨識依賴來源中的歌名或報幕。

## 準備語意搜尋

```powershell
.\.venv\Scripts\python.exe scripts/setup_search.py
```

下載固定官方版本的 multilingual-e5-small ONNX 模型，保存在 `data/models/multilingual-e5-small`。這是獨立於 Ollama 的 CPU 模型，執行搜尋不連網、不使用付費服務。下載後更新網頁，或按「更新搜尋資料」。背景程序會為既有收藏建立向量。

關鍵字模式比對標題、作者內文、摘要、分類與 Threads 留言。語意模式依內容相近程度排序；智慧模式結合兩種排名。語意結果不代表精確文字命中，也不保證每筆都相關。模型或索引未就緒時，頁面顯示降級原因並先用關鍵字搜尋。

選擇多個主題或標籤時，收藏須同時符合所有條件。人工分類與標籤獨立保存，不被 AI 重跑覆寫；「恢復使用 AI 分類」清除人工分類覆寫。搜尋結果會顯示命中欄位，Threads 留言獨立標示。

## 試用收藏流程

1. 貼上 YouTube 影片、IG 貼文或 Reel、Threads 貼文的 HTTPS 連結。
2. 可選擇填寫標題與作者內文，按下收藏。
3. 背景工作讀取原文，再呼叫本地 AI 整理。讀不到時貼上作者內文；Threads 留言另貼在留言補充欄位。
4. 開啟收藏，修改標題或內文。版本衝突時重新載入，避免覆寫其他頁籤的修改。
5. 同一影片的短網址與完整網址只保存一次。重複加入不覆寫既有內容。
6. YouTube 預設用原始標題，可切換 AI 標題。其他平台由 AI 根據正文命名。人工修改不被重新處理覆寫。
7. 刪除前確認。刪除沒有復原功能。

支援 Threads `/share/` 分享連結解析，不支援帳號首頁或私人登入讀取。Threads 留言只代表實際取得範圍，不能保證全篇熱門排名。分享連結命中既有收藏時保留補充草稿，提供前往原收藏的入口。

## 執行檢查

```powershell
.\.venv\Scripts\python.exe scripts/verify.py
```

包含後端行為測試、遷移測試、前端型別檢查與正式建置。測試使用臨時 SQLite，不修改自己的收藏。執行正式建置前先停止開發網站，避免共用 Next.js 建置資料夾。

測試包含模型已安裝時的繁中對日文語意檢索。未安裝模型時，該項實測會跳過，其他測試不需要模型下載。

## 品質評估

`backend/clueshelf/evals/golden` 是可公開的示範資料集：60 筆自行撰寫的收藏（每平台 20 筆，繁中與日文）和 20 題搜尋問題，附預期主題與預期答案。店名與活動皆為虛構。

```powershell
.\.venv\Scripts\python.exe scripts/eval.py search --gate 0.8
.\.venv\Scripts\python.exe scripts/eval.py classify --models qwen3:4b
```

- `search` 只需要 CPU 搜尋模型。它用正式遷移建立臨時資料庫，只索引來源文字，比較關鍵字、語意與智慧模式的 Hit@5、Recall@5、MRR 和延遲。CI 以智慧模式 Hit@5 ≥ 0.8 作為關卡。
- `classify` 需要 Ollama。它用與 worker 相同的 prompt、schema 與參數，輸出主要分類正確率、各主題 precision／recall、失敗率與 p50／p95 延遲；`--models` 可用逗號比較多個模型。呼叫失敗一律算錯。
- 報告寫到 `reports/`。私人真實收藏用 `--golden <資料夾> --out reports/local`，該路徑不納入版本控制。

目前示範集的搜尋結果（[完整報告](reports/eval-search.md)）：

| 模式 | Hit@5 | Recall@5 | MRR | p50 |
|---|---|---|---|---|
| 關鍵字 | 80.0% | 55.8% | 0.800 | 2 ms |
| 語意 | 100.0% | 94.2% | 1.000 | 14 ms |
| 智慧 | 100.0% | 94.2% | 0.975 | 16 ms |

示範集的收藏彼此差異大，題目與內容出自同一作者，語意模式已經滿分，無法再分辨改動的好壞。這些數字只能證明管線可運作及跨語言檢索有效，不代表真實收藏的品質；`mvp-spec.md` 的 60 筆真實驗收仍待執行。

分類結果（`qwen3:4b`，RTX 3060 12GB；[示範集完整報告](reports/eval-classify.md)）：

| 資料集 | Prompt | 主要分類正確率 | 完全相符 | Micro F1 | 失敗 | p50 |
|---|---|---|---|---|---|---|
| 示範集 60 筆 | `classify-v1` | 80.0% | 75.0% | 0.816 | 1/60 | 1.49 秒 |
| 示範集 60 筆 | `classify-v2` | 93.3% | 83.3% | 0.906 | 1/60 | 1.52 秒 |
| 真實收藏 60 筆 | `classify-v1` | 75.0% | 70.0% | 0.742 | 1/60 | 1.73 秒 |
| 真實收藏 60 筆 | `classify-v2` | 88.3% | 76.7% | 0.824 | 0/60 | 1.71 秒 |

`classify-v1` 會把健身、保養、穿搭、遊戲等不屬於任何主題的內容塞進「程式」（真實收藏的「其他」recall 25%）。`classify-v2` 加上「主要重點符合才選」的規則及「其他」與多主題範例，「其他」recall 升到 58%，仍是最弱的主題。

真實收藏是從個人資料庫隨機抽樣的 60 筆（57 筆 YouTube），標註由較強的模型完成、4 個分類原則由擁有者決定，並非逐筆人工標註；prompt 是看著這兩份資料集的錯誤調整的，所以這些數字偏樂觀，尚未在全新的樣本上驗證。

真實收藏的搜尋以 `scripts/judge_search.py` 評估：對 20 個自然語句問題合併三種模式的前五名，由擁有者勾選相關結果。在 1658 筆收藏、11735 個片段上：

| 版本 | 語意 Hit@5 | 語意 Precision@5 | 語意 MRR | 關鍵字 p50 | 語意 p50 | 智慧 p50 |
|---|---|---|---|---|---|---|
| 修改前 | 85% | 63% | 0.729 | 2411 ms | 5108 ms | 5023 ms |
| 修改後 | 90% | 62% | 0.742 | 113 ms | 105 ms | 208 ms |

修改內容：未加篩選時不再載入並分類每一筆收藏；向量改以常駐記憶體的 numpy 矩陣計分，內容變動時才重建（啟動後第一次查詢約 4 秒）；只含主題名稱的片段不再參與語意排名，因為同主題的收藏會全部同分；整句查詢找不到完全符合的結果時，改用中日文雙字詞的部分比對。兩個版本以同一份合併後的人工判定計分。延遲降低約 25 到 50 倍；準確度基本持平：多答對 1 題（「點心食譜」從 0 筆相關變成 3 筆），但有 2 題的相關結果變少（「語言學習方法」「如何找工作 精進自己」），20 題的樣本不足以判定排名品質有提升。整句的關鍵字比對在真實收藏上仍只對 20 題中的 2 題有結果，智慧模式實際上仍等同語意模式。

模型名稱可用環境變數 `CLUESHELF_AI_MODEL` 更換。每筆分析結果會記錄 `model` 與 `prompt_version`，修改 `ai.py` 的 prompt 或 schema 時須同步更新 `PROMPT_VERSION`。

## 資料與背景工作

SQLite 預設位於 `data/clueshelf.db`，不納入版本控制。可以設定 `CLUESHELF_DATABASE_URL` 指向其他 SQLite 檔案。變更後 API、worker 與遷移必須使用相同設定。

每筆收藏保留固定本地使用者的歸屬。工作以收藏版本、租約與嘗試次數識別，重啟後恢復過期工作，最多自動嘗試三次。手動重試會建立新版本。

來源讀取、YouTube 官方同步、單一 AI worker 與 CPU 搜尋索引分開執行。AI 按實際節錄文字分成小、中、大工作，以 3：2：1 輪替，每類內先進先出；分類是文字長度估算，不是 token 計數。

worker 定期續租，過期程序不能提交結果。升級資料庫前會自動備份到 `data/backups`。這是遷移前的資料庫備份，不等同完整資料匯出與還原功能。

## 規劃與工作紀錄

- [MVP 規格](docs/mvp-spec.md)
- [決策紀錄](docs/planning.md)
- [領域名詞](CONTEXT.md)
- [pstack 模型設定](docs/pstack-models.md)
- [第一階段執行紀錄](docs/implementation-log.md)
- [原文與本地 AI 設計](docs/phase-two.md)

pstack 採專案內 Codex 適配，small 預算與 inherit-parent 角色設定。不修改全域 Cursor 設定。工作方式依使用者指定的 [poteto-mode](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/SKILL.md)。

## 分類與探索

分類管理可新增主題與標籤，預覽改名、合併、封存與恢復。合併保留別名，既有原始 AI 快照不改寫；封存項目保留已有關聯。AI 使用啟用中的主題與說明分類。「請 AI 建議整理」只分析近期收藏的有限樣本，使用同一個 GPU worker，產生建議後須由你選取、確認，不會自動改分類。

首頁初次只載入 30 筆精簡收藏；內容視窗才讀取完整原文。搜尋、文字雲與 Graph 共用十分鐘的結果快照，過期可按更新結果。文字雲最多顯示前 60 個標籤，每個數字是相關收藏數，不是原文詞頻。

Graph 初始最多顯示 20 個主題、40 個標籤與 120 條共現連線。點分類展開 30 筆收藏，同時最多 150 筆，可收合分支。也可用節點清單操作、點收藏開啟內容視窗。連線只表示共同分類，並非因果或語意相似。背景分類更新時先顯示提示，按更新才重排。

單一主題的「主題推薦」使用設定的模板，多主題使用通用卡片。模板僅整理已有摘要與標籤，不自動補地址、食材或活動日期。
