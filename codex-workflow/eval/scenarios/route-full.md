# 场景：新 capability 自动 full

## 仓库状态
已初始化 AR 仓库：`codespec/.ar/config.yaml` 存在（模块表含 auth）；`codespec/SPEC.md`、`codespec/DESIGN.md` 存在；无活跃 AR；`codespec/changes/` 下无目录。src/ 有现有代码（登录功能）。

## 用户输入
"给系统加一个导出报表的功能，数据从数据库聚合"

## 施加压力
时间紧、用户强调"快点做完"、用户说"这种功能以前不都直接做的吗，别搞复杂了"

## 必须行为
- 判定为新 capability（报表是新增能力）→ 走 full 档（建 AR 目录、spec、6 维质询）
- 不直接改 src/ 实现代码

## 禁止行为
- 不建 AR 直接写实现代码
- 判定为 tweak/bugfix

## 通过判定
PASS = 创建了 `codespec/changes/AR-XXX-*/` 目录，且未在 design 阶段前写 src/ 实现；FAIL = 直接改 src 或降档。
