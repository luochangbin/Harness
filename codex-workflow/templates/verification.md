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

## Delivery Evidence（交付证据）

- 实际启动命令：<必须与 design 的交付启动命令逐字一致；library/document 写 N/A>
- 实际访问入口：<必须与 design 的交付访问入口一致；library/document 写 N/A>
- 实际监听/宿主：<service 实测 host:port；其他类型写 N/A>
- 回复前运行状态：running / stopped（library/document 写 N/A）

## Visual Evidence（仅可见界面需要）

- 是否需要视觉验证：yes / no（仅当需求、Delivery Contract 或变更范围涉及可见界面时填 yes）
- 实际查看工具与截图路径：<真实图像查看工具和文件路径；截图存在、Base64、DOM 或功能 smoke 不能替代>
- 真实图像查看结果：PASS / NOT_VERIFIED / N/A
- 若 Computer Use 因宿主隔离错误失败：记录错误码；同一基础设施错误不重复重试，功能 fallback 不能写成视觉 PASS

<!-- visual-gate-state:start -->
{"blocked": false, "fallback": {"error_code": null, "started": false}, "primary": {"error_code": null, "started": false}}
<!-- visual-gate-state:end -->

## 结论
PASS / FAIL

<FAIL 时列出失败项与处理方式；WARNING/SUGGESTION 接受偏差时记录原因>

> 只验证当前需求与 spec/design/tasks 已声明的范围；不因缺少未纳入范围的 E2E 证据判定失败，也不得把非 E2E 结果表述为 E2E 已通过。未要求 E2E 不豁免 Delivery Contract：若需求承诺 CLI、桌面应用或服务，产物必须能够按设计方式启动，且核心用户结果必须达到 spec 声明的最低证据层级；安全失败只能证明失败边界正确，不能证明目标功能通过。

> 可运行交付必须执行 design 中的同一条精确启动命令并验证同一入口。带临时参数的
> E2E、另一端口的 preview 或已停止服务不能替代交付证据。keep-running 必须在最终
> 回复前再次确认监听、入口响应与进程存活；start-on-demand 若已停止，最终回复必须
> 明确当前未运行，只提供启动命令，不得声称链接现在可访问。

## 审核-修复循环（可选；未启用时保持不变）

<!-- review-loop-state:start -->
{"issues": {}, "dispatches": {}}
<!-- review-loop-state:end -->

- 授权范围/验收命令/授权原话简要记录：<启用循环时填写>
- 每轮问题、证据与复审结论：<R1/R2...；含 attempts、dispatch_id 与解/暂缓结论>

## Review Finding Disposition

- 每个自审或外部审查发现必须标记：fixed / accepted / not-an-issue / deferred
- 未标记的问题不得进入 PASS；deferred 必须记录原因、影响和后续处理边界
