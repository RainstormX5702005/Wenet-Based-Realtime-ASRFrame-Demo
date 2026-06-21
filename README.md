<p align="center">
  <strong>Real-Time ASR &mdash; a streaming speech recognition pipeline from browser mic to text</strong><br>
  <strong>实时语音识别 &mdash; 从浏览器麦克风到文字的流式转写流水线</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white" alt="PyTorch 2.0+">
  <img src="https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white" alt="FastAPI 0.109+">
  <img src="https://img.shields.io/badge/WebSocket-streaming-FF6F00" alt="WebSocket streaming">
  <img src="https://img.shields.io/badge/Silero_VAD-6.2%2B-1F425F" alt="Silero VAD 6.2+">
  <img src="https://img.shields.io/badge/Wenet-Conformer_CTC-8A2BE2" alt="Wenet Conformer CTC">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
</p>

This repository contains a streaming real-time automatic speech recognition system
built from the ground up. Audio is captured in the browser, streamed over WebSocket,
processed through a modular preprocessing pipeline, and transcribed by a persistent
Wenet subprocess &mdash; all with structured logging and a clean extensibility model.

本仓库是一个从零搭建的流式实时语音识别系统。音频在浏览器端采集，经 WebSocket
实时传输，通过模块化预处理管线流转，最终由持久化 Wenet 子进程完成转写 &mdash;
全程附带结构化日志和清晰的扩展模型。

<details>
<summary><strong>AI READ / AI 阅读指引</strong></summary>

如果你是一个 AI 编程助手，在阅读任何代码或做出任何修改之前，**请先阅读 [docs/project-upgrade-hints.md](docs/project-upgrade-hints.md)**。该文档包含了项目所有者对架构演进、代码取舍和参数调优的明确指令，是所有开发工作的首要约束文件。

If you are an AI coding assistant, **read [docs/project-upgrade-hints.md](docs/project-upgrade-hints.md) before touching any code**. It is the primary constraint file for all development work on this repository.

</details>

---

## Contents / 目录

- [Why This Project / 为什么要做这个项目](#why-this-project--为什么要做这个项目)
- [Highlights / 工程亮点](#highlights--工程亮点)
- [Architecture / 整体架构](#architecture--整体架构)
- [Pipeline Design / 管线设计](#pipeline-design--管线设计)
- [Core Components / 核心组件](#core-components--核心组件)
- [Quick Start / 快速开始](#quick-start--快速开始)
- [Project Structure / 项目结构](#project-structure--项目结构)
- [Limitations / 当前局限](#limitations--当前局限)
- [Roadmap / 演进路线](#roadmap--演进路线)
- [Third-party Resources / 第三方资源](#third-party-resources--第三方资源)
- [License / 许可证](#license--许可证)
- [Acknowledgements / 致谢](#acknowledgements--致谢)

## Why This Project / 为什么要做这个项目

这是我接触并正式开始实践语音项目的开山作，见证了我从零到 0.5 构造整个语音识别
流水线的全过程。除去 Wenet 框架本身，自己编写的有效代码虽不多，但每一行都
经过了认真的工程思考。

一个实用的语音识别系统不能只是一次模型推理。它需要回答：

- 音频流中何时有人在说话？
- 说话的内容是什么？
- 如何在 GPU 推理速度跟不上音频输入时保持系统稳定？
- 如何让预处理、队列、转写、日志各层解耦，各自独立演进？
- 切换 ASR 引擎或预处理策略时，改动范围有多大？

本项目围绕这一完整流程构建，把工程基础设施做在了模型推理的外面。

项目工作流水线如下所示：

```
浏览器前端                    FastAPI 主进程                      Wenet 子进程
   │                            │                                  │
   │  WebSocket 512-sample      │                                  │
   │  float32 chunks @ 16kHz    │                                  │
   │ ─────────────────────────► │                                  │
   │                            │  PreprocessPipeline              │
   │                            │  ├─ DCRemover                   │
   │                            │  ├─ StreamingVadSegmenter        │
   │                            │  ├─ RmsNormalizer               │
   │                            │  └─ AudioPeakLimiter            │
   │                            │                                  │
   │                            │  validate + windowing            │
   │                            │         │                        │
   │                            │  AudioTaskQueue  (max 3)         │
   │                            │  TranscriptionWorker ──────────► │  JSONL stdin/stdout
   │                            │                                  │  ├─ load model
   │                            │                                  │  ├─ fbank features
   │  ◄── transcribed text ──── ┤  ◄── n-best results ─────────── │  └─ CTC beam search
   │                            │                                  │
   │                            │  AsrResultLogger                 │
   │                            │  ──► logs/transcription_*.jsonl │
```

## Highlights / 工程亮点

- **Pipeline 模式**：所有预处理步骤统一实现 `PreprocessStep` 协议，模仿 scikit-learn
  的 Pipeline 设计。构造时通过注册表做契约校验，杜绝重复注册和非可调用对象进入管线。
  每步接收并返回 `AudioData` 数据包，链式传递，添加新步骤只需实现协议并注册。

- **进程化 ASR 后端**：Wenet 作为持久化子进程运行，通过 stdin/stdout 交换 JSONL 消息。
  主 FastAPI 进程保持轻量，GPU 模型常驻内存，避免了每次请求的模型加载开销。线程锁保护
  子进程 I/O 的串行安全。

- **流式 VAD 分段**：基于 Silero VAD 的逐帧驱动语音活动检测，在 512 采样点粒度上实时
  判断语音起止。检测到语音结束时输出完整片段，同时提取语音前的静音段作为噪声参考，
  传递给降噪步骤使用。

- **有界队列与反压**：`AudioTaskQueue` 最大容量 3，溢出时默认丢弃最旧任务。在 GPU
  转录速度跟不上音频采集速度时，队列容量天然限制内存增长，避免无限积压。

- **抽象基类 + 工厂**：`BaseTranscriber` 定义转写契约，`create_transcriber` 工厂根据
  配置创建具体实现。未来切换到 HMM、自研模型或其他 ASR 引擎，只需实现新的 Transcriber
  子类，其余模块不受影响。

- **结构化日志**：按日输出 JSONL 日志，完整记录每次转写结果的 n-best 词条与分数，
  以及系统生命周期事件，方便后续分析和调试。

## Architecture / 整体架构

系统由三个物理进程协同工作，数据在进程间单向流动：

**进程 1 — 浏览器前端**：Vue 3 SPA，通过 WebSocket 以 16kHz 单声道持续发送 512 采样点
的 float32 音频块。内置实时波形可视化和转写历史记录。

**进程 2 — FastAPI 主进程**：接收音频块，依次通过预处理管线、段验证、窗口化切分、
有界任务队列，由异步 Worker 将任务派发到 Wenet 子进程，拿到结果后回传前端并写日志。

**进程 3 — Wenet 子进程**：持久化运行的 GPU 推理进程。加载 Conformer-Transformer
模型，对每个传入的 WAV 路径做 fbank 特征提取与 CTC prefix beam search，返回 n-best
转写结果。

### Audio flow / 数据流转

```
chunk (512 samples)           segment (VAD output)         task (windowed slice)
      │                             │                           │
      ▼                             ▼                           ▼
[PreprocessPipeline] ──► [validate_segment] ──► [build_audio_tasks] ──► [AudioTaskQueue]
                                                                          │
                                                                          ▼
[Browser ◄── WebSocket]  ◄── [send_result] ◄── [TranscriptionWorker] ◄──┘
                                                    │
                                                    ▼
                                            [SubprocessTranscriber]
                                                    │
                                                    ▼
                                            [Wenet JSONL process]
```

## Pipeline Design / 管线设计

预处理管线是系统最核心的抽象。参照 scikit-learn 的设计哲学，所有预处理步骤被抽象为
统一的 `PreprocessStep` 协议。

### Step protocol / 步骤协议

```python
class PreprocessStep(Protocol):
    def process(self, data: AudioData) -> AudioData | None: ...
```

每个步骤接收一个 `AudioData` 数据包，返回修改后的同一数据包。返回 `None` 表示该数据包
不应该继续流向后续步骤，VAD 步骤利用这一机制过滤掉静音段。

### Step registry / 步骤注册机

```python
@register_step
class DCRemover:
    def process(self, data: AudioData) -> AudioData: ...
```

`@register_step` 装饰器将步骤类登记到全局注册表。Pipeline 在构造时校验每一步：
必须已注册、必须可调用、不允许重复。这套机制在工程初期就把配置错误拦截在启动阶段。

### Default pipeline / 默认管线

| 顺序 | 步骤 | 功能 | 关键参数 |
| --- | --- | --- | --- |
| 1 | `DCRemover` | DC 偏移移除 | — |
| 2 | `StreamingVadSegmenter` | 流式 VAD 语音分段 | threshold=0.35, min_silence=120ms, speech_pad=40ms, pre_speech=300ms |
| 3 | `RmsNormalizer` | RMS 响度归一化 | target=-23dB, max_gain=18dB |
| 4 | `AudioPeakLimiter` | 峰值限幅 | peak=0.95 |

### Optional steps / 可选用组件

| 步骤 | 功能 | 状态 |
| --- | --- | --- |
| `NoiseReducer` | 频谱降噪，利用 VAD 提取的噪声参考做 spectral gating | 已注册，当前未启用 |
| `PreEmphasis` | 预加重高通滤波 y[n]=x[n]-0.97·x[n-1] | 已注册，当前未启用 |

### Segment validation / 段验证门控

Pipeline 输出的语音段在进入任务队列前，经过两道验证：

- **最短时长门控**：段时长不小于 250ms，过滤过短的误检片段
- **最低响度门控**：段 RMS 不低于 -45dB，过滤静音误检

## Core Components / 核心组件

### VAD streamer / 流式语音活动检测

基于 Silero VAD 的 `VADIterator`，在 512 采样点粒度上实时判断语音起止。关键行为：

- 每个 chunk 喂入 VAD 迭代器，获得 `start` / `end` 事件
- `start` 触发时开始缓冲语音 chunk，同时保留 300ms 的前置静音作为噪声参考
- `end` 触发时拼接前置缓冲 + 全部语音 chunk，输出完整语音段
- 非语音期间的 chunk 被丢弃，Pipeline 中返回 `None`

### Windowing / 窗口化切分

对 VAD 输出的长语音段进行重叠切分，适配离线 CTC 解码的输入约束。默认参数：

- **窗口长度**：8000ms
- **步长**：6000ms
- **相邻窗口重叠**：2000ms
- **最小保留**：1200ms，短于此值的尾部直接丢弃

短于窗口长度的段作为单个任务发送，不做切分。

### Task queue / 有界任务队列

`asyncio.Queue` 封装，最大容量 3。溢出策略：

- `DROP_OLDEST`：丢弃队首任务，入队新任务，保证响应的时效性
- `DROP_NEWEST`：直接丢弃新任务，保留正在排队的旧任务

### Transcription worker / 转录 Worker

异步协程，核心逻辑：

```
while True:
    task = await queue.get()
    result = await asyncio.to_thread(transcriber.transcribe, task)
    await on_result(result)
```

`asyncio.to_thread` 将阻塞的 GPU 推理调用抛到线程池，保证 WebSocket 接收循环不被阻塞。
任务串行消费，避免 GPU 并发争抢。

### Subprocess backend / 子进程通信

Wenet 作为持久化子进程运行，JSONL 通信协议：

```
→ {"wav": "/tmp/tmpXXX.wav", "sample_rate": 16000}
← {"status": "ok", "text": "你好世界", "nbest_tokens": [[...], [...]], "nbest_scores": [...]}

→ {"command": "shutdown"}
```

关键技术细节：

- 启动时等待子进程输出 `{"status": "ready"}` 确认模型加载完成
- 每次转写创建临时 WAV 文件，完成后自动清理
- `threading.Lock` 保护 stdin/stdout 读写，防止多线程并发 I/O 导致的消息交错
- `selectors` 实现 ready 信号超时等待

### Structured logging / 结构化日志

`AsrResultLogger` 以异步队列驱动，按日输出 JSONL 文件到 `logs/` 目录。每条记录
包含完整 n-best 数据：

```json
{"type": "result", "segment_id": 0, "window_index": 0, "text": "你好", "nbest_tokens": [...], "nbest_scores": [...]}
{"type": "event", "event": "transcriber_ready", "backend": "wenet"}
```

## Quick Start / 快速开始

```bash
# 构建前端
cd frontend && npm install && npm run build

# 启动后端
cd backend && uv run python src/web_server.py
```

浏览器访问 `http://localhost:1557`，授权麦克风后开始实时转录。

主要依赖包括 FastAPI、Uvicorn、PyTorch、torchaudio、Wenet、Silero VAD、noisereduce、
NumPy、SciPy、soundfile、PyYAML。

## Project Structure / 项目结构

```text
real-time-asr/
├── frontend/                       # Vue 3 + Vite SPA / 前端
│   └── src/
│       ├── views/Home.vue          # Recording + live transcription UI
│       ├── views/History.vue       # Transcription history viewer
│       └── components/             # WaveformCanvas visualization
├── backend/                        # Python backend / 后端
│   ├── models/                     # Wenet checkpoint, config, tokenizer
│   │   ├── final.pt                # Trained model weights
│   │   ├── train.yaml              # Conformer-Transformer architecture
│   │   ├── units.txt               # 4233 Chinese character tokens
│   │   └── global_cmvn             # CMVN normalization stats
│   ├── scripts/
│   │   ├── wenet_serve.sh          # Subprocess launcher
│   │   └── wenet_serve.py          # JSONL Wenet server
│   └── src/
│       ├── web_server.py           # FastAPI entry + WebSocket handler
│       ├── preprocess/
│       │   ├── pipeline.py         # Pipeline orchestrator + validation
│       │   ├── types.py            # AudioData payload dataclass
│       │   └── steps/              # Individual preprocessing steps
│       ├── audio_queue/            # Bounded task queue + windowing
│       ├── transcription/          # ASR backend abstraction + Wenet bridge
│       ├── asr_logging/            # Daily JSONL structured logging
│       └── utils/                  # dB conversion, RMS computation
├── protocols/                      # Reserved for future protocol definitions
└── docs/
    └── future-plans.md             # Detailed roadmap and resources
```

## Limitations / 当前局限

- **Wenet 强绑定**：推理逻辑完全依赖 Wenet 的 `decode` 和 `detokenize`，无法独立演进。
- **离线 windowing**：当前的窗口化是为离线模型拼凑的流式方案，不是真正的流式解码。
  窗口间无上下文传递，结果直接拼接，没有重叠区域的多结果融合。
- **裸 WebSocket 传输**：前后端直接传输 float32 字节流，缺少消息类型、时间戳和元数据。
- **VAD 参数未调优**：Silero VAD 的阈值和时间参数使用默认值，未针对实际场景系统校准。
- **预处理参数未系统优化**：各步骤参数仅做了基本设置，缺少不同 SNR 条件下的系统性对比实验。
- **无标点恢复**：转写结果不含标点，影响可读性。
- **无说话人区分**：不支持多人对话场景的说话人日志。
- **中文限定**：当前模型仅训练了 4233 个中文字符的 token 表。

## Roadmap / 演进路线

### 阶段一：架构优化设计
重新审视并重构整个系统的模块边界。将当前的 Pipeline、队列、转录、日志四层进一步
抽象为更通用的服务接口，明确各层之间的数据契约和错误传播约定。为后续的多进程分离
和协议化打好地基。

### 阶段二：通信协议层与多进程分离
定义前后端及后端多进程间的标准化消息协议，替代裸 WebSocket 二进制传输。将 VAD、
降噪、转写等计算密集型模块拆分为独立进程，语音数据通过统一协议路由到正确的处理器。
这一步把当前「一个 Wenet 子进程」扩展为可编排的多处理器拓扑。

### 阶段三：真正的流式解码
实现滑动窗口 + 上下文传递 + 增量输出的流式识别，研究窗口边界的多结果融合策略。

### 阶段四：摆脱 Wenet 依赖
Wenet 退化为仅负责模型训练。自研 CTC/Attention 推理和字典 + RAG 模式的 N-best 校准。
模型架构也可以自己设计。

### 阶段五：预处理系统优化
在受限语音环境下，做系统的预处理参数调整实验。结合声波物理和傅里叶变换的理解，
探究预处理流程如何提升识别质量。

### 阶段六：双版本服务
- 服务器版：Redis 词典管理，多用户并发，GPU 调度
- 本地版：纯 CPU HMM 模型，轻量词典，低延迟优先

### 阶段七：语音分析扩展
基频提取、语调分类、情绪识别、声学特征可视化。

### 阶段八：VAD 研究与改进
深入理解 VAD 原理，针对自研模型特性做定制化改进。

### 阶段九：大模型接口预留
预留 LLM 调用接口，支持语音概要分析、质量问题评判等高层语义任务。

详细路线图及参考资源见 [docs/future-plans.md](docs/future-plans.md)。

## Third-party Resources / 第三方资源

| 资源 | 用途 | 许可证 |
| --- | --- | --- |
| **Wenet** | Conformer-Transformer ASR 框架，提供模型训练与 CTC 解码 | Apache 2.0 |
| **Silero VAD** | 流式语音活动检测，512 采样点粒度的实时分段 | MIT |
| **noisereduce** | 频谱门控降噪，预留给更完善的预处理管线 | MIT |
| **FastAPI + Uvicorn** | 异步 Web 服务框架与 ASGI 服务器 | MIT |
| **PyTorch + torchaudio** | 深度学习推理与音频 I/O | BSD |
| **Vue 3 + Vite** | 前端界面与构建工具 | MIT |

## License / 许可证
MIT License &mdash; 详见 [LICENSE](LICENSE)。

## 参考资料

- **[传统语音识别 GMM-HMM](https://jonathan-hui.medium.com/speech-recognition-gmm-hmm-8bb5eff8b196)**：利用高斯模型与隐马尔可夫模型进行编码和解码。
- **[Silero-vad](https://github.com/snakers4/silero-vad)**：语音活动检测 (Voice Activity Detection) 的优秀实现，参见 github 仓库。
- **[Sense Voice](https://github.com/FunAudioLLM/SenseVoice)**：开源高准确率语音识别模型调用库。
- **[Wenet](https://github.com/wenet-e2e/wenet)**：基于端到端的语音识别模型训练-启用综合框架。

---

<p align="center">
  <sub>一份从零开始的参考：追求高准确率的流式语音识别全链路，从声波到文字。</sub><br>
  <sub>A hand-written reference from scratch: the full streaming ASR pipeline, from sound waves to text.</sub>
</p>
