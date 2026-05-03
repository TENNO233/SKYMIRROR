# SKYMIRROR 项目逻辑梳理

## 1. 项目定位

SKYMIRROR 是一个面向新加坡道路监控场景的多智能体交通图像分析系统。它的目标不是单纯“识图”，而是把一张交通摄像头画面转成一条可追踪、可解释、可归档、可展示的运营事件链路：

1. 拉取实时交通摄像头画面。
2. 通过图像安全闸门过滤不合规输入。
3. 用视觉模型提取结构化场景描述。
4. 用 validator 对首轮识别结果做保守交叉校验。
5. 用 orchestrator 决定要唤起哪些领域专家。
6. 由专家结合规则和 RAG 判断是否存在交通秩序、安全、环境类问题。
7. 将专家结果合成为告警，并写入磁盘。
8. 把运行状态同步给 dashboard。
9. 按天聚合 `RunRecord`，生成日报 Markdown。

从代码结构上看，它是一个“LangGraph 编排内核 + Python runtime 守护进程 + RAG 检索层 + 告警落盘层 + dashboard 展示层 + 治理与离线评估层”的完整系统。

## 2. 目录与职责地图

### 2.1 核心源码目录

- `src/skymirror/main.py`
  运行入口，负责守护进程、轮询摄像头、调 LangGraph、写运行状态、写 RunRecord、起日报定时任务。
- `src/skymirror/graph/`
  LangGraph 的状态定义、节点图、条件路由规则。
- `src/skymirror/agents/`
  核心智能体节点，包括 guardrail、VLM、validator、orchestrator、三个 expert、alert manager、report generator。
- `src/skymirror/tools/`
  支撑工具层，包括摄像头抓取、Pinecone 检索、RAG 入库、治理策略、运行日志、日报分析、告警工具链、dashboard 状态等。
- `src/skymirror/dashboard/`
  轻量 HTTP dashboard 服务，负责聚合本地运行状态、图片、报告和前端静态资源。

### 2.2 数据与治理目录

- `data/frames/`
  运行时抓取的摄像头帧。
- `data/oa_log/`
  每次处理完成后落盘的 `RunRecord` JSONL 日志，是日报和离线评估的事实源。
- `data/alerts/`
  告警 JSON 与 dispatch log。
- `data/reports/`
  每日 Markdown 报告。
- `data/rag/`
  三个专家域的本地知识语料。
- `data/sources/`
  摄像头参考数据与新加坡官方资料下载缓存。
- `governance/`
  治理策略、发布门槛、AI 风险登记。

### 2.3 测试与脚本

- `tests/`
  覆盖 graph、experts、validator、VLM、alert manager、dashboard、report generator、camera fetcher、runtime governance 等模块。
- `scripts/evaluate_runtime.py`
  基于 fixture 的运行时契约与发布阈值校验。
- `scripts/evaluate_alerts.py`
  对已生成告警做 LTA 事件回溯校验。

## 3. 整体架构

### 3.1 两条主业务线

项目实际维护了两条工作流：

1. `frame` 工作流
   面向实时摄像头帧，输出告警和运行记录。
2. `report` 工作流
   面向某一天的历史 `RunRecord`，输出日报 Markdown。

这两条线被注册在同一张 LangGraph 图里，因此 Studio 上会看到一张统一画布，但逻辑上它们是分开的。

### 3.2 顶层运行方式

`main.py` 提供 4 种入口模式：

- `python -m skymirror.main`
  常驻守护进程，持续拉摄像头。
- `python -m skymirror.main --once`
  单轮拉取并处理后退出。
- `python -m skymirror.main --image /path/to/file`
  用本地图片走一次 frame 流程，跳过摄像头抓取。
- `python -m skymirror.main --report`
  直接生成日报并退出。

默认守护进程还会启动 APScheduler，在 `00:05 UTC` 触发日报生成。

## 4. Frame 工作流主链路

### 4.1 运行主循环

常驻模式下，`main.py` 的执行节奏是：

1. 解析目标摄像头列表。
2. 每个摄像头起一个线程执行 `_run_daemon(...)`。
3. 每轮先调用 `fetch_latest_frame(...)` 抓取实时图片。
4. 成功抓到图后调用 `_run_pipeline(...)`。
5. 管道完成后：
   - 发布可展示的最新帧；
   - 追加短期历史上下文；
   - 写 dashboard runtime status；
   - 写 `RunRecord`。

这里有一个关键设计：**主循环绝不因单次失败而崩掉整个 daemon**。无论是抓图失败、模型失败还是图执行失败，都会写失败状态并继续下一轮。

### 4.2 初始状态构造

进入 LangGraph 前，`_run_pipeline(...)` 会构造一份完整的 `SkymirrorState` 初始对象，主要字段包括：

- `workflow_mode="frame"`
- `run_id`
- `camera_id`
- `image_path`
- `policy_snapshot`
- `history_context`
- `guardrail_result / vlm_output / validated_scene / validated_text / expert_results / alerts / metadata`

也就是说，图中所有节点都围绕这一个共享状态读写。

## 5. LangGraph 编排逻辑

### 5.1 图结构

顶层路由大致如下：

```text
START
  -> workflow_router
     -> frame: image_guardrail -> vlm_agent -> validator_agent -> orchestrator_agent
     -> report: report_generator

frame 分支中：
orchestrator_agent
  -> 并行 expert（dispatch 阶段）
  -> 回到 orchestrator_agent（evaluate 阶段）
  -> alert_manager 或 END
```

### 5.2 三段式决策骨架

Frame 流程的核心是“三段式决策”：

1. `image_guardrail`
   先决定图能不能进分析链。
2. `orchestrator dispatch`
   决定哪些专家参与。
3. `orchestrator evaluate`
   决定是否进入 `alert_manager`。

所以 graph 不只是串行流水线，而是一个带条件路由和并行 fan-out 的监督式图。

### 5.3 兼容性分支

图中还保留了 `legacy_frame_compat`，用于兼容旧测试或旧的 `vlm_text` 输入路径。它会：

- 直接跑 VLM；
- 将文本适配成 `validated_text`；
- 顺序执行三个 expert；
- 再执行 `alert_manager`。

这条线不是当前主运行路径，但说明项目处在从旧文本流向新结构化流的迁移期。

## 6. 状态模型设计

`graph/state.py` 定义的 `SkymirrorState` 是项目的中枢。它有几个很重要的设计点。

### 6.1 业务状态字段

- `guardrail_result`
  图像安全门输出。
- `vlm_output`
  视觉模型首轮结构化识别结果。
- `validated_scene`
  validator 修正后的标准结构化结果。
- `validated_text`
  给 orchestrator 和 experts 用的规范化文本摘要。
- `validated_signals`
  面向下游逻辑的轻量结构化信号，例如 `blocked_lanes`、`queueing`、`collision_cue`。
- `history_context`
  同摄像头最近几帧的摘要，用于判断持续性、恶化趋势。
- `active_experts`
  当前帧激活了哪些专家。
- `expert_results`
  每个专家按名字写入自己的结构化结果。
- `alerts`
  最终告警列表。
- `metadata`
  观测性数据，包含模型、prompt、policy、retrieval、external_calls 等。

### 6.2 reducer 设计

状态里有两个 reducer 很关键：

- `expert_results` 用浅合并 reducer
  让多个 expert 并行写回时互不覆盖。
- `alerts` 用 list 追加 reducer
  保证 terminal 节点可以累积输出。
- `metadata` 用深合并 reducer
  让每个节点都能把自己的观测信息挂进去。

这让图在并行 fan-out 时仍然可控。

## 7. 输入门禁：Image Guardrail

`agents/vlm_agent.py` 里的 `image_guardrail_node(...)` 负责第一道门。

### 7.1 本地预检查

进入模型前，会先做本地 preflight：

- 路径是否合法；
- 本地文件是否存在；
- 远程图域名是否被策略允许；
- 图片格式是否在 `jpeg/png/webp` 之内；
- 宽高是否在合理区间；
- 图片是否可正常解码。

如果本地检查失败，直接返回：

- `guardrail_result.allowed = false`
- `status = blocked`
- `category = invalid_image`

### 7.2 模型级安全分类

通过本地检查后，再调用 OpenAI guardrail 模型对图片进行安全分类，输出：

- `allowed`
- `status`
- `reason`
- `categories`

如果 guardrail 模型异常，也会 fail-closed，直接阻断整条分析链，并把原因记到 `metadata.external_calls.guardrail_api`。

### 7.3 作用边界

这个 guardrail 不是在判断“是否有交通异常”，而是在判断“这张图能否安全地进入下游交通分析模型”。所以交通事故、拥堵、施工都应该被允许；真正要挡的是图片损坏、非法来源、或明显不安全内容。

## 8. 首轮视觉识别：VLM Agent

### 8.1 输出形式

`vlm_agent_node(...)` 会把图片送入单个 OpenAI 视觉模型，要求返回严格 JSON，主要字段为：

- `summary`
- `direct_observations`
- `road_features`
- `traffic_controls`
- `notable_hazards`
- `signals`

其中 `signals` 是全链路最关键的字段之一，包含：

- 车辆数量、静止车辆数量；
- 是否有行人；
- 阻塞车道数；
- 是否排队；
- 是否有积水、施工、障碍物；
- 是否低可见度；
- 是否存在 wrong way、collision、dangerous crossing、conflict risk 等 cue。

### 8.2 设计意图

VLM 的职责是“广覆盖提取”，尽量把图里的可见事实结构化出来，但不直接下最终业务判断。

## 9. 二次校验：Validator Agent

validator 是当前架构的一个核心安全层。

### 9.1 为什么需要 validator

首轮 VLM 输出可能会：

- 过度推断；
- 用词过强；
- 信号与文本不一致；
- 把画面中不够确定的风险写成确定事实。

validator 的作用是把这些内容重新对照原图做保守收敛，得到一份更适合编排与告警的标准描述。

### 9.2 validator 输出

它会产出：

- `validated_scene`
  标准结构化 JSON。
- `validated_text`
  一段 operations-facing 的简洁文本。
- `validated_signals`
  与修正后场景一致的结构化 cue。

### 9.3 `validated_text` 的风格

validator 不是简单复述场景，而是把文本格式化为：

- `Scene assessment: ...`
- `Government relevance: ...`

也就是说，下游不只是拿到“图里有什么”，而是拿到“政府交通运营团队为什么应该关心这个画面”。

### 9.4 与 orchestrator 的关系

后续专家路由主要依赖两类输入：

1. `validated_text` 中的关键词。
2. `validated_signals` 中的布尔/数值 cue。

这让路由既能走文本召回，也能走结构化召回。

## 10. 调度中枢：Orchestrator

`agents/orchestrator.py` 里的 `orchestrator_node(...)` 每帧会执行两次。

### 10.1 Dispatch 模式

当 `expert_results` 为空时，orchestrator 处在 dispatch 模式：

- 读取 `validated_scene`
- 读取 `validated_text`
- 读取 `validated_signals`
- 让 LLM 决定哪些 expert 参与

允许返回的节点只有：

- `order_expert`
- `safety_expert`
- `environment_expert`

### 10.2 Evaluate 模式

当 `expert_results` 已经有内容时，orchestrator 进入 evaluate 模式：

- 读取所有专家结果；
- 判断是否需要生成告警。

它只允许输出：

- `alert_manager`
- `FINISH`

### 10.3 安全护栏

这里做了两层保护：

1. LLM 决策本身通过结构化输出约束。
2. 代码再次过滤非法节点，避免：
   - dispatch 阶段返回 `alert_manager`
   - evaluate 阶段返回 expert
   - 错误结果造成循环

如果 LLM 调用失败：

- dispatch 阶段回退到“全专家都跑”；
- evaluate 阶段回退到 `alert_manager`。

整体偏保守。

## 11. 三个专家节点

项目把问题域拆成三个专家：

- `order_expert`
  交通秩序、违停、占道、拥堵、异常排队。
- `safety_expert`
  碰撞、逆行、危险穿越、冲突风险。
- `environment_expert`
  积水、施工、障碍物、低能见度、异常光照。

### 11.1 输入来源

专家统一读取：

- `validated_text`
- `validated_signals`
- `history_context`

也就是说，专家不再直接看原图，而是消费 validator 之后的标准化结果。

### 11.2 规则优先

每个 expert 都先走本地规则判断，例如：

- `blocked_lanes > 0` -> `lane_obstruction`
- `queueing=True` 且多帧持续 -> `abnormal_queue`
- `collision_cue=True` -> `collision_or_suspected_collision`
- `water_present=True` -> `flooding`

这些规则还会补充：

- `severity`
- `confidence`
- `impact_scope`
- `persistence`
- `recommended_actions`

### 11.3 history_context 的作用

`history_context` 是这个项目相比单帧识别更“运营化”的地方。

它会保留最近几帧的：

- `validated_scene`
- `validated_text`
- `validated_signals`
- `expert_results`

专家会用它判断：

- 是否是新问题；
- 是否在持续；
- 是否在恶化。

例如：

- 连续多帧 queueing -> `persistent` 或 `worsening`
- 连续多帧有停滞车辆 -> `vehicle_loitering`

### 11.4 RAG 兜底

如果规则判断：

- 一个问题都没命中；
- 或命中结果全部低置信度；

则触发 Pinecone 检索 + LLM 专家评估。

流程是：

1. 用 `validated_text` 检索对应 namespace。
2. 将检索到的文档送入 expert LLM。
3. 让模型基于“场景文本 + 检索上下文”输出：
   - `summary`
   - `findings`
   - `severity`
   - `recommended_action`
   - `citations`
4. 若 LLM 结果不是低严重度空结论，则把它补成一个 `llm_inferred_*` 场景并并入规则结果。

所以专家是**规则优先，RAG 增强兜底**，不是纯 LLM。

## 12. 告警生成链路

`alert_manager_node(...)` 是 frame 流程的终点。

### 12.1 触发条件

只有 orchestrator evaluate 阶段认为需要告警时，才会进入这里。

### 12.2 告警组装四步

每个 expert result 会依次经过 4 个工具：

1. `classification.py`
   用 LLM 把 expert findings 归类成告警 `sub_type / severity / message`。
2. `lta_lookup.py`
   若开启 LTA 且能解析到 camera_id，则向官方数据源查询附近事件做佐证。
3. `rendering.py`
   组装完整 alert dict。
4. `dispatcher.py`
   落盘 JSON 并写 dispatch log。

### 12.3 alert 的字段含义

一个 alert 大致包含：

- `alert_id`
  由 `image_path + expert_name` 生成的确定性 ID，保证重复处理同一输入时幂等。
- `domain / sub_type / severity / message`
- `source_expert`
- `evidence`
- `regulations`
  专家 RAG 引用来源。
- `department`
  模拟接收部门。
- `image_path`
- `lta_corroboration`
  官方事件近邻匹配结果。

### 12.4 LTA 佐证逻辑

LTA 佐证不是必须成功的外部依赖。失败时系统不会中断，只会：

- 返回 `api_available=False`
- 继续生成 alert

这说明官方事件校验是“增强可信度”的侧路，而不是主流程的硬前置。

## 13. RunRecord：系统事实账本

`tools/run_records.py` 定义了运行日志事实格式。

### 13.1 每帧必写

不管结果是：

- `blocked`
- `clean`
- `alerted`
- `failed`

都会写一条 `RunRecord` 到 `data/oa_log/YYYY-MM-DD.jsonl`。

### 13.2 RunRecord 的价值

它是项目里最核心的中间资产，因为它同时服务于：

- dashboard 的状态回显；
- 日报生成；
- 离线评估；
- 运行审计；
- 故障回溯。

### 13.3 metadata 的作用

每条记录都带 `metadata`，里面会收集：

- 各阶段用到的模型；
- 对应 prompt 版本；
- 命中的 policy 版本；
- 是否触发 RAG；
- 是否调用外部服务。

这让项目具有较好的可观测性和可追责性。

## 14. Dashboard 运行面

dashboard 并不是只读展示，而是一个轻量控制面。

### 14.1 两层组成

1. `dashboard/server.py`
   一个原生 `http.server` 实现的小型 HTTP 服务。
2. `dashboard/data.py`
   聚合 camera reference、本地图片、runtime status、报告列表，生成前端 JSON。

### 14.2 runtime status 文件

后台 daemon 会不断写 `data/dashboard/live_status.json`，内容包括：

- 每个 camera 当前状态；
- 最近心跳；
- 当前处理阶段；
- 最近摘要；
- 最近 alert；
- 已批准可展示的图片路径；
- 状态历史、分析历史；
- 当前运行中的 agent。

### 14.3 approved frame 机制

dashboard 显示图片时优先使用 `approved_image_path`，而这个字段只有在 guardrail 允许展示后才会写入。

这意味着：

- 实时抓到的原图不一定立刻前台可见；
- 只有通过安全闸门的图才进入稳定展示位。

这是很明确的“分析输入”和“前台可展示资产”分离设计。

### 14.4 切换摄像头

`/api/runtime/select-camera` 支持 dashboard 切换后台当前分析摄像头。其实现方式不是在内存里改状态，而是：

1. 停掉当前后台进程；
2. 写入选中 camera 状态；
3. 重启一个新的 `python -m skymirror.main` 进程；
4. 用环境变量把 `TARGET_CAMERA_IDS` 锁到该 camera。

因此 dashboard 实际具备最小化的“运维控制台”能力。

## 15. Daily Report 日报链路

日报是系统的第二条主业务线。

### 15.1 输入不是原始图片，而是 RunRecord

`report_generator.generate_report(...)` 的输入是某天的 `RunRecord` 日志，而不是图片本身。这说明日报关注的是“系统判定与运营输出”，不是重新识图。

### 15.2 报告生成步骤

1. `loader.py`
   读取目标日期 JSONL。
2. `analysis.py`
   计算 overview、temporal、system profile。
3. `select_representative_cases(...)`
   从告警中挑选 3 个代表案例。
4. `rendering.py`
   用模板渲染 Markdown。
5. `llm_factory.narrate(...)`
   只负责将已计算事实转成 prose，不负责凭空算结论。

### 15.3 Hybrid 原则

日报明确采用“事实模板 + LLM 叙述”模式：

- 数据统计、筛选、计数在代码里完成；
- LLM 只做自然语言包装；
- 如果 LLM 失败，就退回模板 fallback 文本。

这使日报更加稳健，也降低幻觉风险。

### 15.4 空日报的处理

即使当天没有告警，系统也不会简单输出“风平浪静”。它会区分：

- log 文件不存在；
- log 文件存在但为空；
- 有处理记录但没有触发告警；

并输出一份 self-diagnostic 报告，提醒这不一定代表系统正常。

这体现出项目对“静默失败”有显式防范。

## 16. RAG 语料与知识底座

### 16.1 三个 namespace

系统把知识库拆成三个 namespace：

- `traffic-regulations`
- `safety-incidents`
- `road-conditions`

分别对应三个专家域。

### 16.2 语料来源

`singapore_corpus.py` 会下载并整理新加坡官方资料，包括：

- LTA AV 指南与表单；
- TR68 相关公开页面；
- Smart Mobility 2030；
- 道路施工与交通控制规范；
- DataMall / OneMap 文档；
- 年报与公共说明材料。

下载后会转成 Markdown 落到 `data/rag/<namespace>/`。

### 16.3 入库方式

`rag_ingest.py` 会：

1. 遍历 namespace 对应目录；
2. 按 chunk size / overlap 切块；
3. 构造 LangChain `Document`；
4. 调 Pinecone upsert。

专家检索时再按 namespace 拉回相关文档。

## 17. 治理与安全控制

`tools/governance.py` 和 `governance/policy.yaml` 提供了运行时治理能力。

### 17.1 当前治理覆盖面

- 限制不同 capability 可用的模型名单；
- 限制远程图片允许的域名；
- 限制 RAG namespace；
- 控制是否启用 LTA lookup；
- 设置 prompt 输入长度上限；
- 控制 tracing 开关。

### 17.2 fail-closed 倾向

多个位置都体现出保守策略：

- 远程图域名不在白名单则拒绝；
- 图片异常直接 blocked；
- guardrail 失败直接 blocked；
- orchestrator LLM 失败走保守 fallback；
- LTA 失败不阻塞主流程，但会标记 unavailable。

项目整体设计是“宁可保守、不轻易放行”。

## 18. 测试与发布门槛

### 18.1 测试覆盖重点

从 `tests/` 可看出项目重点验证这些层面：

- VLM 和 validator 的结构化输出与回退行为；
- experts 的规则命中、history 推断、RAG fallback；
- alert manager 的分类、渲染、落盘、LTA 佐证；
- dashboard 数据聚合与 approved frame 机制；
- main.py 的多摄像头与运行节奏；
- 报告生成与空日报分支；
- Pinecone 入库和检索适配；
- runtime governance 评估。

### 18.2 发布门槛

`governance/release_thresholds.yaml` 约束了：

- schema valid rate
- guardrail regression rate
- validator regression rate
- expert routing regression rate
- alert evidence completeness rate
- report generation success rate

其中 `scripts/evaluate_runtime.py` 会利用 fixture 执行这些指标校验。

## 19. 关键设计特点总结

### 19.1 这是“多阶段收敛系统”，不是单模型直出

系统把一次识别拆成：

- guardrail
- VLM
- validator
- orchestrator
- expert
- alert

每一层都在收敛上一层的自由度。

### 19.2 规则和 LLM 是混合关系

项目不是纯 prompt 驱动：

- 路由和专家判断都带强规则；
- RAG 只在必要时兜底；
- 日报统计完全代码计算；
- LLM 更多承担抽取、校验、叙述和归类角色。

### 19.3 运行时和展示层解耦

后台 daemon、dashboard、alert 文件、日报文件之间通过本地文件协议协作，而不是强耦合 RPC：

- `RunRecord` 给审计与日报；
- `live_status.json` 给 dashboard；
- `data/alerts/` 给告警归档；
- `data/reports/` 给历史查看。

这让模块边界比较清晰，也便于离线调试。

### 19.4 项目非常重视可解释性

可解释性体现在多个地方：

- validator 输出更保守的 canonical scene；
- expert 返回 scenarios + citations；
- alert 携带 evidence 和 regulations；
- report 只基于事实数据叙述；
- metadata 记录模型、prompt、policy、外部调用。

## 20. 一张简化的数据流图

```text
LTA Camera API / Local Image
        |
        v
 image_guardrail
        |
        v
    vlm_agent
        |
        v
 validator_agent
        |
        v
 orchestrator(dispatch)
        |
        +------> order_expert --------+
        +------> safety_expert -------+--> orchestrator(evaluate) --> FINISH
        +------> environment_expert --+                           \
                                                                   -> alert_manager
                                                                           |
                                                                           +--> data/alerts/
                                                                           +--> data/oa_log/
                                                                           +--> dashboard status

data/oa_log/YYYY-MM-DD.jsonl
        |
        v
 report_generator
        |
        v
 data/reports/YYYY-MM-DD.md
```

## 21. 代码阅读建议顺序

如果后续要继续深入这个项目，推荐按下面顺序读：

1. `src/skymirror/main.py`
2. `src/skymirror/graph/state.py`
3. `src/skymirror/graph/graph.py`
4. `src/skymirror/agents/vlm_agent.py`
5. `src/skymirror/agents/validator.py`
6. `src/skymirror/agents/orchestrator.py`
7. `src/skymirror/agents/experts.py`
8. `src/skymirror/agents/alert_manager.py`
9. `src/skymirror/tools/run_records.py`
10. `src/skymirror/dashboard/data.py`
11. `src/skymirror/agents/report_generator.py`

这样最容易先建立主流程，再补充周边支撑能力。

## 22. 结论

SKYMIRROR 当前已经不是一个单点 agent demo，而是一个围绕“交通摄像头异常分析”搭出来的完整运行闭环：

- 有实时采集；
- 有多阶段模型链；
- 有专家分工；
- 有知识检索；
- 有告警产出；
- 有运行归档；
- 有日报总结；
- 有 dashboard 展示；
- 有治理与离线评估。

如果用一句话概括它的核心逻辑，就是：

**把交通摄像头帧通过保守校验、专家路由和规则/RAG 混合分析，转成可解释、可追踪、可运营消费的告警与日报。**
