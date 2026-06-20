# Project Upgrade Hints / 迭代提示

本文档是项目升级的操作手册。面向我自己和 AI 编程助手：在开始任何代码修改前，必须先理解这里定义的架构取舍、迁移路径和参数约束。

---

## 对 AI 的阅读指令

1. **不要直接删除或重写**：本仓库是起点框架，代码有留存价值。修改时先对照本文档确认该模块是在「保留」清单还是「替换」清单。
2. **Pipeline 协议不可破坏**：`PreprocessStep` 协议、`AudioData` 数据包、`@register_step` 注册器是核心抽象，所有新步骤必须遵守。
3. **进程边界不可混淆**：Wenet 子进程的 JSONL 通信模式是通用模式，替换成其他引擎时复用同一模式。
4. **配置必须可追溯**：所有参数调优的实验记录要能回溯到本文档的参数调优节。

---

## 一、当前架构：保留清单 vs 替换清单

### 保留并复用的模块

这些模块的接口设计经受住了考验，在新项目中可以直接复用或稍作适配：

| 模块 | 路径 | 复用方式 |
| --- | --- | --- |
| `PreprocessStep` 协议 | `preprocess/steps/base.py` | 直接照搬，这是整个 Pipeline 的契约 |
| `@register_step` 注册器 | `preprocess/steps/registry.py` | 直接照搬，构造时校验步骤合法性 |
| `PreprocessPipeline` | `preprocess/pipeline.py` | 直接照搬，`process_chunk` / `validate_segment` 生命周期完整 |
| `AudioData` 数据包 | `preprocess/types.py` | 直接照搬，`accepted` / `reason` / `metadata` 字段设计合理 |
| `AudioTask` | `audio_queue/task.py` | 直接照搬，`segment_id` + `window_index` 的组合 key 设计正确 |
| `AudioTaskQueue` | `audio_queue/audio_task_queue.py` | 直接照搬，容量控制 + 丢弃策略的模式通用 |
| `BaseTranscriber` ABC | `transcription/base.py` | 直接照搬，`transcribe(task) -> TranscriptionResult` 契约清晰 |
| `TranscriptionResult` / `RawTranscriptionResult` | `transcription/base.py` | 直接照搬，n-best 数据携带方式正确 |
| `AsrResultLogger` | `asr_logging/result_logger.py` | 直接照搬，异步队列 + 按日 JSONL 的模式完全通用 |
| `db_to_linear` / `linear_to_db` / `rms_db` | `utils/audio_utils.py` | 直接照搬，纯函数工具集 |

### 需要砍掉或彻底重写的模块

| 模块 | 路径 | 原因 | 替代方向 |
| --- | --- | --- | --- |
| `web_server.py` | `src/web_server.py` | 组件组装硬编码，缺少配置系统 | 阶段一：引入服务编排 + YAML 配置 |
| `SubprocessTranscriber` | `transcription/subprocess_backend.py` | JSONL 协议可行，但 temp WAV 文件方式低效 | 阶段二：改为共享内存或管道传输音频 |
| `wenet_serve.py` | `scripts/wenet_serve.py` | 完全绑定 Wenet 的模型加载和推理 | 阶段四：替换为自研解码器 |
| `create_transcriber` | `transcription/factory.py` | 只支持 `backend="wenet"` 一条分支 | 阶段四：扩展为多后端的工厂注册模式 |
| `StreamingVadSegmenter` | `preprocess/steps/vad_streamer.py` | 算法保留，参数未调优 | 阶段八：调参 + 研究内部机制 |
| `build_audio_tasks` | `audio_queue/windowing.py` | 离线窗口化，无上下文传递 | 阶段三：替换为流式 windowing |

### 保留但需要调参的模块

| 模块 | 当前参数 | 待调整方向 |
| --- | --- | --- |
| `StreamingVadConfig` | threshold=0.35, min_silence=120ms, speech_pad=40ms, pre_speech=300ms | 阶段八：在不同 SNR 条件下做网格搜索 |
| `WindowingConfig` | window=8000ms, step=6000ms, min=1200ms | 阶段三：根据流式解码能力调整窗口和步长 |
| `RmsNormalizerConfig` | target=-23dB, max_gain=18dB | 阶段五：实验最优目标值区间 |
| `PreprocessConfig` | min_speech=250ms, min_rms=-45dB | 阶段五：根据实际场景校准门控阈值 |
| `AudioTaskQueueConfig` | max_size=3 | 根据 GPU 性能和延迟要求调整 |
| `NoiseReducer` | prop_decrease=0.8 | 当前未启用，阶段五启用并调参 |

---

## 二、分阶段升级指南

### 阶段一：架构优化设计

**目标**：先把骨架抽象干净，再做功能扩展。

**具体任务**：

1. 把 `web_server.py` 的 lifespan 拆出来，变成独立的服务组装模块。不要让 lifespan 函数既负责初始化又负责依赖注入。

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

3. 这一步**不改变任何运行时行为**，只做结构重构。重构完成后 pytest 必须全绿。

**判断完成的标准**：`web_server.py` 不超过 60 行，lifespan 逻辑移出到独立模块。

---

### 阶段二：通信协议层与多进程分离

**目标**：把 VAD、降噪、转写拆成独立进程。

**具体任务**：

1. 先定义协议。不要一步到位做完整协议栈，先定义三种消息类型：

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
```

2. 把 `StreamingVadSegmenter` 拆成独立进程。当前它是 Pipeline 中的一个步骤，升级后它应该是一个独立服务，输入音频流，输出语音段边界。

```
当前：chunk → Pipeline → VAD(内部步骤) → 后续步骤
升级：chunk → VADProcess(独立) → 语音段 → Pipeline(纯增强)
```

3. Pipeline 的角色从「预处理 + VAD」变为「纯音频增强」。

**判断完成的标准**：VAD 进程独立启动/停止，消息通过协议路由。

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

2. 替换 `build_audio_tasks` 的离线窗口化逻辑。滑动窗口的关键是保留上一个窗口的编码器状态和 beam 状态。

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

## 三、参数调优笔记

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

## 四、当前管线代码索引

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

## 五、给未来自己的备注

1. **架构比模型更重要**：一个参数没调好的模型，跑在一个好架构上，比一个调好参数的模型跑在乱堆的脚本上更有价值。先做阶段一。

2. **协议先于实现**：阶段二的协议定义一旦落地，后面所有模块都基于协议通信。协议错了，后面都要返工。花足够多的时间想清楚消息类型和路由逻辑。

3. **自研解码是最硬的骨头**：阶段四的 CTC beam search 如果卡住了，不要硬刚。先用 KenLM 做第二遍 rescoring——把 Wenet 的 n-best 输出喂给 KenLM 重打分，立即有提升，成就感能撑住你继续啃 beam search。

4. **噪声预处理是低挂果实**：阶段五的参数调优虽然理论深度大，但工程上就是网格搜索 + 评估。先做这个，出结果快。

5. **跑通整个流程才有意义**：每个阶段以「端到端跑通」为完成标准，而不是「代码写完」。一次完整的 `浏览器录音 → 转写文本` 链路比 10 个未集成的模块有价值。

6. **VAD 先不动**：Silero VAD 在这个规模的项目上已经足够好。除非你有明确的证据表明 VAD 是性能瓶颈，否则阶段八放到最后做。调 VAD 参数带来的边际收益远不如换一个好降噪策略。
