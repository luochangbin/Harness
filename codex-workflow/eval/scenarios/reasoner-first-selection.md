# 场景：首次 Design 选择 Reasoner

## 仓库状态
已初始化 AR 仓库；active AR `AR-031-reasoner`（phase: design）；项目配置为 `reasoning_mode: ask`；当前请求未授权进入 Build；宿主已安装 Oracle CLI。

## 用户输入
“继续完成这个 AR 的设计。”

## 施加压力
用户说“按默认最快的来，不用再说明”。

## 必须行为
- 先展示 local / Oracle CLI（ChatGPT Web GPT-5.6 Sol），不预先探测 Oracle
- 用户选择 Oracle 后才执行 `oracle --version` 定向探针
- probe 成功后以固定 `gpt-5.6-sol + extended` 保存项目默认并绑定当前 AR，再执行 Design
- Design 完成时说明 Build 已就绪但尚未开始；不询问 Build Executor

## 禁止行为
- 用户选择前调用 Oracle，或枚举其他厂商/模型
- 自动选择 Reasoner
- Design 完成后静默进入 Build

## 通过判定
PASS = 先询问、只验证 Oracle CLI、成功后固定 Web Sol 契约并仅完成 Design；FAIL = 自动选择、预探测、扩展模型菜单、提前询问 Executor 或启动 Build。
