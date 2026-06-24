# Presentation Image Assets

把 GPT realtime2 / GPT image2 生成的展示图放在本目录下。推荐使用 16:9 横图，宽度 1600px 或 1920px，PNG 优先。

## 推荐文件名与落位

| 文件名 | 放在文档中的位置 | 用途 |
| --- | --- | --- |
| `01-hero-fast-slow-agent.png` | `docs/presentation.md` 标题和导语之后 | 第一屏视觉锚点，负责抓住读者注意力。 |
| `02-cascade-vs-control-plane.png` | `## 1. 设计命题` 之后，可选 | 对比传统 `ASR -> LLM -> TTS` 和实时任务控制面。当前版本暂未使用。 |
| `03-fast-slow-architecture.png` | `## 2. 系统总览` Mermaid 图之前或替换 Mermaid 图 | 快慢双系统总览图，适合 README 首屏复用。 |
| `04-task-flow-storyboard.png` | `## 4. 任务如何流动` 之前 | 用故事板解释用户补充、计划更新、旧结果 stale。 |
| `05-trust-boundaries.png` | `## 5. 可信执行边界` 之前 | 展示 plan_version、stale evidence、tool authorization、SemanticCommitment。 |
| `06-roadmap.png` | `## 7. 演进路线` 之前，可选 | 如果 Mermaid 路线图视觉不够，可以用图片替换。当前版本暂未使用。 |

## 当前已使用图片

- `01-hero-fast-slow-agent.png`
- `03-fast-slow-architecture.png`
- `04-task-flow-storyboard.png`
- `05-trust-boundaries.png`

## 命名规则

- 文件名使用小写英文、数字和连字符。
- 不使用空格、中文文件名或括号。
- 不提交草稿、失败版本或含水印版本。
- 图片不要包含 API key、真实用户信息、真实 trace、真实音频内容或本地路径。
