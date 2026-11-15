# YouTube 官方帳號連結

ClueShelf 以唯讀權限讀取一個頻道的按讚清單，只保存影片連結、標題及影片說明，不下載影音。同步由使用者手動啟動。

## Google Cloud 設定

1. 開啟 [Google Cloud Console](https://console.cloud.google.com/)，建立或選擇專案。
2. 啟用 **YouTube Data API v3**。
3. 在 Google Auth Platform 設定應用程式名稱、聯絡資料及使用對象。開發期間可維持 Testing，將自己的 Google 帳號加入測試使用者。
4. 在資料存取權限加入 `https://www.googleapis.com/auth/youtube.readonly`。
5. 建立 OAuth client，類型選 **Web application**。授權重新導向 URI 必須完全等於 `http://127.0.0.1:8000/api/v1/youtube/oauth/callback`。
6. 下載 client JSON，放在專案的 `data/google-client.json`。`data/` 已忽略，不要放進版本控制或貼到聊天裡。
7. 重新啟動 ClueShelf。在首頁的 YouTube 區塊按「連結帳號」，於系統預設瀏覽器完成 Google 授權。
8. 回到 ClueShelf，確認顯示自己的頻道，再按「同步」。Google 的返回頁只顯示連線結果。

Google 外部應用程式處於 Testing 時，離線授權可能只有七天效期；遇到「需重新連結」時重新授權。公開上線前需另外完成 Google 要求的驗證與正式 HTTPS 網址設定。

目前環境尚未放入本人 OAuth client，也尚未完成真實帳號授權。自動化測試使用假的 Google 回應，只能驗證程式流程。

## 設定與認證保存

| 設定 | 預設值 |
| --- | --- |
| `CLUESHELF_GOOGLE_CLIENT_FILE` | `data/google-client.json` 的絕對路徑 |
| `CLUESHELF_YOUTUBE_CALLBACK` | `http://127.0.0.1:8000/api/v1/youtube/oauth/callback` |
| `CLUESHELF_FRONTEND_URL` | `http://127.0.0.1:3000/` |

程式讀取的是啟動時的環境變數，不會自動載入 `.env`。可直接使用預設檔案位置，不需設定環境變數。正式網址必須使用 HTTPS。

Google access token、refresh token 和暫時的 PKCE verifier 保存在目前 Windows 使用者的 Credential Manager，名稱以 `ClueShelf/` 開頭。SQLite 保存連線、來源與進度，不保存權杖。不能用同步資料庫檔案的方法搬移 Google 授權，換電腦後需重新連結。

開始授權時只將一次性本機啟動票證交給系統瀏覽器。瀏覽器先在本機領取 HttpOnly cookie，再跳轉 Google。這讓桌面內嵌瀏覽器與系統瀏覽器使用不同 cookie 儲存空間時仍可安全授權。state 與啟動票證只接受一次，十分鐘後失效。

本機啟動器關閉 API access log，避免 callback 查詢參數進入紀錄。自行啟動 API 時也必須使用 `uvicorn ... --no-access-log`，反向代理不得記錄 `/api/v1/youtube/oauth/*` 的完整查詢參數。

解除連結會停止同步、清除本機認證並嘗試撤銷 Google 授權，已匯入收藏保留。如果撤銷時 Google 無法連線，請到 [Google 帳戶的第三方連線](https://myaccount.google.com/connections) 移除 ClueShelf。若 Windows 認證服務無法清除，介面會保留重試入口。

## 同步及恢復

官方 API 先查頻道的按讚清單，再每頁最多讀取五十個項目，分批取得影片完整說明。沒有自行設定總筆數限制，但完成只代表本次 API 可取得的範圍，不保證完整帳號歷史。私人、刪除或無法取得的影片統計為「無法取得」。

每頁的影片、來源紀錄及下一頁游標在同一筆交易提交。頁面中途失敗不會保存半頁，重啟後重新處理該頁。工作有租約與每十秒續租，逾期工作可重新取得；舊程序不能覆寫新的結果。同頻道同時只允許一個同步工作。

暫時性連線錯誤最多嘗試三次。配額用完會暫停，稍後可手動再次同步並沿用已保存的游標。無效游標會從頭重新掃描一次，利用影片來源紀錄去重。中止會完成已在執行的那一頁後停止；下次手動同步重新掃描。

影片原文標記 `provider=youtube_api`，不再交給公開網頁讀取器。已存在影片會更新來源快照，保留人工標題、內文、主題及標籤。來源內容未變不重新排 AI，來源改變才增加版本並取代舊工作。AI 失敗時可使用收藏本身的重試功能。

程式保存每個來源的首次發現、最近看到時間、同步工作識別及最後完整掃描時間。第一版不比較消失的影片，也不推論取消按讚或刪除收藏。一次只使用原本連結的頻道，尚不提供切換到不同頻道。

## 工作程序

- `python -m clueshelf.youtube_sync worker`：官方 API I/O，同步每次處理一頁。
- AI worker：沿用單一 Ollama 工作程序，由工作大小佇列分流。
- CPU 索引 worker：獨立建立本機 E5 語意索引。

`scripts/dev.py` 會一起啟動這些程序。資料庫仍只有一份，交易只涵蓋短時間的資料保存，Google 與 Ollama 網路處理在交易外執行。

## 官方參考

- [OAuth Web server 流程](https://developers.google.com/identity/protocols/oauth2/web-server)
- [playlistItems.list](https://developers.google.com/youtube/data/reference/rest/v3/playlistItems/list)
- [channels.list](https://developers.google.com/youtube/data/reference/rest/v3/channels/list)
- [videos.list](https://developers.google.com/youtube/data/reference/rest/v3/videos/list)
