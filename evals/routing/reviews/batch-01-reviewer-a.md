# Gate 1 Batch 01 — Reviewer A Working Sheet

Status: pending per-family case sign-off. This is a synthetic-text review aid, not a model report and not a completed human-review ledger.

Manifest snapshot:

```text
sha256:cf155201f83d46cbaf2b8b8d73dc5478d43eaa4ba9f430a098b479c2c2ee0591
```

Reviewer A approved the following cross-case policies on 2026-07-11:

1. Pause-like input becomes `CANCEL_OR_PAUSE_CANDIDATE + PATCH_ACTIVE_SLOW_TASK + CLARIFY`; it must not claim that pause succeeded.
2. Explicit cancellation enters SlowTask through UserPatch. An acknowledgement confirms receipt only; execution/finalizing or unfinished-tool cancellation requires current-plan confirmation.
3. Rejecting a pending confirmation is `ACTIVE_TASK_PATCH`, not cancellation of the whole task.
4. A clear but currently unsupported complex request still spawns SlowTask, which explains capability limits or offers an alternative.
5. The current 80 records are `contrast_set` cases, not strict one-variable minimal pairs.

All cases below remain `annotation_status=draft` until this sheet receives explicit per-family sign-off and an independent Reviewer B completes review.

## F01 — Weather

| Case | Synthetic utterance | Context | Expected outcome |
| --- | --- | --- | --- |
| `rpd_f01_fast` | 一般可以根据哪些天气迹象判断第二天是否可能下雨？ | No active task | `FOREGROUND_CHAT → FAST_ONLY → ANSWER` |
| `rpd_f01_spawn` | 帮我持续关注明天早上的天气，整理出行建议；如果天气明显变化，就更新方案。 | No active task | `NEW_TASK_CANDIDATE → SPAWN_SLOW_TASK → ACK_SLOW` |
| `rpd_f01_patch` | 把现在的出行方案改成不受下雨影响的室内活动路线。 | Active trip, planning | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |
| `rpd_f01_control` | 这个出行方案先停一下。 | Active trip, executing | `CANCEL_OR_PAUSE_CANDIDATE → PATCH_ACTIVE_SLOW_TASK → CLARIFY` |

Reviewer A family decision: pending.

## F02 — Writing

| Case | Synthetic utterance | Context | Expected outcome |
| --- | --- | --- | --- |
| `rpd_f02_fast` | 给我一句简短的生日祝福。 | No active task | `FOREGROUND_CHAT → FAST_ONLY → ANSWER` |
| `rpd_f02_spawn` | 帮我写一份分三部分的生日庆祝活动策划案，并附上执行清单和时间表。 | No active task | `NEW_TASK_CANDIDATE → SPAWN_SLOW_TASK → ACK_SLOW` |
| `rpd_f02_patch` | 第二部分语气别那么正式，改得轻松一点。 | Active document, planning | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |
| `rpd_f02_control` | 这篇策划稿不用写了。 | Active document, finalizing | `CANCEL_OR_PAUSE_CANDIDATE → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH`; cancellation requires confirmation |

Reviewer A family decision: pending.

## F03 — Travel

| Case | Synthetic utterance | Context | Expected outcome |
| --- | --- | --- | --- |
| `rpd_f03_fast` | 坐火车时靠窗座位一般有什么优点？ | No active task | `FOREGROUND_CHAT → FAST_ONLY → ANSWER` |
| `rpd_f03_spawn` | 帮我规划一次三天的公共交通旅行，比较路线和预算，并安排每天的行程。 | No active task | `NEW_TASK_CANDIDATE → SPAWN_SLOW_TASK → ACK_SLOW` |
| `rpd_f03_patch` | 预算上限改为一千元，住宿要尽量安静。 | Active trip, planning | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |
| `rpd_f03_control` | 这版旅行方案我还不能确认，任务继续，请再问我需要怎么调整。 | Active trip, waiting for final-argument confirmation | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |

Reviewer A family decision: pending.

## F04 — Meal Planning

| Case | Synthetic utterance | Context | Expected outcome |
| --- | --- | --- | --- |
| `rpd_f04_fast` | 燕麦和米饭的口感有什么区别？ | No active task | `FOREGROUND_CHAT → FAST_ONLY → ANSWER` |
| `rpd_f04_spawn` | 设计一周晚餐计划，兼顾预算、备餐时间和食材复用。 | No active task | `NEW_TASK_CANDIDATE → SPAWN_SLOW_TASK → ACK_SLOW` |
| `rpd_f04_patch` | 周三那顿不要放花生，换成鹰嘴豆。 | Active meal plan, planning | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |
| `rpd_f04_control` | 先停一下这个晚餐计划。 | Active meal plan, planning | `CANCEL_OR_PAUSE_CANDIDATE → PATCH_ACTIVE_SLOW_TASK → CLARIFY` |

Reviewer A family decision: pending.

## F05 — Language Learning

| Case | Synthetic utterance | Context | Expected outcome |
| --- | --- | --- | --- |
| `rpd_f05_fast` | 把“稍后见”翻成英文。 | No active task | `FOREGROUND_CHAT → FAST_ONLY → ANSWER` |
| `rpd_f05_spawn` | 为初学者设计四周英语练习计划，每周有目标、材料类型和复盘方法。 | No active task | `NEW_TASK_CANDIDATE → SPAWN_SLOW_TASK → ACK_SLOW` |
| `rpd_f05_patch` | 每天练习时间从半小时改成十五分钟。 | Active learning plan, planning | `ACTIVE_TASK_PATCH → PATCH_ACTIVE_SLOW_TASK → ACK_PATCH` |
| `rpd_f05_control` | 这个学习计划先不要继续。 | Active learning plan, executing | `CANCEL_OR_PAUSE_CANDIDATE → PATCH_ACTIVE_SLOW_TASK → CLARIFY` |

Reviewer A family decision: pending.

## Reviewer A response format

```text
F01 accept|change: ...
F02 accept|change: ...
F03 accept|change: ...
F04 accept|change: ...
F05 accept|change: ...
```
