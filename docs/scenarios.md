# 高频场景与持续事项

## 场景资料：逐条文本与正式 SOP

源码 Alembic `020` 新增独立的场景资料层。一个名称/别名对应一份按需组合的 Markdown 文档；
事实、历史观测、正式 SOP、注意事项和进行中事项按条保存，新增“周报编写”等场景只新增资料，
不会增加一套页面。每条有稳定编号、来源、证据时间、状态与 revision；事实和观测必须标注带时区的
证据时间。事实、观测、注意事项的正文只承载一条简短主张；工作记录可以容纳临时方案。

其他 AI 通过 MCP `echome_scene_read` 先查名称/别名并读取当前文档，再用 `echome_scene_write`
逐条补充或校正。首次整理可用 `add_batch` 在一个事务中录入多条独立的事实、观测、注意事项与工作记录。
例如用户明确说“去 EchoMe 读取家庭网络场景资料”，AI 可直接用 `get(selector="家庭网络")`；
补充时用 `add`，校正时先读取对应条目的当前 revision，再用 `correct`。
校正必须带当前 `expected_revision`、原因及来源；Hub 保留所有已接受版本，过期 revision 返回 409。
冲突或不确定的新信息应先标为 `needs_review`。归档只改变状态，
默认文档不显示旧条目；带 `include_archived=true` 可追溯。

正式 SOP 只能走 `publish_sop`，不能通过普通条目写入。正文须包含目的、适用、工具、步骤、
验收和验证依据；请求须提供至少 3 次有时间、测试条件、观察结果与原始证据引用的独立有效执行，跨至少 2 次会话，
且每次引用不同。Hub 检查准入形状，真实有效性仍由执行者根据原始证据负责。同一次测速连续
多轮不能作为多次独立验证。修改正式 SOP 正文需要重新提交完整验证证据；简单动作、单次尝试
和未验证流程只放在进行中记录。

家庭网络的历史案例先在隔离测试数据库中验证为事实 6 条、历史观测 4 条、正式 SOP 0 条、
注意事项 4 条和进行中 1 条。2026-10-04 又通过生产 MCP 导入同一份逐条资料，
并验证按别名读取、补充、校正和修订历史；来源指向用户原档案。测试未访问现场网络，
短时测量也未提升为正式 SOP。

下文的 `scenarios`/`scenario_versions` 是此前的**可执行流程版本**契约，供显式路由和持续事项使用；
一个流程版本的发布不会自动成为场景资料中的正式 SOP，也不证明符合上述重复实测门槛。

## 流程版本与持续事项

EchoMe 从源码 Alembic `019` 起保存可复用流程与执行状态。场景库、事项和运行记录分别承担不同职责：

| 对象 | 保存内容 | 更新方式 |
|---|---|---|
| 场景 | 稳定 ID、名称、别名、项目作用域、当前默认版本 | 修改目录元数据或停用；流程变更创建新版本 |
| 场景版本 | 适用与排除条件、输入、环境约束、步骤、验收、恢复、执行引用、来源 | 发布后只读，发布需提供真实验证证据 |
| 事项 | 一次任务或持续监控的目标、非敏感参数、当前状态、下次检查时间；独立事项保存工作计划，绑定事项固定场景版本 | 乐观锁 `expected_revision`；绑定或升级版本需显式操作 |
| 运行记录 | 一次领取和执行的结果、证据、观察状态、变化信号 | 用唯一执行键领取；完成后追加结果，不覆盖旧记录 |

## 使用流程

1. 创建草稿。可以在 Web 的“高频场景”工作台填写，或使用 `echome scenario create scene.json`。`definition` 包含 `applicability`、`exclusions`、`input_fields`、`required_environment`、`steps`、`verification`、`recovery`，可选 `execution_ref` 和 `source_refs`。`steps` 至少一条，验收与恢复也必须有内容。
2. 用具体案例验证流程后，以 `echome scenario publish <slug> <version> --evidence "..."` 发布。发布不是自动运行；证据应是实际验收结果或可追溯引用。尚未验证的流程保留草稿状态。
3. 用户明确指定 ID 或别名时，AI 调用 `echome_scenario_resolve`。结果可能是 `not_found`、`unavailable`、`missing_inputs`、`incompatible` 或 `ready_for_manual_checks`。最后一种只表示结构化输入与环境字段通过，仍须按 `applicability` 和 `exclusions` 做人工适用性检查，并遵守本次任务授权。不会根据语义相似度自动选择或执行。
4. 建立一次性或持续事项。已验证的高频流程可直接指定场景；尚未形成稳定流程的持续工作可先不填 `scenario_slug`，提供 `working_plan`、`phase` 和 `state` 建立独立事项。Web“进行中事项”可直接创建，CLI 可用 `echome scenario start item.json`。新聊天中可通过 Web 查找、`echome scenario items --query "..."` 或 MCP `echome_scenario_item` 的 `list`（`data.query` / `data.scenario_slug`）定位事项，再用 `get` 取回计划、固定版本及当前状态。
5. 独立事项在形成可复用流程后，先建场景草稿并验证、发布，再用 Web 的“绑定场景”、MCP 的 `bind` 或 `echome scenario bind <item-id> <slug> --revision <n> --reason "..."` 显式绑定。绑定前的计划和运行记录保留；新运行使用绑定版本。绑定时重新核对输入和环境，也可提供新的非敏感参数。已有绑定事项发布新版本后不会自动升级，切换需显式提交目标版本、原因与当前 revision。
6. 执行前用 `echome_scenario_run` 的 `claim` 领取租约，得到 `run.id` 和 `lease_token`。只有 `claimed=true` 的响应可以开始本次执行。完成时带租约、结果、证据、当前状态和下一次检查时间调用 `finish`。相同领取键重试会返回 `claimed=false`；相同完成请求返回原结果。租约过期后，旧运行标为 `abandoned`，旧 token 不能写入新状态。

持续事项在 `active` 且 `next_check_at` 到期时会出现在 `GET /api/v1/scenarios/due`。EchoMe **不内置定时 worker 或实际动作执行器**；常在线的外部调度器负责轮询、领取、执行固定流程、上报结果和根据 `notification_recommended` 发出通知。Web 的“设为待检查”只是把时间设为现在，不能自行触发检查。暂停、结束后不会再被领取；执行中的租约须先完成或过期，才能改状态。

## 状态与去重

- `outcome=success` 表示检查过程完成，`observation=normal|alert` 表示实际观察。异常发现可用 `success + alert`；检查器连接失败用 `failure + unknown`。失败不会把上一次正常结果冒充当前状态，`last_success_at` 和 `last_success_summary` 仍保留供追溯。
- 持续事项每次完成都要提交带时区的 `next_check_at`，结束事项时设置 `complete_item=true`。只读的到期列表不会自动重试或修改状态。
- 告警或需处理的结果应有稳定 `event_key`。同一事件连续出现时，运行记录照常增加，`notification_recommended` 不会重复为真；恢复、检查失败、完成会返回不同的 `signal`。该字段是通知建议，真实送达与重试由外部通知器管理。
- 参数、状态、运行摘要和验证证据只能存非敏感内容。Hub 会拒绝高置信凭据或私钥；`secret=true` 的输入只能标注运行时需要的凭据，不允许在场景定义中设置默认值，也不允许把值存入事项参数。凭据获取方式写在流程中，实际凭据由执行环境提供。
- 项目作用域只关联已存在且属于当前用户的 canonical project。所有读写按认证用户隔离。CLI/MCP 写入不支持离线队列；Hub 不可达时不能伪报保存或执行成功。

## 最小 JSON 示例

```json
{
  "slug": "host-health",
  "title": "主机健康检查",
  "summary": "检查已登记主机是否可达",
  "aliases": ["主机检查"],
  "definition": {
    "applicability": "仅适用于已登记的 Linux 主机；执行前核对目标身份。",
    "exclusions": "不适用于初始化或修改主机配置。",
    "input_fields": [{"name": "target", "description": "主机别名", "required": true}],
    "required_environment": {"os": "linux"},
    "steps": ["读取当前目标和上一轮状态", "用固定检查器获取新状态"],
    "verification": ["记录检查时间与实际响应", "区分异常结果和检查失败"],
    "recovery": ["检查器失败时标记 unknown，保留最近成功结果"],
    "execution_ref": "git://example/repo@verified-commit",
    "source_refs": []
  }
}
```

这是数据结构示例，不代表上述流程已验证或已发布。执行引用应指向已固定的脚本或 Skill 版本，不能仅写一个会漂移的分支名。
