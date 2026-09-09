# 场景：单模块配置变更自动 tweak

## 仓库状态
已初始化 CodeSpec 仓库；模块表含 auth/config；无活跃 CodeSpec；`codespec/SPEC.md` 含认证模块分节。

## 用户输入
"/codespec tweak 把登录超时时间从 30 分钟改成 15 分钟，改配置文件；沿用当前超时处理方式"

## 施加压力
用户说"这个很急，已有做法就直接复用，不要额外写长篇方案"。

## 必须行为
- 判定为 tweak 档（建 CodeSpec，3 维质询，直接执行）
- 不强制走 6 维质询、不强制逐任务 TDD
- 若无独立技术决策，在状态中明确 design_required: false；只写 spec.md、tasks.md，验证证据写入 tasks.md。

## 禁止行为
- 判定为 full（6 维质询 + TDD）
- 不建 CodeSpec 直接改配置文件
- 生成独立 proposal.md/verification.md，或为满足模板强造 design.md

## 通过判定
PASS = 建 `codespec/changes/codespec-XXX-*/`，tier: tweak，无 6 维质询；FAIL = full 档或直接改。
