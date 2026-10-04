# Qwen3.8-Flash-Next Strata 低資源部署

本專案保存 2026-10-04 實際驗證通過的部署方法：使用 Strata 推理引擎執行
ISTA-DASLab 製作的 `Qwen3.8-Flash-Next` GSQ-RCO `IQ2_XS` GGUF 量化模型。

這是官方所稱的**約 180B 總系統**：包含 125B 核心 MoE 語言模型（每個
token 啟用約 6B）、51B n-gram embedding 與 4B MTP。量化頁 metadata
顯示約 177B，差異來自計數與四捨五入口徑。本專案測試的是這套完整權重，
不是 27B 縮小版。GSQ 產生高精度低位元
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

測試 LangChain `ChatOpenAI` 相容性：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-langchain.txt
STRATA_BASE_URL=http://127.0.0.1:8080/v1 python test-langchain.py
```

## GPU 相容性

公司正式目標是 RTX A6000 與 NVIDIA L20。公開映像同時編譯 CUDA 架構
8.6 與 8.9：

- RTX A6000：48 GB、Ampere、compute capability 8.6
- NVIDIA L20：48 GB、Ada、compute capability 8.9

本次因雲端未取得公司同型卡，使用同為 Ada 8.9 的 L4 實測，因此可驗證 L20
所需的 CUDA 程式碼路徑、容器啟動與功能；但 L4 不能代替 L20 的精確吞吐量
與壓力測試。A6000 的 8.6 程式碼已成功建入映像，但尚未在實體 8.6 GPU
執行；若租不到 A6000，可先用同為 Ampere 8.6 的 A10、RTX A5000、A4000
或 RTX 3090 做移植測試，最終仍應在公司的 A6000 驗收。

硬體規格可交叉查核 [NVIDIA CUDA GPU compute capability 表](https://developer.nvidia.com/cuda/gpus)、
[RTX A6000 官方規格](https://www.nvidia.com/en-us/products/workstations/rtx-a6000/)
與 [NVIDIA Ada vGPU 規格表](https://docs.nvidia.com/ai-enterprise/release-7/latest/infra-software/vgpu/reference/ada-lovelace.html)。

10 GB 或 12 GB 的 Ampere/Ada GPU 可使用相同映像，但目前實測下限約為
12 GB VRAM。更小的 GPU 可能可運行，但尚未驗證，不應直接當作正式環境承諾。

## OpenAI 與 LangChain 相容性

Strata 提供 OpenAI Chat Completions 相容端點；LangChain 可透過
`langchain-openai` 的 `ChatOpenAI(base_url=...)` 連接，不必更改既有 chain
的主要介面。直接 HTTP 的非串流聊天已實測通過；`test-langchain.py` 可在
服務啟動後驗證 LangChain invoke 與選用的 streaming。工具呼叫、結構化輸出、
async、高併發與完整 callback 行為仍應用公司的實際 chain 另做驗收。
設定方式可參考 [LangChain ChatOpenAI 官方文件](https://docs.langchain.com/oss/python/integrations/chat/openai)。

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
