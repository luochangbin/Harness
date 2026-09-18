# .ar.yaml 状态文件模板 — 复制到 codespec/changes/<AR 目录>/ 下，文件名 .ar.yaml
# 字段说明：
#   ar                   AR 编号（目录名前缀，如 AR-001）
#   tier                 档位：full
#   phase                下一步可执行阶段：open | design | build | verify | archive；build 不表示实现已开始
#   modules              影响模块 id 列表（必须登记在 codespec/.codespec/config.yaml）
#   worker_transport     null|server|cli；null 表示 current 路径或按 AR/项目默认值
#   verify_result        验证结果：pending | pass | fail
#   verify_failures      连续验证失败次数（verify 失败回 build 时 +1；>=3 后暂停等用户）
#   archive_confirmation 归档确认：pending | confirmed（dry-run 展示后用户确认一次置 confirmed）
#   spec_base_hash       SPEC.md 基线 SHA-256（design 完成时 capture，归档冲突检测用）
#   design_base_hash     DESIGN.md 基线 SHA-256（同上）
#   review_loop_id           审核-修复循环标识；未启用为 null
#   review_loop_status       null|reviewing|dispatching|waiting|paused|needs_user|passed
#   review_loop_issue_limit  逐问题修复暂缓阈值（默认 3）
#   review_loop_round        已预留的修复派发次数（单调递增，不限制整体轮数）
#   review_loop_dispatch_id  当前循环/轮次稳定标识，如 <loop-id>:2
#   review_loop_expected_revision  派发前读取的真实 MCP revision
#   worker_executor       本 AR Worker：null | opencode；current 路径为 null
#   worker_agent          OpenCode agent ID；未选角色或 current 路径为 null
#   worker_session_id     OpenCode CLI/Server session id；current 路径为 null
#   archived             归档完成置 true
ar: AR-001
tier: full
phase: open
modules: [auth]
worker_transport: null
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
review_loop_id: null
review_loop_status: null
review_loop_issue_limit: 3
review_loop_round: 0
review_loop_dispatch_id: null
review_loop_expected_revision: null
worker_executor: null
worker_agent: null
worker_session_id: null
archived: false
