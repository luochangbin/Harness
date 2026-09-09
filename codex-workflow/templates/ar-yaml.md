# .ar.yaml 状态文件模板 — 复制到 codespec/changes/<AR 目录>/ 下，文件名 .ar.yaml
# 字段说明：
#   ar                   AR 编号（目录名前缀，如 AR-001）
#   tier                 档位：full | tweak（bugfix 不建 AR）
#   phase                下一步可执行阶段：open | design | build | verify | archive；build 不表示实现已开始
#   modules              影响模块 id 列表（必须登记在 codespec/.ar/config.yaml）
#   verify_result        验证结果：pending | pass | fail
#   verify_failures      连续验证失败次数（verify 失败回 build 时 +1；>=3 后暂停等用户）
#   archive_confirmation 归档确认：pending | confirmed（dry-run 展示后用户确认一次置 confirmed）
#   spec_base_hash       SPEC.md 基线 SHA-256（design 完成时 capture，归档冲突检测用）
#   design_base_hash     DESIGN.md 基线 SHA-256（同上）
#   reasoner_mode        本 AR Design Reasoner：null | local | oracle-cli
#   reasoner_model       固定 gpt-5.6-sol；local/未绑定为 null
#   reasoner_effort      固定 extended；local/未绑定为 null
#   reasoner_session_id  Oracle CLI session slug；未完成首次调用或 local 为 null
#   worker_executor       本 AR 外部 Worker：null | claude | opencode
#   worker_agent          本 AR 固定的 OpenCode agent ID；非 opencode 或旧绑定为 null
#   worker_session_id     对应 CLI 的 opaque session id；current 路径为 null
#   archived             归档完成置 true
ar: AR-001
tier: full
phase: open
modules: [auth]
verify_result: pending
verify_failures: 0
archive_confirmation: pending
spec_base_hash: null
design_base_hash: null
reasoner_mode: null
reasoner_model: null
reasoner_effort: null
reasoner_session_id: null
worker_executor: null
worker_agent: null
worker_session_id: null
archived: false
