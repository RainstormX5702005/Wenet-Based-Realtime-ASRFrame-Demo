# 后续计划与资源

本文档记录项目的演进方向、技术路线，以及当前和未来依赖的关键资源。

---

## 当前架构的可复用性

虽然当前框架在后续会被弃用——因为 Wenet 的紧耦合、离线窗口化策略以及缺少真正的流式协议支持都限制了它向中型项目演进的潜力——但框架本身的架构设计值得在新项目中复用：

- **Pipeline 模式**：预处理步骤的协议化 + 注册机机制，可直接在新项目中照搬
- **进程化 ASR 后端**：JSONL 子进程通信模式，适用于任何需要隔离 GPU 推理的场景
- **有界任务队列 + 反压**：asyncio.Queue 封装的容量控制策略
- **抽象基类 + 工厂**：`BaseTranscriber` → `create_transcriber` 的扩展模式
- **结构化日志**：按日 JSONL 输出，记录完整 n-best 数据

---

## 技术路线图

### 阶段零：迁移 Python 版本

**目标**：适配新版本的 Python 并使用更多的优秀特性，计划迁移到 Python 3.14

---

### 阶段一：架构优化设计

**目标**：重新审视并重构整个系统的模块边界，为后续扩展打好地基。

- 将当前的 Pipeline、队列、转录、日志四层抽象为更通用的服务接口
  - 每层定义清晰的数据契约和错误传播约定
  - 层与层之间通过接口通信，而非直接依赖具体实现
- 引入依赖注入或服务注册机制，替代当前硬编码的模块组装方式
  - `web_server.py` 目前手动拼接所有组件，需要替换为可配置的服务编排
- 规范化配置管理
  - 将散落在各模块的 dataclass 配置收敛为统一的 YAML 或 TOML 配置系统
  - 支持不同部署环境下的一键切换
- 建立完整的单元测试与集成测试体系
  - 当前测试覆盖率有限，需要在架构定型后补齐

**参考资源**：
- Python 服务架构：[dependency-injector](https://github.com/ets-labs/python-dependency-injector)
- 配置管理：[Hydra](https://hydra.cc/)、[OmegaConf](https://github.com/omry/omegaconf)

---

### 阶段二：通信协议层与多进程分离

**目标**：建立标准化的通信层，支撑前后端及后端多进程间的语音数据传输。

- 定义前端到后端的消息协议，替代当前的裸 WebSocket 二进制传输
  - 消息类型：音频块、控制指令、元数据
  - 序列化格式候选：MessagePack 或自定义二进制帧头
- 将 VAD、降噪、转写等计算密集型模块拆分为独立进程
  - 当前仅有一个 Wenet 子进程，拆分后形成多处理器拓扑
  - 每个处理器有独立的资源配额和错误隔离
- 定义后端多进程间的路由协议
  - 语音数据根据类型被路由到正确的处理器
  - 支持处理器的动态注册与健康检查
- 在 `protocols/` 目录下落地协议定义文档

**参考资源**：
- WebSocket 子协议设计：[RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455)
- 实时通信协议参考：LiveKit、MediaSoup 的 SFU 设计

---

### 阶段三：流式语音识别

**目标**：实现真正的流式识别，音频进入的同时增量输出文字。

- 研究流式 CTC/Attention 解码策略
  - 当前 Wenet 的 CTC prefix beam search 本质是离线解码
  - 需要实现 chunk-based 或 frame-synchronous 的流式解码
- 改进 windowing 机制
  - 当前策略：固定窗口重叠切分 → 独立识别 → 结果拼接
  - 目标策略：滑动窗口 + 上下文传递 + 增量输出 + 结果合并
- 研究重叠区域的多结果融合策略，处理窗口边界的识别不一致

**参考资源**：
- Wenet 流式解码：`wenet/transformer/asr_model.py` 中的 `decode_chunk` 方法
- 流式 Attention 综述：[MoChA](https://arxiv.org/abs/1712.05382)、[Triggered Attention](https://arxiv.org/abs/1907.03477)
- CTC 流式解码：frame-wise CTC + prefix merging

---

### 阶段四：自研 ASR 引擎

**目标**：摆脱 Wenet 的推理绑定，Wenet 退化为训练工具，转写服务由自研代码驱动。

- 模型方面
  - 深入理解 Conformer/Transformer 的推理图
  - 尝试导出 ONNX 或 TorchScript 做跨框架部署
  - 探索使用自己设计的轻量语音模型替代 Wenet 预设架构
- 解码方面
  - 自研 CTC prefix beam search + WFST/TLG 解码
  - 基于字典的 N-best 策略校准
  - RAG 模式：利用外部文本语料提升领域适配的准确率
  - HMM 结合语言模型做第二遍 rescoring
- 文字后处理
  - 标点恢复、逆文本归一化
  - 中文分词与命名实体识别

**参考资源**：
- k2/WFST 解码：[k2-fsa](https://github.com/k2-fsa/k2)、[icefall](https://github.com/k2-fsa/icefall)
- HMM 语音识别基础：[HTK Book](https://htk.eng.cam.ac.uk/)
- RAG for ASR：[Contextual Biasing](https://arxiv.org/abs/2203.05361)
- N-best rescoring：使用 KenLM 或 RNNLM 做第二遍打分

---

### 阶段五：预处理系统优化

**目标**：在受限语音环境下，通过系统性的预处理参数调整提升识别质量。

- 声学基础研究
  - 理解声波在空气中的传播特性与衰减模型
  - 理解傅里叶变换在音频特征提取中的物理意义
  - 研究不同噪声类型对特征提取的影响
- 预处理参数调优实验
  - 网格搜索或贝叶斯优化各步骤的参数组合
  - 在不同 SNR 条件下评估 DC 移除、预加重、降噪的参数敏感性
  - 确定 RMS 归一化目标值、限幅阈值的最优区间
- 探索新的预处理组件
  - 自适应增益控制
  - 多频带动态压缩
  - 基于深度学习的语音增强前端

**参考资源**：
- 语音信号处理：[HTK Book 第 5 章](https://htk.eng.cam.ac.uk/) — 特征提取原理
- 傅里叶变换与频谱分析：Oppenheim & Schafer《Discrete-Time Signal Processing》
- 语音增强：[DNS Challenge](https://github.com/microsoft/DNS-Challenge) — 噪声抑制基线
- noisereduce 库：[noisereduce](https://github.com/timsainb/noisereduce) — 频谱门控降噪

---

### 阶段六：双版本服务

**目标**：推出本地版和服务器版两种部署形态。

- **服务器版**
  - 词典管理：Redis 存储可热更新的词表
  - 多用户并发：每个连接独立的状态机
  - GPU 调度：请求批处理或流式分时复用
  - 支持用户自行上传和更新个性化词典
- **本地版**
  - 纯 CPU 运行，使用轻量 HMM 模型
  - 词典本地文件存储，简单高效
  - 低延迟优先，牺牲部分准确率换取实时性
- 两个版本共用
  - Pipeline 预处理架构
  - 通信协议定义
  - 前端界面

**参考资源**：
- Redis 词典管理：使用 Redis Sorted Set 存储词频，Hash 存储词条属性
- HMM 工具包：[HTK](https://htk.eng.cam.ac.uk/)、[Kaldi](https://kaldi-asr.org/)

---

### 阶段七：语音分析扩展

**目标**：从单纯的转写扩展为语音理解。

- 语调检测
  - 基频 F0 提取与轨迹分析
  - 语调模式分类：升调、降调、平调、曲折调
- 情绪识别
  - 声学特征：音高、响度、语速、共振峰
  - 频谱特征：MFCC、梅尔谱图 + 分类器
  - 考虑结合文本语义做多模态情绪判断
- 语音波形修饰
  - 可视化频谱图与时频谱
  - 波形对比分析

**参考资源**：
- F0 提取：[pYIN](https://code.soundsoftware.ac.uk/projects/pyin)、[CREPE](https://github.com/marl/crepe)
- 语音情绪识别：[SpeechBrain Emotion Recognition](https://huggingface.co/speechbrain/emotion-recognition-wav2vec2-IEMOCAP)
- 声学特征：[librosa](https://librosa.org/) — 频谱、MFCC、色度等
- 多模态情绪：[MER 2024 Challenge](https://github.com/zeroQiaoba/MERTools)

---

### 阶段八：VAD 深入

**目标**：理解 VAD 原理并针对自研模型做定制化改进。

- 研究 Silero VAD 的内部机制
  - 模型结构：类似 CRNN 的轻量设计
  - 训练数据与策略
  - 阈值与时间参数的物理意义
- 自研 VAD 或微调
  - 在目标场景数据上微调 Silero VAD
  - 考虑基于能量 + 频谱的双重门控策略
  - 研究如何与自研 ASR 模型的声学特征前段共享

**参考资源**：
- Silero VAD：[snakers4/silero-vad](https://github.com/snakers4/silero-vad)
- VAD 综述：[WebRTC VAD](https://webrtc.googlesource.com/src/) — 经典能量/频谱方法
- 基于深度学习的 VAD：[MarbleNet](https://arxiv.org/abs/2010.13886)

---

### 阶段九：大模型集成

**目标**：利用 LLM 对语音转写结果做高层语义分析。

- 预留 LLM 调用接口
  - 统一的 `analyze(text, task)` 抽象
  - 支持本地模型和云端 API 两种后端
- 规划的分析能力
  - 语音内容概要提取
  - 说话质量评判
  - 关键信息抽取
  - 多轮对话的语境理解

**参考资源**：
- 本地 LLM：[Ollama](https://ollama.com/)、[llama.cpp](https://github.com/ggerganov/llama.cpp)
- 云端 API：OpenAI、Anthropic 接口规范
- 提示工程：[Prompt Engineering Guide](https://www.promptingguide.ai/)

---

### 阶段十：前端引入 WebRTC

**目标**：重构 Websocket 相关模块，转为 WebRTC

- 将 Websocket 相关的业务逻辑全部转换为 WebRTC，获得更高的实时率。
- 重构整体通信逻辑，将职权进程化拆解，科学设计

---

## 当前技术债务

| 问题 | 说明 | 优先级 |
|------|------|--------|
| Wenet 强绑定 | 推理逻辑完全依赖 Wenet 的 `decode` 和 `detokenize`，无法独立演进 | 高 |
| 离线 windowing | 当前的窗口化是为离线模型拼凑的流式方案，不是真正的流式解码 | 高 |
| 裸 WebSocket 传输 | 前后端直接传输 float32 字节流，缺少消息类型和元数据 | 中 |
| VAD 参数未调优 | Silero VAD 的阈值和时间参数使用默认值，未针对实际场景校准 | 中 |
| 预处理参数未系统优化 | 各步骤的参数仅做了基本设置，缺少不同条件下的系统性对比实验 | 中 |
| 无标点恢复 | 转写结果不含标点，影响可读性 | 低 |
| 无说话人区分 | 不支持多人对话场景的说话人日志 | 低 |

---

## 第三方资源汇总

### 核心依赖

| 库 | 版本 | 用途 | 许可证 |
|----|------|------|--------|
| Wenet | vendored | ASR 模型训练与推理 | Apache 2.0 |
| Silero VAD | >=6.2.1 | 流式语音活动检测 | MIT |
| noisereduce | latest | 频谱降噪 | MIT |
| FastAPI | >=0.109.0 | Web 服务框架 | MIT |
| PyTorch | >=2.0.0 | 深度学习框架 | BSD |
| torchaudio | >=2.0.0 | 音频 I/O 与特征提取 | BSD |

---

## 写在后面

这个项目虽然日后会被重构甚至重写，但它的价值不在于代码本身能跑多久，而在于它让我建立了对语音识别全链路的认知——从声波到文字，每一步都经过了手写和思考。下一次搭建中型项目时，这套架构思路和工程经验会直接复用过去。

如果未来有人看到这个项目，希望它能作为一份参考：一个初入语音领域的人如何从零搭建起一条可工作的流式语音识别流水线，以及他对这条流水线未来演进方向的所有思考。
