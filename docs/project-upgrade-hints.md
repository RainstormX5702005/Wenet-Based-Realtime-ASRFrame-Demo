# 系统架构设计与演进指南

本文档是项目的架构设计蓝图。面向我自己和 AI 编程助手：在开始任何代码修改前，必须先理解这里定义的五段管线设计、设计模式映射、协议分层和扩展嵌入点。

---

## 对 AI 的阅读指令

1. **不要直接删除或重写**：本仓库是起点框架，代码有留存价值。修改时先对照本文档确认该模块是在「保留」清单还是「替换」清单。
2. **五段管线拓扑不可破坏**：验证 → 波分析/真预处理 → 向量化/加窗分帧 → 解码/N-best校准 → 后处理。新功能必须嵌入已有阶段，不额外添加阶段或进程。
3. **协议先于实现**：消息类型定义（AudioChunk, ControlCommand, TranscriptionResult 等）是所有通信的基础，不可随意更改。
4. **设计模式驱动**：每个阶段有明确的设计模式约束，新功能必须遵循所在阶段的模式。
5. **配置必须可追溯**：所有参数调优的实验记录要能回溯到本文档的参数调优节。

---

## 一、五段管线设计

系统的核心处理链路分为五个逻辑阶段。每个阶段有明确的输入/输出契约和适用设计模式。

```
                         前置验证
                     Specification + Interceptor
                              │
                     ValidatedChunk (bypass 或 通过)
                              │
              ┌───────────────┴───────────────┐
              │       阶段二：波分析/真预处理    │
              │                               │
              │  ChainOfResp:                 │
              │  DC → [VAD] → [NoiseReduce]   │
              │       → RMS → Limiter          │
              │                               │
              │  Strategy: VAD算法可换         │
              │  State: VAD内部状态机          │
              │  Builder: 显式组装步骤         │
              └───────────────┬───────────────┘
                              │
                         AudioSegment
                              │
                         后置门控
                     Specification + NullObj
                              │
                     AudioSegment (accepted)
                              │
              ┌───────────────┴───────────────┐
              │       阶段三：向量化/加窗分帧   │
              │                               │
              │  Iterator: 滑动窗口遍历        │
              │  Windowing → Fbank/MFCC → CMVN │
              │                               │
              │  Strategy: 特征提取器可换      │
              │  Memento: 流式状态跨窗口传递   │
              └───────────────┬───────────────┘
                              │
                        FeatureSequence
                              │
              ┌───────────────┴───────────────┐
              │       阶段四：解码/N-best校准   │
              │                               │
              │  TemplateMethod:              │
              │  Encoder→Decoder→LM→Dict→Detok │
              │                               │
              │  Strategy: 整个后端可换        │
              │  Proxy: GPU进程隔离            │
              │  Memento: beam state传递       │
              └───────────────┬───────────────┘
                              │
                        RawText + NBest
                              │
              ┌───────────────┴───────────────┐
              │       阶段五：后处理            │
              │                               │
              │  ChainOfResp:                 │
              │  标点→ITN→RAG→字典→NER→格式化   │
              │                               │
              │  Strategy: 每步实现可换        │
              │  NullObj: Dummy占位            │
              │  Pub-Sub: 多消费者分发         │
              └───────────────┬───────────────┘
                              │
                         FinalOutput
```

### 阶段一：验证 (Validation Gate)

**职责**：音频进入管线前，判断「该不该处理」。验证分两层：

**前置验证（轻量，Pre-Validation）**：每个 chunk 进来就做，快速拒绝。

| 检查项 | 说明 |
|---|---|
| 采样率校验 | 必须是 16kHz，否则拒收或重采样 |
| 通道数校验 | mono only，多声道→混音或报错 |
| 信号存在性 | 静音 chunk（`rms_db < -60`）直接丢弃 |
| 认证/授权 | 连接是否合法（当前没有，预留） |

**后置门控（质量，Post-Gating）**：预处理完成后做，验证语音段质量。

| 检查项 | 说明 |
|---|---|
| 最短时长 | 段时长 ≥ 250ms，过滤过短的误检片段 |
| 最低响度 | 段 RMS ≥ -45dB，过滤静音误检 |
| 可扩展 | VAD confidence ≥ 0.5 等 |

**适用模式**：

| 模式 | 怎么用 |
|---|---|
| **规约模式 (Specification)** | 每个检查拆成独立规则对象：`SampleRateRule(16000)`, `MinRMSRule(-60dB)`。可以 `&` 组合，可以单独测试。优于当前 `validate_segment` 里硬编码的 if/else |
| **空对象/门控** | 不通过的 chunk 不是抛异常，而是返回 `RejectedChunk(reason="too_quiet")`。上游收到后直接跳过，不进入预处理 |
| **拦截器链** | 规则按序执行，第一个失败就短路，不继续检查 |
| **装饰器** | 给 validate 函数挂 `@log_rejection` 记录被拒原因分布 |

---

### 阶段二：波分析与真预处理 (Wave Analysis & Real Preprocessing)

**职责**：在波形层面增强语音信号，决定是否输出完整语音段。

**关键设计决策**：VAD 是预处理管线的一个**可选步骤**，不是独立进程。VAD 的 ON/OFF 决定了管线运行在流式模式还是批量模式：

```
VAD=ON (批量模式):
  chunk → DC移除 → [VAD积攒] → 语音段完整 → RMS归一 → 限幅 → 输出段

VAD=OFF (流式模式):
  chunk → DC移除 → RMS归一 → 限幅 → 逐chunk输出
```

**默认步骤链**：

| 步骤 | 做什么 | 可替换性 |
|---|---|---|
| DC 偏移移除 | 减去均值，消除直流分量 | 基本不用换 |
| VAD 语音活动检测 | Silero VAD 状态机，积攒 chunk，判断 speech start/end | **核心策略点**：Silero → 自研能量+频谱双门控 → WebRTC VAD |
| 噪声抑制 | 频谱门控降噪（当前未启用），需要 VAD 提供的 noise_reference | 可选，算法可换 |
| RMS 归一化 | 调节响度到目标 dB | 参数可调，算法基本固定 |
| 峰值限幅 | 硬截断到 ±0.95 | 基本不用换 |
| 预加重 | y[n]=x[n]-0.97x[n-1] | 可选 |

**适用模式**：

| 模式 | 怎么用 |
|---|---|
| **责任链 (Chain of Resp.)** | 每个步骤接收 `AudioData`，处理后传给下一个。任一步骤可返回 `None` 中断链 |
| **策略模式 (Strategy)** | **VAD 是最关键的策略点**：`SileroVAD` / `EnergySpectralVAD` / `WebRTCVAD`，都实现 `VADStrategy.process(chunk) → event`。降噪、归一化同理 |
| **建造者模式 (Builder)** | 显式组装步骤链，**不用全局装饰器注册**：`PipelineBuilder().add(DC()).add(VAD(silero)).add(RMS()).add(Limiter()).build()` |
| **状态模式 (State)** | VAD 内部状态机：`Silence → PreSpeech → Speaking → End`。每个状态对 chunk 的处理不同 |
| **空对象** | VAD 处在 silence 时返回 None，中断后续步骤 |

**Pipeline 构建方式改进**：

当前使用 `@register_step` 全局装饰器注册 + 构造时校验。目标改为 Builder 模式显式组装：

```python
# 当前（装饰器魔法）
@register_step
class DCRemover: ...

# 目标（Builder 显式组装）
pipeline = (
    PipelineBuilder()
    .add(DCRemover())
    .add(VADSegmenter())          # 可选
    .add(RmsNormalizer())
    .add(Limiter())
    .build()
)
```

`@register_step` 可以被一个简单的 `isinstance` + Protocol 检查替代，不需要全局状态。

---

### 阶段三：向量化编码与加窗分帧 (Vectorization, Windowing & Framing)

**职责**：从波形信号提取声学特征，切分为模型可消费的帧序列。

**为什么独立为阶段**：当前 Wenet 的 `compute_feature` 把 fbank 绑死在 Wenet 模型里。提出来之后：

```
阶段二输出: AudioSegment (float32 numpy array)
                │
阶段三处理:     ├─ Windowing (滑动窗口切分)
                ├─ FbankExtractor / MFCCExtractor (可切换)
                └─ CMVN (全局均值方差归一化)
                │
阶段四输入: FeatureSequence (shape: [T, F] 的特征矩阵)
```

好处是换 ASR 后端时（阶段四从 Wenet 换成自研），阶段三不需要改。反之亦然——换特征提取策略不影响解码端。

**具体操作**：

| 操作 | 说明 |
|---|---|
| **加窗分帧** | 语音段切分为重叠的窗口/帧。流式模式下用滑动窗口 + 状态传递 |
| **特征提取** | fbank（当前 Wenet 用）或 MFCC。可替换 |
| **特征归一化** | CMVN（倒谱均值方差归一化），用 `global_cmvn` 统计量 |
| **Spec Augmentation** | 训练时用的，推理不需要 |

**适用模式**：

| 模式 | 怎么用 |
|---|---|
| **策略模式** | 特征提取器可切换：`FbankExtractor` / `MFCCExtractor` / 自定义 |
| **迭代器模式** | 滑动窗口遍历语音段，每次 yield 一帧 |
| **备忘录模式** | 流式解码时，保存当前窗口的编码器状态和 beam 状态，传递给下一个窗口 |
| **适配器** | 不同 ASR 后端可能要求不同的特征格式，适配器做转换 |

---

### 阶段四：解码与 N-best 输出校准 (Decoding & N-best Calibration)

**职责**：声学特征 → 文本，输出带置信度的 N 条候选。

**这是最重的一步，也是未来改动最多的地方。Strategy 模式的核心战场。**

```
FeatureSequence
    │
    ▼
┌──────────────┐
│ Encoder      │  ← Conformer/Transformer，未来可自研
└──────┬───────┘
       │ encoder_output
       ▼
┌──────────────┐
│ Decoder      │  ← CTC prefix beam search / WFST / Attention
└──────┬───────┘
       │ nbest (tokens + scores)
       ▼
┌──────────────┐
│ LM Rescoring │  ← KenLM / RNNLM 重打分
└──────┬───────┘
       │ rescored nbest
       ▼
┌──────────────┐
│ Dictionary   │  ← 领域词典约束：不在词典里的词惩罚
│ Constraint   │
└──────┬───────┘
       │ calibrated nbest
       ▼
┌──────────────┐
│ Detokenize   │  ← tokens → text
└──────┬───────┘
       │
       ▼
RawText + NBest

Strategy 可切换层:
  Encoder:   WenetEncoder / CustomEncoder / TorchScriptEncoder
  Decoder:   WenetCTC / CustomCTC / WFSTDecoder / HMMDecoder
  LM:        KenLM / None / RNNLM
  Dictionary: DomainDict / EmptyDict
```

**适用模式**：

| 模式 | 怎么用 |
|---|---|
| **策略模式** | 整个 ASR 后端是一个策略。`WenetBackend` / `CustomCTCBackend` / `HMMBackend`，都实现同一个 `transcribe(features) → NBest` 接口 |
| **模板方法** | `encode → decode → rescore → detokenize` 骨架固定，每步的算法可替换 |
| **代理模式** | GPU 推理在独立进程/线程，调用方不感知进程边界，只面对一个本地对象 |
| **备忘录** | 流式解码时，存 `encoder_cache` + `beam_state`，跨窗口传递。这是实现真正流式的关键 |

---

### 阶段五：后处理 (RAG / NLP字典 / 标点 / ITN)

**职责**：把 N-best 和最优文本变成面向用户的最终输出。

```
RawText + NBest
    │
    ├──→ 标点恢复 (Punctuation)         ← "你好世界" → "你好，世界。"
    ├──→ 逆文本归一化 (ITN)             ← "一百二十三" → "123"
    ├──→ RAG 上下文校准                 ← 结合对话历史调整 N-best 排序
    ├──→ NLP 字典匹配                   ← "ASR" → "自动语音识别"
    ├──→ 命名实体识别 (NER)             ← 标记人名、地名
    └──→ 文本格式化                     ← 最终输出
```

**适用模式**：

| 模式 | 怎么用 |
|---|---|
| **责任链** | 每个后处理步骤串联：`[标点] → [ITN] → [RAG] → [字典] → [NER] → [格式化]` |
| **策略模式** | 每个步骤都是可替换策略：`BertPunctuator` / `RulePunctuator` / `NonePunctuator` |
| **空对象** | 未实现的功能用空对象占位：`DummyPunctuator`（原样返回），`DummyAnalyzer`（LLM 预留） |
| **发布-订阅** | 一份结果推给多个消费者：前端显示、日志写盘、LLM 分析、指标统计 |

---

## 二、协议分层设计

系统需要两层协议：**网络协议**（前后端通信）和**进程间协议**（后端内部通信）。

### 核心原则：消息类型复用，传输层分离

```
┌─────────────────────────────────────────────────────────────┐
│                    同一套 Message 定义                        │
│                                                             │
│  AudioChunk  │  ControlCommand  │  TranscriptionResult  │    │
│  (音频块)     │  (控制指令)       │  (转写结果)            │    │
│  SpeakerEmbed│  EmotionResult   │  LLMAnalysis          │    │
│  (声纹向量)   │  (情绪分析)       │  (大模型分析)          │    │
└──────────┬─────────────────────────────────────┬────────────┘
           │                                     │
           ▼                                     ▼
┌──────────────────────┐              ┌──────────────────────┐
│   Protocol A         │              │   Protocol B         │
│   Network Protocol   │              │   IPC Protocol       │
│   (前后端通信)        │              │   (后端进程间通信)     │
│                      │              │                      │
│ Transport:           │              │ Transport:           │
│  WebSocket / WebRTC  │              │  Pipe / SharedMemory │
│                      │              │  / ZeroMQ / Queue    │
│ Layer 7 concerns:    │              │ Layer 7 concerns:    │
│  • Auth (JWT/Token)  │              │  • No auth (trusted) │
│  • Encryption (TLS)  │              │  • No encryption     │
│  • Reconnection      │              │  • Process lifecycle │
│  • Rate limiting     │              │  • Backpressure      │
│  • Session mgmt      │              │  • Zero-copy (audio) │
│  • Compression       │              │  • Health check      │
│                      │              │                      │
│ Patterns:            │              │ Patterns:            │
│  Bridge (transport)  │              │  Bridge (transport)  │
│  Adapter (auth wrap) │              │  Mediator (routing)  │
│  Decorator (retry)   │              │  Pub-Sub (fanout)    │
│  Interceptor (限流)   │              │  Command (dispatch)  │
└──────────────────────┘              └──────────────────────┘
```

**为什么消息类型定义复用**：`AudioChunk` 在前端发过来是一个 JSON/MessagePack 包，在进程间传输可能是共享内存指针 + 元数据。但 `AudioChunk` 的**语义**（采样率、时间戳、样本数据）完全相同。变的是序列化方式和传输载体，不变的是消息本身的含义。这就是 **Bridge 模式**——抽象（Message）与实现（Transport）分离。

**Ingress 进程充当边界适配器**：它收到 Protocol A 的消息 → 验证 auth → 去掉传输层头部 → 转为 Protocol B 的消息 → 投递到 MessageBus。反向亦然。

### 消息类型定义

```python
# protocols/messages.py

@dataclass
class AudioChunk:       # 前端 → 后端
    chunk_id: int
    samples: bytes       # float32 序列化
    timestamp_ms: int
    sample_rate: int = 16000

@dataclass
class ControlCommand:   # 前端 ↔ 后端
    command: str         # "start" | "stop" | "pause" | "resume"
    params: dict

@dataclass
class TranscriptionResult:  # 后端 → 前端
    segment_id: int
    window_index: int
    text: str
    is_final: bool
    confidence: float

@dataclass
class SpeakerEmbed:     # 阶段三 → 阶段五
    segment_id: int
    embedding: bytes     # 声纹向量
    timestamp_ms: int

@dataclass
class EmotionResult:    # 阶段二 → 阶段五
    segment_id: int
    emotion: str         # "neutral" | "positive" | "negative"
    confidence: float
    timestamp_ms: int

@dataclass
class LLMAnalysis:      # 阶段五内部
    segment_id: int
    summary: str
    keywords: list[str]
    quality_score: float
```

---

## 三、消息总线 (Message Bus / Mediator)

**职责**：所有后端进程只和 MessageBus 通信，不直接互连。

```
┌─────────────────────────────────────────────────────────────────────┐
│                           MESSAGE BUS                               │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐     │
│  │ Router       │  │ Pub-Sub      │  │ Lifecycle Manager      │     │
│  │              │  │              │  │                        │     │
│  │ AudioChunk→  │  │ Result →     │  │ start(Logger→ASR→...) │     │
│  │  Preprocess  │  │   [WS,Log,   │  │ stop(reverse)          │     │
│  │ ControlCmd→  │  │    LLM,      │  │ health_check(1s)       │     │
│  │  Capture     │  │    Analysis] │  │ on_dead → restart      │     │
│  └──────────────┘  └──────────────┘  └────────────────────────┘     │
│                                                                     │
│  Patterns: Mediator, Observer/Pub-Sub, Registry, State              │
└─────────────────────────────────────────────────────────────────────┘
```

**路由表（Protocol B 层）**：

```
MessageBus 路由表（Protocol B 层）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AudioChunk           → Preprocess
ControlCommand       → Ingress (自己处理)
AudioSegment         → Vectorization
FeatureSequence      → ASR
RawText + NBest      → Postprocess
SpeakerEmbed (声纹)   → SpeakerDB (存储) + Postprocess (关联)
EmotionResult        → Postprocess (随结果一起推前端)
LLMAnalysis          → Egress (推前端)
```

---

## 四、多进程架构：逻辑视图与部署视图

### 逻辑架构（组件 = 做什么）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PROTOCOL LAYER                               │
│                                                                     │
│  Message Types (定义消息，不定义传输):                                │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐               │
│  │ AudioChunk  │  │ ControlCmd   │  │ TransResult   │  ...          │
│  │ samples     │  │ start/stop   │  │ text+nbest    │               │
│  │ timestamp   │  │ pause/resume │  │ confidence    │               │
│  │ format      │  │ params       │  │ segment_id    │               │
│  └─────────────┘  └──────────────┘  └───────────────┘               │
│                                                                     │
│  Transports (实现层，可插拔):                                        │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────────┐     │
│  │ WebSocket │  │ WebRTC    │  │ Pipe      │  │ SharedMemory │     │
│  └───────────┘  └───────────┘  └───────────┘  └──────────────┘     │
│                                                                     │
│  Patterns: Bridge (Message ↔ Transport 分离)                         │
│            Adapter (TransportAdapter 统一接口)                       │
│            Command (每个 Message 是命令对象)                         │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                           MESSAGE BUS                               │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐     │
│  │ Router       │  │ Pub-Sub      │  │ Lifecycle Manager      │     │
│  │              │  │              │  │                        │     │
│  │ AudioChunk→  │  │ Result →     │  │ start(Logger→ASR→...) │     │
│  │  Preprocess  │  │   [WS,Log,   │  │ stop(reverse)          │     │
│  │ ControlCmd→  │  │    LLM,      │  │ health_check(1s)       │     │
│  │  Capture     │  │    Analysis] │  │ on_dead → restart      │     │
│  └──────────────┘  └──────────────┘  └────────────────────────┘     │
│                                                                     │
│  Patterns: Mediator, Observer/Pub-Sub, Registry, State              │
└─────────────────────────────────────────────────────────────────────┘

        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   INGRESS     │   │  PREPROCESS   │   │   EGRESS      │
│               │   │               │   │               │
│ • 接入层       │   │ • 语音增强    │   │ • 结果分发    │
│ • 认证         │   │ • 活动检测    │   │ • 日志记录    │
│ • 编解码       │   │ • 响度归一    │   │ • 标点恢复    │
│ • 缓冲/反压    │   │ • 噪声抑制    │   │ • 文本后处理  │
│               │   │ • 门控验证    │   │ • LLM分析     │
│               │   │               │   │               │
│ Patterns:     │   │ Patterns:     │   │ Patterns:     │
│ Adapter       │   │ ChainOfResp   │   │ Pub-Sub       │
│ State         │   │ Strategy      │   │ ChainOfResp   │
│ Interceptor   │   │ Builder       │   │ Strategy      │
│ Command       │   │ Spec          │   │ NullObj       │
│               │   │ NullObj       │   │               │
└───────┬───────┘   └───────┬───────┘   └───────────────┘
        │                   │                   ▲
        │           ┌───────┴───────┐           │
        │           │   VAD         │           │
        │           │  ┌─────────┐  │           │
        │           │  │ ON:     │  │           │
        │           │  │ 积攒→整段│  │           │
        │           │  │ OFF:    │  │           │
        │           │  │ 直通chunk│  │           │
        │           │  └─────────┘  │           │
        │           └───────┬───────┘           │
        │                   │                   │
        │                   ▼                   │
        │           ┌───────────────┐           │
        │           │     ASR       │           │
        │           │               │           │
        │           │  ┌─────────┐  │           │
        │           │  │Strategy:│  │           │
        │           │  │ Wenet   │  │───────────┘
        │           │  │ Custom  │  │
        │           │  │ HMM     │  │
        │           │  └─────────┘  │
        │           │               │
        │           │ • Windowing   │
        │           │ • fbank       │
        │           │ • Encoder     │
        │           │ • Decoder     │
        │           │ • LM rescore  │
        │           │ • N-best      │
        │           │               │
        │           │ Patterns:     │
        │           │ Strategy      │
        │           │ Template      │
        │           │ Memento       │
        │           │ Proxy         │
        │           │ Prod-Cons     │
        │           └───────────────┘

                    ┌───────────────┐
                    │   ANALYZER    │  (Phase 7 语音分析)
                    │               │
                    │ • F0 提取     │
                    │ • 语调分类    │
                    │ • 情绪识别    │
                    │ • 语速统计    │
                    │               │
                    │ Uses: 原始音频 │
                    │ Patterns:     │
                    │ Strategy      │
                    │ Blackboard    │
                    └───────────────┘
```

### 部署视图（逻辑组件 → 物理进程的映射）

同一个逻辑架构，两种部署密度：

**部署 A：本地版（2-3 进程）**

```
Process 1:  [Ingress + Preprocess + Egress]
Process 2:  [ASR (HMM, CPU)]
Process 3:  [Logger] (可选独立)
```

**部署 B：服务器版（5-6 进程）**

```
Process 1:  Ingress (WebSocket/WebRTC, auth, rate-limit)
Process 2:  Preprocess (VAD, enhance, validate)
Process 3:  ASR (GPU, Wenet/Custom)
Process 4:  Egress (fan-out, postprocess, WS send)
Process 5:  Analyzer (F0, emotion, intonation)
Process 6:  Logger (JSONL, metrics)
```

**关键**：MessageBus 在部署 A 中是进程内的 asyncio Queue 集合；在部署 B 中是独立的 Router 进程或基于 ZeroMQ/Redis 的 Broker。但组件代码不变——只有 Bus 的实现不同。

---

## 五、扩展嵌入点

新功能如何嵌入现有五段管线，**不添加新阶段、不添加新进程**：

```
                        前置验证
                             │
              ┌──────────────┴──────────────┐
              │     阶段二：波分析/真预处理    │
              │                              │
              │  DC → VAD → NoiseReduce      │
              │       → RMS → Limiter        │
              │                              │
              │  ┌────────────────────────┐  │
              │  │ ★ 波情感分析（声学层）  │  │  ← 新：并行分支
              │  │ F0, energy, speech_rate│  │
              │  │ 需要原始波形，不依赖文本 │  │
              │  │ Pattern: Strategy      │  │
              │  └────────┬───────────────┘  │
              │           │ EmotionResult    │
              │           │ → MessageBus     │
              └───────────┼──────────────────┘
                          │
                     AudioSegment
                          │
                     后置门控
                          │
              ┌───────────┴──────────────────┐
              │     阶段三：向量化/加窗分帧    │
              │                               │
              │  Windowing → Fbank → CMVN     │
              │                               │
              │  ┌─────────────────────────┐  │
              │  │ ★ 人声色检测（声纹层）   │  │  ← 新：并行分支
              │  │ Speaker Embedding       │  │
              │  │ 与 fbank 共享输入音频     │  │
              │  │ 输出声纹向量 + 时间戳     │  │
              │  │ Pattern: Strategy       │  │
              │  └────────┬────────────────┘  │
              │           │ SpeakerEmbed      │
              │           │ → MessageBus      │
              └───────────┼──────────────────┘
                          │
                     FeatureSequence
                          │
              ┌───────────┴──────────────────┐
              │     阶段四：解码/N-best校准    │
              │  Encoder→Decoder→LM→Dict     │
              └───────────┬──────────────────┘
                          │
                     RawText + NBest
                          │
              ┌───────────┴──────────────────┐
              │     阶段五：后处理             │
              │                               │
              │  标点 → ITN → RAG → 字典 → NER │
              │                               │
              │  ┌─────────────────────────┐  │
              │  │ ★ 大模型响应接口          │  │  ← 新：责任链步骤
              │  │ 输入：转写文本             │  │
              │  │ 输出：摘要/质量/关键词     │  │
              │  │ Pattern: Strategy +      │  │
              │  │  NullObj (Dummy占位)     │  │
              │  └─────────────────────────┘  │
              │                               │
              │  ┌─────────────────────────┐  │
              │  │ ★ 情绪+声纹结果融合       │  │  ← 新：Pub-Sub订阅
              │  │ 订阅 EmotionResult +      │  │
              │  │  SpeakerEmbed + Text     │  │
              │  │ 组装多模态分析结果         │  │
              │  │ Pattern: Pub-Sub         │  │
              │  └─────────────────────────┘  │
              └───────────────────────────────┘
```

### 逐项分析

| 新功能 | 插入位置 | 是否需要新阶段 | 是否需要新进程 |
|---|---|---|---|
| 波情感分析 | 阶段二（并行分支） | 否 | 否 |
| 人声色检测 | 阶段三（并行特征提取） | 否 | 否 |
| 大模型接口 | 阶段五（责任链步骤） | 否 | 否 |
| 多模态结果融合 | 阶段五（Pub-Sub 订阅） | 否 | 否 |

**波情感分析 — 插入阶段二**

需要什么：原始波形（F0、能量、语速）。这些在阶段二都有——VAD 前后的音频就是最干净的信号源。

怎么加：在阶段二的 Pipeline 中增加一个并行分析步骤。它不是责任链的一环（不修改 AudioData），而是**观察者**——收到音频后异步计算情感特征，结果走 MessageBus 投递到阶段五。

**人声色检测与分离 — 插入阶段三**

需要什么：说话人声纹嵌入。和 fbank 一样，输入是原始音频段。

怎么加：在阶段三，和 fbank 共享同一个 AudioSegment 输入。声纹提取器作为 Strategy 的另一个实现——`FbankExtractor` 和 `SpeakerEmbedExtractor` 并行运行或串行运行。声纹结果（谁在什么时候说话）走 MessageBus。

**大模型响应接口 — 插入阶段五末尾**

需要什么：转写文本。

怎么加：阶段五责任链的最后一步。`LLMAnalyzer.analyze(text) → summary`。Strategy 模式：`OllamaAnalyzer` / `OpenAIAnalyzer` / `DummyAnalyzer`。Dummy 在未部署 LLM 时原样返回。

**跨阶段结果融合 — MessageBus 的 Pub-Sub 能力**

情绪结果在阶段二产生，声纹结果在阶段三产生，转写文本在阶段五产生。如何把它们关联成一条「带声纹标记的、带情绪标签的转写结果」？

这就是 MessageBus 的 Pub-Sub 做的事——阶段五订阅所有相关消息类型：

```
Postprocess (阶段五) 的订阅列表:
  • TranscriptionResult    ← 阶段四发来
  • EmotionResult          ← 阶段二发来 (同 segment_id)
  • SpeakerEmbed           ← 阶段三发来 (同 segment_id)

当同 segment_id 的三条消息到齐:
  → 组装 FinalOutput {
      text: "你好世界",
      speaker: "Speaker_A (85% confidence)",
      emotion: "中性偏积极 (F0平稳, 能量正常)",
      llm_summary: "..."
    }
```

---

## 六、设计模式总览

### 当前代码中已存在的全部模式

| 模式 | 代码证据 | 说明 |
|---|---|---|
| **责任链** | `pipeline.py:71-88` 的步骤循环，每个 Step 可返回 None 中断 | 核心管线模式 |
| **策略模式** | `PreprocessStep` 协议 + 多个 Step 实现互换 | 步骤可替换 |
| **装饰器模式** | `@register_step`, `@dataclass(frozen=True)`, `@asynccontextmanager`, `@app.websocket("/ws")`, `@abstractmethod`, `@staticmethod` | Python `@` 语法就是原生装饰器 |
| **状态模式** | `StreamingVadSegmenter._speaking` (vad_streamer.py:45), `_audio_chunks` / `_prev_chunks` 缓冲区 | VAD 内部状态机 |
| **协议模式** | `class PreprocessStep(Protocol)` (steps/base.py:10) | 结构化类型，不要求显式继承 |
| **值对象/不可变** | 所有 `@dataclass(frozen=True)` 类型：`AudioTask`, `TranscriptionResult`, `RawTranscriptionResult`, 全部 Config 类 | 线程安全、可哈希 |
| **上下文对象** | `AudioData.metadata: dict[str, Any]` (types.py:20) | 可扩展元数据容器 |
| **规约模式** | `validate_segment()` (pipeline.py:106-128) 中的 `min_speech_duration_ms` 和 `min_active_rms_db` 检查 | 可组合规则 |
| **空对象/门控** | `AudioData.accepted=False` + `reason` + `samples=[]` (pipeline.py:115-118) | 不用异常传递拒绝语义 |
| **模板方法** | `BaseTranscriber(ABC)` 定义 `transcribe`/`close` 契约 | 骨架固定 |
| **工厂方法** | `create_transcriber()` (factory.py:26) | 简单工厂 |
| **代理模式** | `SubprocessTranscriber` 是 Wenet 子进程的本地代理 | 隔离进程边界 |
| **外观模式** | `process_chunk()` 包装 AudioData 构造 + process + validate | 简化接口 |
| **生产者-消费者** | `AudioTaskQueue` + `TranscriptionWorker` | 异步队列 |
| **反压** | `asyncio.Queue(maxsize=3)` + `DROP_OLDEST` | 有界队列 |
| **观察者/回调** | `ResultCallback` | 结果通知 |
| **注册表** | `REGISTERED_STEP_TYPES` 全局集合 + `is_registered()` | 编译期校验 |

### 协议引入后催生的模式

| 协议引入后催生的模式 | 具体场景 |
|---|---|
| **适配器** | `AudioChunk(bytes)` → `AudioData(ndarray)`，协议消息 ↔ 领域对象互转 |
| **命令模式** | 每个消息类型是一个命令对象：`StartCapture`, `StopCapture`, `AudioChunk`, `TranscriptionResult`。接收方根据 `message.type` 分派 |
| **访问者/分派** | `MessageDispatcher.dispatch(message)` → 根据类型找到注册的 handler |
| **发布-订阅 (完整版)** | 一个 `TranscriptionResult` 同时推给 WebSocket、Logger、LLMAnalyzer |
| **桥接模式** | 分离消息类型的抽象层次（语义）与传输实现（WebSocket / Pipe / SharedMemory） |
| **备忘录** | 序列化进程状态（VAD 的 buffer、ASR 的 encoder state），支持崩溃恢复 |
| **装饰器模式（扩展）** | `@message_handler("audio_chunk")`, `@retry(3)`, `@timeout(5s)`, `@log_latency` 注解在 handler 上 |
| **拦截器/过滤器链** | 每条消息经过一组中间件：`[解密] → [校验] → [日志] → [实际处理]` |

---

## 七、分阶段升级指南

### 阶段一：架构优化设计

**目标**：先把骨架抽象干净，再做功能扩展。

**具体任务**：

1. 把 `web_server.py` 的 lifespan 拆出来，变成独立的服务组装模块。

```python
# 当前：所有组件在 lifespan 里硬编码组装
# 目标：独立的 ServiceContainer 或 AppBuilder
class AppBuilder:
    def __init__(self, config: AppConfig): ...
    def build_pipeline(self) -> PreprocessPipeline: ...
    def build_transcriber(self) -> BaseTranscriber: ...
    def build_queue(self) -> AudioTaskQueue: ...
    def assemble(self) -> FastAPI: ...
```

2. 统一配置管理。当前各模块的 dataclass 散落在各自文件中，需要收敛到一个配置系统：

```python
# 所有配置从一个 YAML 文件加载
@dataclass
class AppConfig:
    preprocess: PreprocessConfig
    vad: StreamingVadConfig
    rms: RmsNormalizerConfig
    limiter: PeakLimiterConfig
    windowing: WindowingConfig
    queue: AudioTaskQueueConfig
    transcriber: TranscriberFactoryConfig
    log: AsrLogConfig
```

3. **Pipeline 构建方式改进**：从 `@register_step` 装饰器注册改为 Builder 模式显式组装。

4. 这一步**不改变任何运行时行为**，只做结构重构。重构完成后 pytest 必须全绿。

**判断完成的标准**：`web_server.py` 不超过 60 行，lifespan 逻辑移出到独立模块。

---

### 阶段二：通信协议层与多进程分离

**目标**：建立标准化的通信层，支撑前后端及后端多进程间的语音数据传输。

**具体任务**：

1. 定义协议消息类型（见本文档「协议分层设计」节）。

2. 实现 MessageBus：
   - Router：根据消息类型路由到目标进程
   - Pub-Sub：支持一对多分发
   - Lifecycle Manager：进程启动/停止/健康检查

3. 把 VAD 作为预处理管线的可选策略步骤，支持 ON/OFF 切换。

4. 把特征提取（fbank/MFCC）从 Wenet 子进程中提出来，成为独立的阶段三。

**判断完成的标准**：VAD 可独立启用/禁用，消息通过协议路由，特征提取不依赖 Wenet。

---

### 阶段三：真正的流式解码

**目标**：让转写结果在音频流入的同时增量输出。

**具体任务**：

1. 深入研究 Wenet 的 `decode_chunk` 方法。这是 Wenet 原生的流式解码接口，返回值是逐帧的 CTC 输出。

```python
# Wenet 流式解码的关键步骤（伪代码）
encoder_out, encoder_mask = model.encoder(chunk, ...)
ctc_log_probs = model.ctc(encoder_out)
# 对 ctc_log_probs 做 prefix beam search
# 保留 beam 状态用于下一个 chunk
```

2. 替换 `build_audio_tasks` 的离线窗口化逻辑。滑动窗口的关键是保留上一个窗口的编码器状态和 beam 状态（**备忘录模式**）。

```
窗口1: [0, 8000ms] → encoder_state_1, beam_state_1 → "你好"
窗口2: [6000ms, 14000ms] → 复用 encoder_state_1 的重叠部分 → "好世界"
合并: "你好世界"
```

3. 重叠区域的结果融合。最简单策略：比较两个窗口在重叠区的 token 序列，取置信度高的。

**判断完成的标准**：长语音段的第一个字在说完后 500ms 内出现，而不是等整个段结束。

---

### 阶段四：摆脱 Wenet 依赖

**目标**：Wenet 只用于训练，推理完全自研。

**具体任务**：

1. 先从最简单的替换开始：把 `wenet_serve.py` 换成自己写的解码服务，复用 JSONL 通信协议。

```python
# 自研解码服务的骨架
class DecodeServer:
    def __init__(self, model_path: str, dict_path: str, lm_path: str | None):
        self.model = load_my_model(model_path)
        self.tokenizer = load_tokenizer(dict_path)
        self.lm = load_kenlm(lm_path) if lm_path else None

    def handle_request(self, wav_path: str, sample_rate: int) -> dict:
        features = compute_fbank(wav_path, sample_rate)
        encoder_out = self.model.encoder(features)
        nbest = ctc_prefix_beam_search(encoder_out, self.tokenizer, beam_size=10)
        if self.lm:
            nbest = lm_rescore(nbest, self.lm)
        return {"status": "ok", "text": nbest[0].text, "nbest_tokens": ..., "nbest_scores": ...}
```

2. 实现最小可用的 CTC prefix beam search。不需要从头写，可以研究 Wenet 源码的 `ctc_prefix_beam_search` 函数，理解后再自己实现。

3. 字典 + RAG 的 N-best 校准。当有领域词典时，对 n-best 候选做约束解码或 rescoring：

```python
def rag_rescore(nbest: list, dictionary: set[str], context: str) -> list:
    """对 n-best 列表做字典约束重打分"""
    for hyp in nbest:
        tokens = hyp.tokens
        # 1. 字典约束：惩罚不在词典中的词
        # 2. 上下文 RAG：奖励与上下文语义一致的候选
        hyp.score += dictionary_bonus(tokens, dictionary)
        hyp.score += context_bonus(tokens, context)
    return sorted(nbest, key=lambda h: h.score, reverse=True)
```

**判断完成的标准**：`TranscriberFactoryConfig.backend` 可以设为 `"wenet"` 或 `"custom"`，两者输出结果格式一致。

---

### 阶段五：预处理系统优化

**目标**：在受限语音环境下系统调参。

**具体任务**：

1. 先建立评估基准。准备一批带标注的测试音频，覆盖不同的 SNR 条件。

2. 用网格搜索做参数调优：

```python
# 参数搜索空间
param_grid = {
    "vad_threshold": [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5],
    "vad_min_silence_ms": [80, 120, 160, 200, 300],
    "pre_emphasis_coeff": [0.0, 0.90, 0.95, 0.97, 0.99],
    "rms_target_db": [-30, -26, -23, -20, -16],
    "rms_max_gain_db": [12, 18, 24, 30],
    "noise_reduce_prop_decrease": [0.5, 0.6, 0.7, 0.8, 0.9],
}
```

3. 关键洞察：参数的排列组合指数爆炸。不要全量网格搜索，先用一组默认参数做单变量控制实验，确定每个参数的敏感度排序，再对前 3 个最敏感的参数做细粒度搜索。

4. 噪声类型对预处理策略有决定性影响。白噪声和粉红噪声的最佳预处理不同，建议实验时分类记录。

**判断完成的标准**：有至少两组 SNR 条件下、通过调参使得 WER 都有显著下降的实验记录。

---

### 阶段六：双版本服务

**目标**：同一套 Pipeline 架构，两种部署形态。

**具体任务**：

1. 服务器版的 `BaseTranscriber` 实现与本地版不同，但共享 Pipeline 和 `AudioTaskQueue`。

```python
# 服务器版
class ServerTranscriber(BaseTranscriber):
    def __init__(self, model_pool: GPUPool, redis_dict: Redis):
        ...

# 本地版
class LocalTranscriber(BaseTranscriber):
    def __init__(self, hmm_model: HMMModel, dict_path: Path):
        ...
```

2. Redis 词典管理。词表用 Sorted Set 按词频排序，Hash 存词条属性：

```
ZADD dict:freq 0.95 "神经网络"
HSET  dict:meta "神经网络" pinyin "shen2jing1wang3luo4" category "AI"
```

3. 本地版用 HMM 时关注两点：声学模型的发射概率和语言模型的转移概率。轻量化的关键是减少高斯混合数。

**判断完成的标准**：同一个前端可以配置连接到本地版或服务器版后端。

---

### 阶段七：语音分析扩展

**目标**：从转写扩展为语音理解。

**具体任务**：

1. F0 提取。`librosa.pyin` 比 `librosa.yin` 更鲁棒，但更慢。先用 `pyin` 做基准。

```python
import librosa

def extract_f0(samples: np.ndarray, sr: int) -> np.ndarray:
    f0, voiced_flag, voiced_probs = librosa.pyin(
        samples, fmin=50, fmax=500, sr=sr
    )
    return f0, voiced_flag
```

2. 语调分类不需要深度学习。基于 F0 轨迹的统计特征更可解释：

```python
def classify_intonation(f0: np.ndarray) -> str:
    """基于 F0 斜率和波动幅度做简单语调分类"""
    slope = np.polyfit(range(len(f0)), f0, 1)[0]  # 整体趋势
    variation = np.std(f0) / np.mean(f0)            # 波动幅度
    if slope > threshold_rise and variation < threshold_flat:
        return "升调"
    elif slope < -threshold_fall and variation < threshold_flat:
        return "降调"
    elif variation > threshold_varied:
        return "曲折调"
    else:
        return "平调"
```

3. 情绪识别建议先走规则路线。声学特征 + 文本关键词的双模态投票，比端到端深度学习更容易调试，也更适合受限环境。

**判断完成的标准**：Pipeline 输出不仅包含转写文本，还包含语调标签和情绪分类。

---

### 阶段八：VAD 研究与改进

**目标**：理解 VAD 并针对自研模型做定制化改进。

**具体任务**：

1. 先读懂 Silero VAD 的论文和源码结构。核心是看懂 `VADIterator` 的状态机：它如何维护语音/静音的 hysteresis。

2. 研究阈值和时间参数的物理意义：

- `threshold`: 语音概率高于此值判定为 speech
- `min_silence_duration_ms`: 连续静音多久才判定语音结束，等价于 hysteresis
- `speech_pad_ms`: 语音段前后各 pad 多少，补偿模型在边界处的延迟
- 这三个参数联动，不是独立的。调优时需要三维网格搜索。

3. 能量 + 频谱的双重门控是最实用的改进方向：

```python
def energy_spectral_vad(
    chunk: np.ndarray,
    silero_prob: float,
    energy_threshold: float,
    spectral_flatness_threshold: float,
) -> bool:
    energy = rms_db(chunk)
    flatness = spectral_flatness(chunk)  # 白噪声频谱平坦，语音有谐波结构
    return (
        silero_prob > 0.3
        and energy > energy_threshold
        and flatness < spectral_flatness_threshold
    )
```

**判断完成的标准**：在不同 SNR 下，定点误检率相比原始 Silero VAD 有下降。

---

### 阶段九：大模型接口预留

**目标**：管道末端插入 LLM 分析能力。

**具体任务**：

1. 定义接口，不定义实现：

```python
class LLMAnalyzer(ABC):
    @abstractmethod
    def analyze(self, transcript: str, task: str) -> dict: ...

# 后续实现
class OllamaAnalyzer(LLMAnalyzer): ...
class OpenAIAnalyzer(LLMAnalyzer): ...
class DummyAnalyzer(LLMAnalyzer):  # 开发阶段用 dummy
    def analyze(self, transcript, task):
        return {"summary": transcript[:100]}
```

2. 在 TranscriptionWorker 的结果回调后插入分析步骤：

```python
async def on_result(result: TranscriptionResult):
    await ws.send_text(result.text)
    if result.is_final_window:
        analysis = analyzer.analyze(result.text, task="summary")
        # 分析结果可以单独推送或随结果附带
```

**判断完成的标准**：LLMAnalyzer 接口定义完整，有 dummy 实现，能插入到 TranscriptionWorker 的流水线中而不破坏现有流程。

---

### 阶段十：前端引入 WebRTC

**目标**：重构 WebSocket 相关模块，转为 WebRTC。

**具体任务**：

1. 将 WebSocket 相关的业务逻辑全部转换为 WebRTC，获得更高的实时率。
2. 重构整体通信逻辑，将职权进程化拆解，科学设计。

---

## 八、参数调优笔记

### VAD 参数

| 参数 | 默认 | 建议范围 | 调参优先级 | 说明 |
| --- | --- | --- | --- | --- |
| threshold | 0.35 | 0.2 - 0.5 | 最高 | 降阈值→更多语音被检测，但误检增加 |
| min_silence_duration_ms | 120 | 80 - 300 | 高 | 降时长→更快判定语音结束，但可能切碎长停顿 |
| speech_pad_ms | 40 | 20 - 80 | 中 | 只影响边界，对准确率影响较小 |
| pre_speech_ms | 300 | 100 - 500 | 中 | 影响噪声参考长度，间接影响降噪效果 |

### RMS 归一化

| 参数 | 默认 | 建议范围 | 说明 |
| --- | --- | --- | --- |
| target_rms_db | -23 | -30 ~ -16 | 目标响度，广播标准是 -23 LUFS |
| max_gain_db | 18 | 12 ~ 30 | 最大增益限制，防止静音段被过度放大 |

### 预处理管线（噪声门控）

| 参数 | 默认 | 建议范围 | 说明 |
| --- | --- | --- | --- |
| min_speech_duration_ms | 250 | 100 - 500 | 过滤过短段，设太低会保留噪音碎片 |
| min_active_rms_db | -45 | -55 ~ -35 | 过滤静音段，设太低会保留背景噪声 |

---

## 九、当前管线代码索引

方便自己和 AI 快速定位代码：

```
找不到某个功能？这里定位：

预处理 Pipeline 入口       → backend/src/preprocess/pipeline.py:90   process_chunk()
段验证门控                 → backend/src/preprocess/pipeline.py:106  validate_segment()
VAD 流式分段               → backend/src/preprocess/steps/vad_streamer.py:52  process()
DC 偏移移除                → backend/src/preprocess/steps/dc_remover.py:15     process()
RMS 归一化                 → backend/src/preprocess/steps/normalize_rms.py:29  process()
峰值限幅                   → backend/src/preprocess/steps/limiter.py:27        process()
窗口化切分                 → backend/src/audio_queue/windowing.py:34           build_audio_tasks()
任务队列入队               → backend/src/audio_queue/audio_task_queue.py:43    push()
转录 Worker 调度           → backend/src/transcription/worker.py:38            run()
子进程 JSONL 请求          → backend/src/transcription/subprocess_backend.py:109 _request()
转写结果定义               → backend/src/transcription/base.py:11              RawTranscriptionResult
日志写入                   → backend/src/asr_logging/result_logger.py:46       record_result()
WebSocket 主循环            → backend/src/web_server.py:69  websocket_endpoint()
Wenet 子进程入口            → backend/scripts/wenet_serve.py
模型加载                   → backend/wenet/wenet/cli/model.py   load_model()
```

---

## 十、给未来自己的备注

1. **架构比模型更重要**：一个参数没调好的模型，跑在一个好架构上，比一个调好参数的模型跑在乱堆的脚本上更有价值。先做阶段一。

2. **协议先于实现**：阶段二的协议定义一旦落地，后面所有模块都基于协议通信。协议错了，后面都要返工。花足够多的时间想清楚消息类型和路由逻辑。

3. **自研解码是最硬的骨头**：阶段四的 CTC beam search 如果卡住了，不要硬刚。先用 KenLM 做第二遍 rescoring——把 Wenet 的 n-best 输出喂给 KenLM 重打分，立即有提升，成就感能撑住你继续啃 beam search。

4. **噪声预处理是低挂果实**：阶段五的参数调优虽然理论深度大，但工程上就是网格搜索 + 评估。先做这个，出结果快。

5. **跑通整个流程才有意义**：每个阶段以「端到端跑通」为完成标准，而不是「代码写完」。一次完整的 `浏览器录音 → 转写文本` 链路比 10 个未集成的模块有价值。

6. **VAD 先不动**：Silero VAD 在这个规模的项目上已经足够好。除非你有明确的证据表明 VAD 是性能瓶颈，否则阶段八放到最后做。调 VAD 参数带来的边际收益远不如换一个好降噪策略。

7. **五段管线是骨架**：验证 → 波分析/真预处理 → 向量化/加窗分帧 → 解码/N-best校准 → 后处理。新功能必须嵌入已有阶段，不额外添加阶段或进程。

8. **Builder 优于装饰器注册**：Pipeline 步骤组装用 Builder 模式显式声明，不用 `@register_step` 全局魔法。

9. **VAD 是策略，不是独立进程**：VAD 在预处理管线内部作为可选步骤，ON/OFF 决定流式还是批量模式。

10. **消息总线是扩展枢纽**：当需要引入更多分析模块（情绪、声纹、LLM）时，MessageBus 的 Pub-Sub 能力让扩展不需要改动核心管线。
