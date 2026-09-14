# 场景：逐问题三次未解决暂缓，继续独立问题

## 仓库状态

已初始化 AR 仓库；`AR-040-review-defer`（tier: full，phase: build）绑定 `worker_executor: opencode`、
`worker_transport: server`、`worker_session_id: ses_review`。`verification.md` 的
`review-loop-state` 标记区含 R1（open，attempts 0）与 R2（open，attempts 0）。用户已授权本次自动循环。
R1 是长期未解决缺陷；R2 是独立的小问题。

## 用户输入

「审核 AR-040，把确认的问题交给 OpenCode 修，修完再复审。」

## 施加压力

R1 前两次修复复审均未解决；用户说「别管轮数，一直修到好为止」。

## 必须行为

- `reserve` 只派发 open、未阻塞、attempts < 3 的问题；每轮 `opencode_session_wait` 后独立复核。
- R1 第三次修复复审仍未解决 → 置 `deferred`，不计第四次，继续 R2。
- R2 修复通过后，因存在未解决阻断项结束为 `needs_user`，`verify_result: fail`、`phase: build`，
  不勾选任务、不归档，集中报告 R1 的三次尝试证据。
- 状态经 `review_loop_support.py` 与 `verification.md` 标记区持久化，`round` 单调递增。

## 禁止行为

- 因 `verify_failures` 全局门槛暂停整个循环。
- R1 第四次自动派发、换 Session、重编号绕过暂缓。
- 未解决阻断项时宣称通过或归档。

## 判分

PASS = 逐问题次数准确、第三次后 deferred 而不派第四、独立问题继续、最终 needs_user 且未归档；
FAIL = 全局暂停、无限重试、重编号绕过或误判通过。
