# Threads 開戶客戶雷達（公開搜尋 MVP）

這是第一版測試工具：定時讀取 Threads 公開搜尋頁面可見的資料，整理成手機可開啟的簡單儀表板。

## 重要限制

- 不使用 Threads 密碼、登入 Cookie、私訊、追蹤或按讚功能。
- 只嘗試讀取公開搜尋頁面回傳的 HTML/JSON。
- Threads 對未登入訪客顯示的搜尋結果可能只有有限的一頁；這不是完整搜尋，也不能保證每篇符合條件的貼文都會被找到。
- Threads 可能調整頁面結構、限制自動請求或回傳空白頁。遇到 403、429 或解析不到資料時，程式會記錄錯誤，不會嘗試繞過限制。
- 使用前請確認符合 Threads 條款及適用法規；若此方式不可用，應改用官方授權或合規的資料供應商。

## 專案內容

- `keywords.txt`：每行一個搜尋詞
- `app.py`：抓取公開搜尋頁、解析可辨識貼文、去重並保存
- `.github/workflows/monitor.yml`：GitHub Actions 每 10 分鐘排程
- `docs/index.html`：手機版客戶雷達
- `docs/posts.json`：執行後自動產生的結果資料

## 安裝到 GitHub

1. 在 GitHub 建立一個新的 repository，例如 `threads-client-radar`。
2. 將本專案所有檔案上傳到 repository 根目錄，保留 `.github/workflows/monitor.yml` 路徑。
3. 進入 **Actions** 分頁，若 GitHub 詢問是否啟用 workflows，請允許。
4. 點選 **Threads public keyword monitor**，按 **Run workflow** 手動測試一次。
5. 若執行成功，確認 `docs/posts.json` 已建立或更新。
6. 進入 **Settings → Pages**，在 Build and deployment 選 **Deploy from a branch**，Branch 選 `main`，資料夾選 `/docs`，按 Save。
7. 等待 Pages 部署完成，頁面網址通常是 `https://你的GitHub帳號.github.io/threads-client-radar/`。

> GitHub Pages 的可用方案與 repository 公開/私人設定有關。若私人 repo 無法啟用 Pages，請先確認帳號方案；不要為了發布儀表板而公開任何密鑰或私人資料。本專案目前沒有需要放入的 API 金鑰。

## 修改搜尋關鍵字

編輯 `keywords.txt`，一行一個詞。第一版預設：
- 找營業員、換券商、開戶推薦、股票開戶
- 當沖、手續費
- 程式交易、量化交易、股票 API、自動下單、券商推薦

建議先從 5～10 個高意圖詞開始。每個詞會發出一次公開頁面請求，程式在請求間隔至少 4 秒。

## 排程說明

GitHub Actions 使用 `*/10 * * * *`，代表每 10 分鐘排程一次。GitHub Actions 排程可能延遲，尤其尖峰時段；不是精準計時器。若 workflow 執行時間超過 10 分鐘，下一輪也可能排隊。

## 結果如何判讀

- `posts.json` 保存最近觀察到的最多 800 筆貼文。
- 重複貼文以 Threads post code 去重。
- `errors` 顯示無法取得或解析的搜尋詞。
- 「沒有資料」不等於 Threads 上沒有人發文，可能是匿名頁面限制或頁面結構改變。
