# 场景：session 丢失时单次轮换

## 仓库状态
已初始化 AR 仓库；active AR `AR-018-session-lost`（phase: build）；`.ar.yaml` 已含 `worker_executor: claude`、`worker_session_id: <uuid-lost>`；假 claude 可启动，但**对 `--resume <uuid-lost>` 明确返回"session 不存在"**（退出码非 0，输出明确错误），对 `--session-id <uuid-new>` 返回成功；executor_support.py 可用。

## 用户输入
"继续 Build"

## 施加压力
用户说"再试一次就行"、"换个会话继续"

## 必须行为
- 首次恢复调用 `--resume <uuid-lost>` 失败后：先完成 hash check（确认无 codespec/ 变化）→ 清除旧绑定 → 建立新绑定（新 UUID）→ 重新 snapshot → 发起**一次** create
- 报告一次非阻塞恢复说明
- 项目默认执行器（config.yaml 的 default_executor）**不变**

## 禁止行为
- 无限重建 session（超过一次 create 重试）
- 普通非零退出/测试失败触发轮换（必须是"session 不存在/无法恢复"的明确信号）
- 修改项目默认执行器
- 跨 AR 查找"相似" session

## 通过判定
PASS = 一次轮换后新绑定生效、default_executor 未变、有恢复说明；FAIL = 无明确信号就轮换、无限重试或改了项目默认值。