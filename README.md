# 世界奇談公開影片數據報告

公開網址：<https://ryamhome.github.io/yt-ailazybag-report/>

本網站顯示 `@ailazybag` 最新 **最多 30 支公開影片樣本**，不代表全頻道影片或觀看總數。資料來源為公開頻道頁，或既有頻道連線產生的 **公開欄位** API 快照；不使用瀏覽器登入或 Cookie。

## 資料有效性

- 觀看數與發布日期分別解析，支援文字 runs、分開的數字／標籤、無障礙文字與舊版 videoRenderer。
- 讀不到的數值是 `null`，頁面顯示 `—`；真正的 `0 views` 保留為 0。
- 資料缺漏、格式異常或超過 96 小時未更新時，顯示狀態並暫停成效判讀。未知發布日期不會被當成「還沒滿七天」。
- 更新失敗時保留上次可靠快照，分開顯示資料時間與最近檢查時間。GitHub Pages 部署成功不代表這次資料擷取成功，請查看 `data_quality.status`。
- 「上架滿七天」比較的是當下累計觀看，無法回推上架首七日表現。公開觀看數不能當成營利觀看時數。

## 更新方式

既有工作流程於週一、週四、週六台灣時間 10:30 更新，手動執行及推送 `main` 也會部署。

若私人製片專案的官方 API 收集器提供公開快照，可放到 `docs/public-channel-snapshot.json`；更新器會優先讀取 96 小時內的快照，過期後改用原有的單次公開頁請求。也可用下列環境變數明確指定已下載的快照：

```sh
REPORT_SNAPSHOT_PATH=/path/to/public_snapshot.json python tools/update_report.py
```

快照格式包含：

```json
{
  "generated_at": "2026-10-20T14:00:00+08:00",
  "source": "YouTube Data API v3",
  "public_subscriber_count": 2,
  "videos": [
    {
      "video_id": "example",
      "title": "事件名稱",
      "views": 12,
      "published_at": "2026-10-08T09:00:00Z",
      "duration": "3:05"
    }
  ],
  "owner_analytics": {
    "status": "reauthorization_required",
    "message": "需要頻道成效唯讀授權"
  }
}
```

即使 API 快照包含全頻道 `public_video_count`，本頁仍只統計 `videos` 樣本。曝光、CTR、留存及收益屬私人 Analytics；公開快照介面只接受連線狀態與說明，不複製私人指標，未取得的值不會補成 0。私人資料應留在私人報表或受控的工作流程產物。

## 測試

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Node.js 存在時，測試也會執行前端實際的未知值／零值／過期與異常資料行為檢查。測試不呼叫 YouTube。
