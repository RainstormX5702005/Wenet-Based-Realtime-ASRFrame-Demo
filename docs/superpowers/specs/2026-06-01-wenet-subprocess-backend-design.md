# Wenet Subprocess Backend Design

## 1. 背景与动机

当前 transcription 模块直接 import Wenet Python API，调用 `model.transcribe(path)` 获取 top-1 结果。这有两个问题：

1. **无法利用 n-best**：Wenet 内部的 `decode()` 已产出 n-best 候选（`ctc_prefix_beam_search`），但 `transcribe()` 只返回 top-1。
2. **后端耦合**：后续要引入 SenseVoice 等其他 ASR 后端时，缺乏切换机制。

本次重构目标：
- 将 Wenet 作为**持久子进程服务**运行（通过 `.sh` 脚本启动），主程序通过 stdin/stdout 与它通信
- 主程序代码不 import Wenet，只依赖通用的 subprocess 通信协议
- 引入工厂模式，为后续多后端切换预留接口
- 新增 logging 模块，记录完整 n-best 候选及服务状态

## 2. 架构总览

```
web_server.py
  │
  ├── preprocess/          (VAD + 音频增强) — 不动
  ├── audio_queue/         (切窗 + 背压)     — 不动
  │
  ├── transcription/       ★ 重构
  │   ├── base.py            BaseTranscriber ABC + RawResult
  │   ├── subprocess_backend.py  持久子进程后端（通用）
  │   ├── factory.py        按配置创建后端实例
  │   └── worker.py         消费者（适配新接口，逻辑不变）
  │
  ├── logging/             ★ 新增
  │   └── result_logger.py  记录 n-best 结果 + 服务状态
  │
  └── scripts/             ★ 新增
      ├── wenet_serve.sh     环境配置 + 启动命令
      └── wenet_serve.py     Wenet 服务进程（stdin/stdout JSON Lines）
```

## 3. 模块设计

### 3.1 transcription/ — 后端抽象层

#### base.py

定义后端统一接口和数据类型：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class RawResult:
    """后端原始输出，保留完整 n-best"""
    text: str
    nbest_tokens: list[list[int]]
    nbest_scores: list[float]
    model_name: str

class BaseTranscriber(ABC):
    @abstractmethod
    def transcribe(self, audio: "numpy.ndarray", sample_rate: int) -> RawResult:
        ...

    @abstractmethod
    def close(self) -> None:
        ...
```

`RawResult` 使用纯序列化类型（list[int]、list[float]、str），为未来多进程预留兼容性。

#### subprocess_backend.py

通用持久子进程后端，通过 stdin/stdout JSON Lines 与子进程通信：

- `__init__(shell_script: str, args: list[str])`：`Popen` 启动子进程，等待 stdout 首行 `ready` 信号
- `transcribe(audio, sample_rate) -> RawResult`：写临时 wav → 发 `{"wav": path}` 到 stdin → 读 JSON 结果从 stdout → 清理临时文件
- `close()`：发 `{"command": "shutdown"}`，等待子进程退出

每次转写在 `asyncio.to_thread()` 中执行（与现有 worker 一致），阻塞 I/O 不影响事件循环。

#### factory.py

```python
def create_transcriber(name: str, **config) -> BaseTranscriber:
    if name == "wenet":
        return SubprocessTranscriber(
            shell_script="backend/scripts/wenet_serve.sh",
            args=[...],  # model_dir, device, beam_size from config
        )
    # future: elif name == "sensevoice": ...
```

#### worker.py

与当前逻辑一致，仅将 `WenetTranscriber` 替换为 `BaseTranscriber` 接口：

```
loop:
  task = await queue.get()
  raw = await asyncio.to_thread(transcriber.transcribe, task.audio, task.sample_rate)
  on_result(raw)   # callback → postprocess → send to client → logging
```

### 3.2 logging/ — 结果日志

#### result_logger.py

Observer 模式，不参与主 pipeline 数据流：

- `record(result)`：接收转写结果，写入内部 `asyncio.Queue`
- 后台 writer 协程攒批写入 JSON Lines 文件
- 记录内容：时间戳、segment_id、模型名、top-1 文本、n-best token 列表、n-best 分数
- 输出位置：`logs/transcription_YYYYMMDD.jsonl`
- 预留服务状态追踪能力（子进程启动/退出/异常事件日志）

### 3.3 scripts/ — Wenet 服务进程

#### wenet_serve.sh

封装环境配置和启动命令，未来换后端只需切换 .sh 文件。

#### wenet_serve.py

Wenet 服务进程，stdin/stdout JSON Lines 协议：

- 启动时加载模型，输出 `ready`
- 循环读取 stdin 行，解析 JSON 请求
- 对 `{"wav": path}` 请求：调 Wenet `decode()` 取 n-best，输出 JSON 结果
- 对 `{"command": "shutdown"}` 请求：退出循环

## 4. 数据流

```
VAD segment (numpy)
  │
  ▼
audio_queue → AudioTask
  │
  ▼
worker.transcribe(task)
  │  asyncio.to_thread()
  ▼
SubprocessTranscriber.transcribe(audio, sr)
  ├── write temp.wav
  ├── subprocess stdin:  {"wav": "/tmp/xxx.wav"}
  ├── subprocess stdout: {"text": "...", "nbest_tokens": [...], "nbest_scores": [...]}
  ├── cleanup temp.wav
  ▼
RawResult(nbest_tokens, nbest_scores, model_name)
  │
  ├──► on_result callback → ws.send_text(text)
  └──► logger.record(raw_result)
```

注：postprocess（detokenize、n-best 选最优）由 Wenet 服务进程内部完成，RawResult 中 `text` 字段即为最优文本。nbest 数据保留用于日志。

## 5. 不做的事（显式排除）

- 不做 postprocess 模块封装（Wenet 服务内部完成）
- 不引入多进程池/进程管理框架（单个持久子进程足够）
- 不定义完整通信协议（本次只约定最小可用协议，后续迭代完善）
- 不引入 SenseVoice 后端（工厂预留，后续再加）
- 不做子进程异常恢复/health check（服务启动失败由 logging 记录，不自动重试）

## 6. 与现有模块的关系

| 模块 | 改动程度 | 说明 |
|------|---------|------|
| `preprocess/` | 不动 | VAD + 音频增强逻辑不变 |
| `audio_queue/` | 不动 | AudioTask、windowing、背压策略不变 |
| `transcription/` | 重构 | 新增 base/factory/subprocess_backend，删除 wenet_transcriber，修改 worker |
| `logging/` | 新增 | 独立模块 |
| `scripts/` | 新增 | Wenet 服务脚本 |
| `web_server.py` | 修改 | 使用 factory 创建后端，初始化 logger |
| `backend/wenet/` | 不动 | Wenet 源码不修改 |
