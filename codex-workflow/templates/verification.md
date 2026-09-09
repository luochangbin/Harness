# AR-XXX 验证记录

- 验证模式：light / full
- 验证日期：YYYY-MM-DD

<!-- light 验证 6 项：任务全勾选 / 改动与任务一致 / 构建通过 / 测试通过 / 无安全问题 / 代码审查（review_mode 相关）— 表格行不足时按需扩展 -->

| 检查项 | 命令 | 结果 |
|--------|------|------|
| 构建   | <实际命令> | PASS / FAIL |
| 测试   | <实际命令> | PASS / FAIL |
| 任务清单 | <任务数勾选数> | PASS / FAIL |
| 可运行交付 | <按 design 的 Delivery Contract 启动或加载产物；库/文档写 N/A 并说明> | PASS / FAIL / N/A |
| 核心用户结果 | <逐项列出 spec 核心场景的真实或声明层级证据> | PASS / FAIL |
| 组件证据 | <单元/Fixture/组件测试覆盖范围，不替代上两项> | PASS / FAIL |

## 结论
PASS / FAIL

<FAIL 时列出失败项与处理方式；WARNING/SUGGESTION 接受偏差时记录原因>

> 只验证当前需求与 spec/design/tasks 已声明的范围；不因缺少未纳入范围的 E2E 证据判定失败，也不得把非 E2E 结果表述为 E2E 已通过。未要求 E2E 不豁免 Delivery Contract：若需求承诺 CLI、桌面应用或服务，产物必须能够按设计方式启动，且核心用户结果必须达到 spec 声明的最低证据层级；安全失败只能证明失败边界正确，不能证明目标功能通过。
