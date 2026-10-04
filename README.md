# Qwen3.8-Flash-Next Strata 低資源部署

本專案保存 2026-10-04 實際驗證通過的部署方法：使用 Strata 推理引擎執行
ISTA-DASLab 製作的 `Qwen3.8-Flash-Next` GSQ-RCO `IQ2_XS` GGUF 量化模型。

Qwen 官方模型卡將核心語言模型列為 125B、每個 token 啟用約 6B，另有
51B n-gram embedding 與 4B MTP；量化頁的整體 metadata 標示約 177B。
本專案測試的是這套完整權重，不是 27B 縮小版。GSQ 產生高精度低位元
scalar quantization，RCO 再依各 tensor 敏感度於固定容量內配置不同精度；
Strata 則在推理時把 experts 分層放入 RAM 與 GPU cache。技術細節、來源與
驗證矩陣請見 [REPORT.md](REPORT.md)。

## 已驗證需求

- 64 GB 系統記憶體
- 約 12 GB 可用 VRAM
- Ubuntu 22.04 x86_64
- NVIDIA 580 或更新版驅動
- Docker 與 NVIDIA Container Toolkit
- 至少 100 GB 可用磁碟；建議 200 GB

雲端測試使用一張 24 GB NVIDIA L4，並設定
`--vram-reserve-mib 12288`，刻意保留 12 GB VRAM。Strata 程序實際使用
10,444 MiB，GPU 仍有 12,046 MiB 可用，因此證明此配置可在約 12 GB VRAM
預算內運作。完整數據請見 [REPORT.md](REPORT.md)。

## 為何大模型能使用較少 VRAM

1. `IQ2_XS` 低位元量化大幅縮小模型權重。
2. Strata 將約 33 GiB 專家權重放在 64 GB 系統 RAM，而非全部塞入 GPU。
3. GPU 只快取目前較需要的專家；本次快取 3,672 個專家，約 4.94 GiB。
4. KV cache 使用 INT8，且測試關閉視覺功能，進一步降低 VRAM 用量。

這不是把模型縮成較小參數版本，而是讓完整 MoE 模型的權重在 RAM 與 GPU
之間分層存放。代價是速度與高併發能力可能低於全模型常駐 VRAM 的部署。

## 快速啟動

在新的 Ubuntu GPU 主機執行：

```bash
git clone https://github.com/Zhyixi/qwen38-strata-deploy.git
cd qwen38-strata-deploy
bash install-host.sh
sudo reboot
```

重新連線後啟動：

```bash
cd qwen38-strata-deploy
bash run-strata.sh
```

預設公開映像：

```text
ghcr.io/zhyixi/qwen38-strata-deploy:cuda13-sm86-sm89
```

若要自行建置：

```bash
bash build-strata.sh
STRATA_IMAGE=strata:qwen38 bash run-strata.sh
```

首次啟動會下載約 68 GB 主模型與約 6.5 GiB MTP 資料，並編譯 Strata
核心。可用以下指令查看進度：

```bash
sudo docker logs -f strata-qwen38
```

## VRAM 限制重現

實體 12 GB GPU 會由 Strata 自動依可用空間配置快取。若要在較大的 GPU
模擬 12 GB 預算，首次啟動產生設定檔後執行：

```bash
RESERVE_MIB=12288 bash set-vram-reserve.sh  # 24 GB L4
RESERVE_MIB=36864 bash set-vram-reserve.sh  # 48 GB L20/A6000
```

測試 OpenAI 相容 API：

```bash
bash test-api.sh
```

## GPU 相容性

公開映像同時編譯 CUDA 架構 8.6 與 8.9：

- RTX A6000：compute capability 8.6
- NVIDIA L4、L20：compute capability 8.9

10 GB 或 12 GB 的 Ampere/Ada GPU 可使用相同映像，但目前實測下限約為
12 GB VRAM。更小的 GPU 可能可運行，但尚未驗證，不應直接當作正式環境承諾。

## 回答品質觀察

測試問題要求模型用繁體中文列出三點量化降低部署資源的原因。回答連貫、
格式正確且三點內容不同，代表服務與基本推理可正常使用。但這只是單題功能
測試，沒有與其他模型進行相同題庫、盲測或評分，因此目前不能客觀宣稱它
「比較聰明」。後續應加入知識、推理、程式與 RAG 任務的固定評測集。

## 網路安全

預設僅綁定 `127.0.0.1:8080`，不會建立公開網址或防火牆規則。正式服務
應在前方放置 TLS 反向代理或驗證通道，並設定 API key，不要直接公開 8080。

## GCP 重建參考

原始驗證環境：

- 專案：`gen-lang-client-0321260816`（`compal`）
- 區域：`us-central1-b`
- 機型：`g2-standard-16`
- GPU：一張 NVIDIA L4
- 開機磁碟：200 GB `pd-ssd`
- 系統：Ubuntu 22.04 LTS

```bash
gcloud compute instances create qwen38-strata-test \
  --project=gen-lang-client-0321260816 \
  --zone=us-central1-b \
  --machine-type=g2-standard-16 \
  --accelerator=type=nvidia-l4,count=1 \
  --maintenance-policy=TERMINATE \
  --restart-on-failure \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=200GB \
  --boot-disk-type=pd-ssd
```

建立 VM 會開始計費。原始測試 VM、磁碟、快照排程與保留 IP 均已刪除。
