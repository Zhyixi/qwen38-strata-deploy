# Qwen3.8-Flash-Next Strata 部署測試報告

## 結論

部署測試通過。`Qwen3.8-Flash-Next` 已成功提供 OpenAI 相容的聊天 API，
且 Strata 在 64 GB 系統 RAM 的主機上，維持在約 12 GB VRAM 預算內。

這不是較小參數版本，而是 ISTA-DASLab 對完整 Qwen3.8-Flash-Next MoE 模型
製作的 GSQ-RCO `IQ2_XS` 量化。Strata 將大部分專家權重放在系統 RAM，
只在 GPU 快取部分專家，因此能降低 VRAM 需求。

## 模型規模與 125B 的定義

Qwen 官方模型卡列出的參數組成如下：

| 組成 | 官方數字 | 推理時的角色 |
| --- | ---: | --- |
| 核心語言模型 | 125B | MoE 主模型，每個 token 約啟用 6B |
| Routed experts | 每層 512 個 | 每個 token 選 10 個，加 1 個 shared expert |
| N-gram embedding | 51B | 查表使用，不是每個 token 全部做矩陣乘法 |
| MTP | 4B | 推測解碼，用來提出候選 token |
| 原生 context | 262,144 tokens | 本次為控制資源，實測使用 32,768 |

Hugging Face 的量化模型頁將此套權重標示為 177B params；Qwen 模型卡則將
核心語言模型寫為 125B，另列 51B n-gram embedding 與 4B MTP。兩者是
計數口徑差異，不代表我們測試的是較小的 27B 模型。本次實際下載的主 GGUF
為 68.0 GB，另有約 6.5 GiB MTP 資料。

官方資料：

- [Qwen3.8-Flash-Next 模型卡](https://huggingface.co/Qwen/Qwen3.8-Flash-Next)
- [ISTA-DASLab GSQ-RCO GGUF 模型卡](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF)

## GSQ、RCO、GGUF 與 Strata

這套方法不是單一技術，而是「量化格式」與「推理時記憶體分層」的組合：

| 元件 | 全名／角色 | 實際作用 |
| --- | --- | --- |
| ISTA-DASLab | 奧地利 ISTA 的 Deep Algorithms and Systems Lab | 製作並發布量化權重與可重現資訊 |
| GSQ | Gumbel-Softmax Quantization | 訓練每個 tensor 的低位元 scalar grid 與 group scale，改善 2–3 bit 精度 |
| RCO | Riemannian Constrained Optimization | 在固定總容量下，依 tensor 敏感度選擇不同量化型別 |
| GGUF | 模型權重與 metadata 的容器格式 | 將非均勻、逐 tensor 的量化配置包裝成可部署檔案 |
| Strata | MoE 特化推理引擎 | 管理 RAM expert arena、GPU expert cache、CPU worker 與 MTP 推測解碼 |

一般「均勻 2-bit」會把所有 tensor 用同一精度。GSQ-RCO 則先評估各 tensor
對誤差的敏感度，再由 RCO 在精確容量預算內分配不同量化型別：重要 tensor
保留較高精度，較不敏感的 tensor 使用更低位元。因此 `IQ2_XS` 的平均
transformer 權重約為 2.50 bpw，但不是每個 tensor 都固定 2.5 bit。

Qwen3.8-Flash-Next 每層有 512 個 routed experts，但每個 token 只會啟用
10 個 routed experts 與 1 個 shared expert。Strata 利用這項稀疏性：

1. 約 33.02 GiB expert 權重放在系統 RAM。
2. 依 routing profile 將常用 experts 放進 GPU cache。
3. 本次 GPU cache 為 3,672 experts、約 4.94 GiB。
4. 未命中 GPU cache 的工作由 13 個 expert-pool CPU workers 與 host thread
   協作，不要求全部 experts 同時常駐 VRAM。
5. MTP 先草擬多個 token，再由主模型驗證；本次 64 個 draft token 接受 43 個。

因此 Strata 的「特殊」不只在於能讀取模型，而是它負責 MoE experts 的
RAM／GPU 分層、路由快取、CPU/GPU 協作及推測解碼。官方實作與說明：
[Niko1221/Strata](https://github.com/Niko1221/Strata)。

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

## 完整驗證矩陣

| 驗證項目 | 結果 | 實測數字／證據 |
| --- | --- | --- |
| 模型檔完整下載 | 通過 | 主 GGUF 68,026,093,024 bytes；MTP 約 6.5 GiB |
| Strata 啟動 | 通過 | 固定 commit `99f3dbd0...`，session ready |
| 64 GB RAM 容量 | 通過 | OS 可見 62.8 GiB；推理時主機 RAM 約使用 36 GiB |
| 12 GB VRAM 預算 | 通過 | Strata 10,444 MiB；GPU 總使用 10,519 MiB |
| VRAM 保留量 | 通過 | 24 GB L4 上仍剩 12,046 MiB |
| OpenAI 相容 API | 通過 | `POST /v1/chat/completions` 回傳 HTTP 200 |
| 健康檢查 | 通過 | `GET /health` 回傳 `status: ok` |
| 單題端到端延遲 | 通過 | 4.214 秒，36 prompt + 95 completion tokens |
| Prompt processing | 已量測 | 35.9 token/s |
| Generation | 已量測 | 29.6 token/s |
| MTP 接受率 | 已量測 | 43 / 64 = 67.2% |
| 公開映像重新啟動 | 通過 | 短回答 22.9 token/s，未重下載既有模型 |
| 匿名取得 GHCR | 通過 | 空白 Docker config 可讀取公開 manifest |
| sm86／sm89 映像 | 通過 | GitHub Actions 成功建置 A6000、L4／L20 架構 |
| 實體 16 GB GPU | 尚未測試 | 本次用 24 GB L4 強制保留 12 GB 模擬容量限制 |
| 多使用者高併發 | 尚未測試 | 本次為單一請求 |
| 長 context 壓力 | 尚未測試 | 本次 context 上限 32,768，未做長文滿載 |
| 模型聰明度比較 | 尚未證實 | 只有單題功能測試，需固定評測集與盲測 |

## 是否證實 16 GB VRAM＋64 GB RAM 可跑 125B

| 判定問題 | 結論 | 理由 |
| --- | --- | --- |
| 這次是不是 125B 核心模型？ | 是 | Qwen 官方列出核心語言模型 125B、每 token 啟用 6B |
| 64 GB RAM 是否實際足夠？ | 是 | 64 GB 主機成功載入，推理時約使用 36 GiB |
| VRAM 是否低於 16 GB？ | 是 | Strata 程序 10,444 MiB，GPU 總使用 10,519 MiB |
| 能否回應 API 請求？ | 是 | HTTP 200、內容正常、29.6 token/s |
| 是否已在實體 16 GB 卡測試？ | 否 | 使用 24 GB L4，透過 reserve 參數模擬 12 GB 預算 |
| 能否代表所有 125B 模型？ | 否 | 結果依賴 MoE 稀疏性、IQ2_XS 量化與 Strata 分層 |

**精確結論：**本次已證實「Qwen3.8-Flash-Next 這個 125B 核心 MoE 模型，
使用指定 IQ2_XS GSQ-RCO 權重與 Strata，在 64 GB RAM 且 VRAM 使用量低於
12 GB 時可以完成推理」。所以從記憶體容量來看，16 GB VRAM＋64 GB RAM
有足夠餘裕；但尚未證實實體 16 GB GPU 的速度、穩定性與高併發表現，也不能
延伸成任何 dense 125B 模型都能使用相同配置。

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
