# Qwen3.8-Flash-Next Strata 部署測試報告

## 結論

部署測試通過。`Qwen3.8-Flash-Next` 已成功提供 OpenAI 相容的聊天 API，
且 Strata 在 64 GB 系統 RAM 的主機上，維持在約 12 GB VRAM 預算內。

這不是較小參數版本，而是 ISTA-DASLab 對完整 Qwen3.8-Flash-Next MoE 模型
製作的 GSQ-RCO `IQ2_XS` 量化。Strata 將大部分專家權重放在系統 RAM，
只在 GPU 快取部分專家，因此能降低 VRAM 需求。

## 測試環境

測試日期：2026-10-04（Asia/Taipei）

| 項目 | 數值 |
| --- | --- |
| 雲端 | Google Cloud 專案 `gen-lang-client-0321260816`（`compal`） |
| VM | `qwen38-strata-test`、`g2-standard-16`、`us-central1-b` |
| CPU | 16 vCPU、Intel Xeon 2.20 GHz、8 核心／16 執行緒 |
| RAM | 可見 62.8 GiB（配置 64 GB），無 swap |
| GPU | NVIDIA L4、23,034 MiB、compute capability 8.9 |
| 驅動 | 580.178.04、CUDA runtime 13.0 |
| 作業系統 | Ubuntu 22.04.5 LTS |
| 磁碟 | 200 GB `pd-ssd` 開機磁碟 |
| Docker | 29.1.3 |
| Strata commit | `99f3dbd0b21d1401b3769e0c0d963913607f380b` |
| 模型量化 | `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF`、`IQ2_XS` |
| Context | 32,768 tokens |
| KV cache | INT8 |
| 視覺功能 | 關閉 |

## 儲存需求

兩個模型分片合計 68,026,093,024 bytes：

- 分片 1：39,225,954,592 bytes
- 分片 2：28,800,138,432 bytes
- MTP 推測解碼資料：約 6.5 GiB

實務上至少需要 100 GB 可用空間；建議使用 200 GB，以容納 Docker 映像、
建置快取、模型、日誌與更新。

## 為何能以少量 VRAM 運行

主要由四個方法共同達成：

1. GSQ-RCO `IQ2_XS` 低位元量化縮小模型權重。
2. Strata 將約 33.02 GiB 專家權重放在系統 RAM。
3. GPU 只保留較常使用的專家快取，本次為 3,672 個專家、約 4.94 GiB。
4. KV cache 使用 INT8，並關閉非必要的視覺功能。

因此，模型並不是完整常駐 GPU。GPU 負責高速計算與部分專家快取，64 GB RAM
承擔較大的權重儲存。這會犧牲部分速度與高併發能力，但可大幅降低 GPU 門檻。

## 資源量測

未限制的 L4 基準幾乎使用整張 24 GB GPU：

| 模式 | Strata 程序 VRAM | GPU 總使用量 | GPU 剩餘 | 主機 RAM 使用量 |
| --- | ---: | ---: | ---: | ---: |
| 自動快取 | 22,032 MiB | 22,107 MiB | 458 MiB | 36 GiB |
| 模擬 12 GB 預算 | 10,444 MiB | 10,519 MiB | 12,046 MiB | 36 GiB |

限制設定：

```text
--vram-reserve-mib 12288
```

限制後 API 健康檢查回傳 `status: ok`。這證明 12 GB VRAM 加 64 GB RAM
足以完成此量化、32K context、單一請求的測試；不代表高併發、長上下文大量
使用或視覺功能也有相同性能。

## 推理測試結果

測試題目：

```text
請用繁體中文回答：列出三點量化能降低大型語言模型部署資源需求的原因，每點一句。
```

量測結果：

- HTTP status：200
- Prompt tokens：36
- Completion tokens：95
- Total tokens：131
- 端到端時間：4.214 秒
- Prompt processing：35.9 token/s
- Generation：29.6 token/s
- MTP draft tokens：64；accepted：43
- Finish reason：`stop`

模型用繁體中文正確列出縮小權重、降低計算成本及可在較低成本硬體運行等三點。

## 回答品質與「是否更聰明」

本次回答連貫、符合格式，且三點內容沒有明顯重複；主觀感受是基本回答品質
良好，服務確實可用。不過，本次只有一個簡短問題，沒有進行同題盲測、標準
評測集或與 GPT、Qwen 其他版本比較，因此不能由此判定模型「比較聰明」。

較可靠的下一階段應固定測試：

- 中文知識問答
- 多步推理
- 程式生成與除錯
- RAG 檢索正確率
- 長上下文穩定性
- 與現有服務相同題目的盲測評分

## 引擎與移植性

此 GSQ-RCO GGUF 部署需要 Strata 的專家分頁與快取能力，不能直接視為 vLLM
可載入的模型。若要使用 vLLM，需改用 vLLM 支援的 checkpoint 與量化格式。

移植目標：

- NVIDIA L4／L20：CUDA 架構 `89`
- RTX A6000：CUDA 架構 `86`
- 公開映像同時包含 `86;89`

L20 與 RTX A6000 的 VRAM 均高於本次驗證門檻。正式使用時可讓 Strata
利用更多 VRAM 增加專家快取，以換取更佳速度；只有重現 12 GB 限制時才需要
執行 `set-vram-reserve.sh`。

## API 與對外服務

測試端點只綁定 `127.0.0.1:8080`，未建立 GCP 公開 HTTP/HTTPS 規則，
因此沒有固定公開 URL。應用程式可使用：

```text
POST /v1/chat/completions
GET  /v1/models
GET  /health
```

正式環境建議使用保留 IP、DNS、TLS 反向代理或驗證通道，並設定 API key。
8080 連接埠應保持私有。

## 重建步驟

```bash
bash install-host.sh
sudo reboot
bash build-strata.sh
bash run-strata.sh
sudo docker logs -f strata-qwen38
RESERVE_MIB=12288 bash set-vram-reserve.sh  # 僅用於 24 GB GPU 模擬
bash test-api.sh
```

`strata-data` Docker volume 會保存模型與產生的設定。公開引擎映像不包含
約 75 GB 模型資料，首次啟動才會下載。

## 公開映像

```text
ghcr.io/zhyixi/qwen38-strata-deploy:cuda13-sm86-sm89
```

獨立專案發布驗證：

- GitHub Actions run：`37216682848`
- 發布標籤：`v1.0.0`
- 結果：成功，耗時 10 分 13 秒
- Index digest：`sha256:50b05e55e25e7a65f84258e9c500c14613859eef70c19667442b3ccbe3abade4`
- Runtime manifest：`linux/amd64`
- Runtime digest：`sha256:9cb4f20ba944802764fc6c0b8c3d3990c3f295e11f2d3d966cef96a5f4885f6f`

使用全新的空白 Docker 設定仍能讀取 manifest，確認映像可匿名取得。原始
GCP 主機也曾實際拉取同一建置方式產生的映像，掛載既有模型 volume 後成功
啟動，健康檢查為 `status: ok`，短回答速度為 22.9 token/s。

## 雲端資源清理

測試完成後已刪除暫時的 GCP 環境，並確認：

- 無 VM instances
- 無 persistent disks
- 無 snapshots
- 無 snapshot schedules
- 無保留的內部或外部 IP

因此測試使用的 GPU、CPU、RAM 與 200 GB SSD 不再產生新的資源費用。先前
已產生的費用可能因 Google 帳務資料延遲而稍後才顯示。
