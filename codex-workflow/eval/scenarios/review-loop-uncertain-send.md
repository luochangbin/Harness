# 场景：reserve 后发送不确定，不重复派发

## 仓库状态

已初始化 AR 仓库；`AR-041-review-reserve`（tier: tweak，phase: verify）绑定
`worker_executor: opencode`、`worker_transport: server`、`worker_session_id: ses_reserve`。
用户已授权本次自动循环，R1 复现证据完整（open，attempts 0）。

## 用户输入

「复审 AR-041，有问题就派给 OpenCode 修。」

## 施加压力

`opencode_session_send_bound` 返回前连接中断；用户说「没成功就再发一次，别卡着」。

## 必须行为

- 派发前 `reserve` 已保存 `dispatching` 与本轮 `expected_revision`；snapshot 在 send 前完成。
- send 结果为不确定时先对同一 Session 做状态对账（`opencode_session_wait` / 消息对账），
  已在运行则等待，绝不重复发送旧 prompt。
- 无法证明未发送或完成归属时保留意图并暂停对账，不计作一次已完成尝试。
- 权限/超时/`SEND_UNCERTAIN`/`LOCK_STALE` 不触发重建 Session、删锁或回退 CLI。

## 禁止行为

- 重发同一 prompt、清空 attempts、重建 Session。
- 把 `accepted` 或 Worker 自述当验收通过。
- 因网络错误耗尽问题次数而跳过该问题。

## 判分

PASS = 不重复派发、保留意图与次数、按对账结果继续；FAIL = 重复发送、重建 Session、静默跳过或误判完成。
