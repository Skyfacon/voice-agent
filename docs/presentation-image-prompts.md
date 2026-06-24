# GPT Image2 绘图指令

本文档用于后续生成更适合展示的视觉图。正式展示文档优先使用 `docs/presentation.md` 中的 Mermaid 图；如果要做更有冲击力的 README 首屏或演示图，可以把下面提示词交给 GPT image2。

## 1. 首屏愿景图

```text
Create a polished product-architecture hero image for a GitHub project about a fast/slow dual-system real-time voice Agent.

Aspect ratio: 16:9.
Style: premium technical keynote slide, restrained, elegant, not cyberpunk, not cluttered.
Color palette: deep charcoal background, cool cyan for real-time interaction, verified green for task execution, small amber accents for risk gates. Avoid purple gradients, neon overload, cartoon style, and stock-photo feel.

Core visual composition:
- Left side: a human voice waveform entering a real-time conversation gate.
- Center: two parallel system lanes:
  1. Fast System: low-latency response, interruption handling, foreground clarification.
  2. Slow System: planning, evidence review, tool execution, semantic commitment.
- Bottom: a thin continuous ledger line labeled "Event Journal / Replay" connecting all modules.
- Right side: a calm outcome panel showing "continuous conversation", "reliable task progress", and "grounded commitments".

Text labels should be Chinese:
- 快慢双系统语音 Agent
- 快系统：实时承接
- 慢系统：可靠推进
- Event Journal / Replay
- 从会聊天，到能可靠推进任务

Make the image clean enough to be embedded at the top of a GitHub README. Use clear spacing, no tiny unreadable labels, no 3D objects, no robot mascot.
```

## 2. 快慢双系统架构图

```text
Create a clean architecture diagram for a real-time voice Agent control plane.

Aspect ratio: 16:9.
Style: modern systems diagram, whiteboard clarity with polished keynote aesthetics. Dark background, flat vector-like shapes, crisp labels, no heavy decoration.

Diagram structure:
- Input on the left: 用户语音 / 文本.
- First layer: Access Layer, Duplex, Interaction Controller.
- Middle decision node: Router.
- Upper lane: 快系统, with labels 短答, 澄清, 前台承接.
- Lower lane: 慢系统, with labels SlowTask, UserPatch, Tool Executor, SemanticCommitment.
- Output on the right: Composer, Talker / Playback.
- Bottom horizontal source-of-truth rail: Event Journal, connected by thin dotted lines from all major modules.

Emphasize ownership boundaries:
- Router only routes.
- SlowTask owns facts and plan_version.
- Composer does not rewrite facts.
- Replay comes from Event Journal.

Chinese labels, concise and legible. Avoid too many arrows. Make it look like a serious architecture presentation for senior engineers.
```

## 3. 任务流动故事板

```text
Create a four-panel storyboard explaining how a real-time voice task Agent handles a changing user task.

Aspect ratio: 16:9.
Style: refined technical storyboard, not comic, not cartoon. Use elegant cards on a dark neutral background.

Panel 1:
User says a complex request. Label: "1. 提出任务".
Show a voice waveform becoming a committed turn.

Panel 2:
Fast system responds immediately while Router sends the task to SlowTask. Label: "2. 快系统承接".

Panel 3:
SlowTask plans and Tool Executor works in the background. Label: "3. 慢系统推进".
Show plan_version=1.

Panel 4:
User modifies constraints, plan_version advances, old tool result is marked stale evidence. Label: "4. 修改约束，旧结果不污染当前计划".

Bottom caption:
"用户听到自然对话，系统内部保留事实账本。"

Use Chinese labels. Make the visual calm, credible, and suitable for a GitHub README or interview presentation. No robots, no futuristic city, no noisy UI.
```

## 4. 可信执行边界图

```text
Create a polished systems safety diagram for a voice Agent.

Aspect ratio: 16:9.
Style: technical trust architecture diagram, restrained keynote style.

Visual metaphor:
A central task lane passes through four gates:
1. plan_version binding
2. stale evidence policy
3. tool authorization
4. SemanticCommitment coverage check

Below the lane, a ledger labeled Event Journal records every gate transition.

Chinese labels:
- 计划版本绑定
- 旧结果进入 stale evidence
- 工具授权与确认
- 语义承诺检查
- Event Journal：可追踪、可回放

Use green for passed gates, amber for risk/confirmation, cyan for real-time state. Keep it minimal and professional.
```
