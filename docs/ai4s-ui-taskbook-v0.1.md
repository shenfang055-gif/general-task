# AI4S 桌面 UI 评测题集与贡献指南 v0.1

> 面向：内部 task 作者、领域 reviewer、评测操作员  
> 范围：生命科学、物质科学、地球科学；9 个 UI-native task samples  
> 对照产品：Codex  
> 配套输入：[`docs/inputs/`](./inputs/README.md)  
> 逐题 Oracle：[`docs/oracles/`](./oracles/README.md)

## 0. 这份文档解决什么

这是一份面向桌面客户端的**内部出题与执行手册**。

每道题把一个小型 `inputs/` 目录交给客户端，让 harness 在同一 workspace 的 `output/` 中产生科研 artifact。冻结 artifact 后，按预定义的 deterministic 规则评分；推荐使用独立 Python oracle，也允许使用严格的人工检查表。最后只对解释、局限和图表可读性做短人工/LLM judge。

## 1. UI 评测怎么运行

### 1.1 Workspace

每次 run 使用全新目录：

```text
workspace/
├── inputs/         # 复制某一道题的配套输入；运行中不得修改
└── output/         # 开始时为空；harness 的全部正式交付
```

Oracle、gold answer 和 judge rubric 不得放入 workspace。不要把聊天文本复制成 artifact；artifact 必须由 harness 写入 `output/`。

### 1.2 先看一张任务卡

任务卡是操作员、task 作者和 grader reviewer 共用的一页说明。下面是本文 `life-l2-paired-expression` 的缩略样例；字段含义见 [§3.1](#31-字段解释)。

> **任务卡 sample**
>
> - **ID**：`life-l2-paired-expression`
> - **Domain / sub-domain**：`life_science / transcriptomics`
> - **Level / time**：`L2 / 30 分钟`
> - **Anchor / related capabilities**：`A / D,P,X,V,I,G`
> - **来源思想**：ScienceAgentBench 的阶段式 workflow；CompBioBench 的 metadata mapping
> - **Inputs**：`inputs/expression_log2cpm.tsv`、`inputs/metadata.csv`；合成数据，约 10 KB
>
> **Prompt**
>
> `inputs/expression_log2cpm.tsv` 是表达矩阵，`inputs/metadata.csv` 是乱序的 donor/condition/batch 信息。按 `sample_id` 连接数据；对每个 donor 计算 `treated-control`，再报告每个 gene 的平均配对差。`mean_paired_delta >= 0.5` 为 `up`，`<= -0.5` 为 `down`，其余为 `stable`。将结果写入 `output/paired_effects.csv`，列严格为 `gene_id,mean_paired_delta,direction`，每个 gene 恰好一行，数值必须 finite；另写 `output/summary.json`，至少含 `top_up_gene,top_down_gene,n_donors`；再写 `output/report.md`（≤200 字）和可从 workspace 根目录运行的 `output/analyze.py`。不要按列位置猜配对。
>
> **Deliverables**：`paired_effects.csv`、`summary.json`、`report.md`、`analyze.py`
>
> **Hard gates**：按 ID join；contrast 必须为 `treated-control`；gene set 完整；脚本能从原始 inputs 重建主表。
>
> **DeterministicArtifactScore（0–80）**：coverage 10；paired delta 40；direction 15；summary 5；脚本 10。评分方式：Python oracle。
>
> **JudgeScore（0–20）**：证据 5；方法 5；克制 5；可读性 5。
>
> **Ablation**：skill=`paired-expression-analysis`；MCP=`biostats.paired_contrast(matrix,metadata)`。

操作员只需要辨认三个位置：把 **Prompt** 原样粘贴到 UI；把 **Inputs** 准备到 workspace；结束后冻结并评分 **Deliverables**。Hard gates、rubric 和 ablation 配置供评测方使用，不粘贴给 harness。

### 1.3 操作员 SOP

1. 复制该题的 `[inputs/<task-id>/](./inputs/)` 到新 workspace 的 `inputs/`，创建空 `output/`。
2. 在客户端中新建会话并打开 workspace；确认启用的是本次实验条件。
3. 将任务卡中的 **Prompt** 原样粘贴一次，开始计时。
4. 只处理统一的文件/命令权限弹窗；不得给科学提示、指出错误或补充步骤。
5. 到时停止。关闭客户端对 workspace 的写入，记录是否 crash、超时或发生人工干预。
6. 对冻结后的 workspace 运行该题的 Python oracle 或人工 deterministic 检查表；再对 `report.md` 等非确定项 blind judge。

如果操作员给了科学帮助，该 run 不进入主结果。UI 正常结束但没有 artifact，是 harness 失败，不是“无效数据”。

### 1.4 最小运行记录

每个 run 填一行。下面的值只示范填写格式：


| task_id                     | harness | condition | client/model           | trial | wall_min | run_status  | hardgate_pass | deterministic_score | judge_score | intervention/notes      |
| --------------------------- | ------- | --------- | ---------------------- | ----- | -------- | ----------- | ------------- | ------------------- | ----------- | ----------------------- |
| `life-l2-paired-expression` | `Codex` | `C0`      | `Codex / gpt-5（UI 显示）` | 1     | 27.4     | `completed` | `true`        | 72                  | 15          | `permission_only；无科学提示` |


字段填写规则：


| 字段                    | 填什么                                               |
| --------------------- | ------------------------------------------------- |
| `task_id`             | 任务卡中的唯一 ID。                                       |
| `harness`             | 被测产品名；版本可见时一并记录，不可见则只写产品名。                        |
| `condition`           | 实验臂：`C0/T0/T1/T2`，定义见 [§5.1](#51-实验臂)。            |
| `client/model`        | UI 实际显示的客户端和模型名；未知部分写 `N/A`。                      |
| `trial`               | 同一 `task × condition` 的第几次独立运行，从 1 开始。            |
| `wall_min`            | 从粘贴 Prompt 到停止写入 workspace 的墙钟分钟数。                |
| `run_status`          | `completed`、`timeout`、`crash` 或 `operator_abort`。 |
| `hardgate_pass`       | 所有 hard gates 是否通过；未完成评分时写 `pending`。             |
| `deterministic_score` | 固定规则得到的 `0–80` 分；不是主观质量分。                         |
| `judge_score`         | blind judge 得到的 `0–20` 分。                         |
| `intervention/notes`  | 写 `none`、`permission_only` 或具体科学干预；同时记导出异常等必要事实。  |


模型快照或 token 不可见时写 `N/A`，不要填 0 或猜测。

## 2. 难度与能力代码

### 2.1 L1–L3


| Level                | 定义                                 | UI 时限建议  | 题目特征              |
| -------------------- | ---------------------------------- | -------- | ----------------- |
| L1 Atomic            | 读取少量本地输入，完成一次关键科学判断并输出结构化 artifact | 15–20 分钟 | 1–3 个关键操作；用于健康检查  |
| L2 Workflow          | 串联数据检查、计算、验证和交付                    | 30–45 分钟 | 4–7 个有意义步骤；MVP 主体 |
| L3 Research workflow | 修复已有分析、处理异常或从方法说明复现结论              | 60–90 分钟 | ≥8 个步骤；要求可重跑和局限说明 |


难度来自科学 workflow，而不是 prompt 长度、冷知识、文件数量或故意缺依赖。L3 必须比 L2 多出恢复、复现或长程状态责任。

### 2.2 精简能力代码


| Code | 能力                        | Artifact 中的可观察证据            |
| ---- | ------------------------- | --------------------------- |
| D    | Data discovery            | 找到正确输入，忽略 decoy/stale 文件    |
| P    | Planning                  | 多个交付物完整、相互一致                |
| T    | Tool / skill / MCP use    | 能使用可用科学工具；不按具体调用顺序评分        |
| A    | Parameter / schema / unit | contrast、阈值、单位、ID、字段正确      |
| X    | Scientific computation    | 数值、统计、结构或模型结果正确             |
| V    | Validation                | QC、finite、边界、mask、守恒或收敛检查   |
| R    | Recovery                  | 发现并修复错误代码、坏输入或 stale result |
| I    | Interpretation            | 结论由 artifact 支持，不过度外推       |
| O    | Output                    | 路径、格式、字段和图表符合 contract      |
| G    | Reproducibility           | 保存可重跑脚本和关键参数                |


每题选 1 个 anchor capability，另标 2–5 个 related capabilities。9 题太少，能力标签只用于覆盖检查，不用于发布细粒度能力排行榜。

## 3. 极简 task contract

每个内部贡献对应一张与 [§1.2 样例](#12-先看一张任务卡) 同结构的任务卡。任务卡是题目的唯一执行入口，应让另一位同事不经口头解释就能准备 workspace、运行和评分。

### 3.1 字段解释


| 字段                           | 样例值                                | 作者需要说明什么                                              |
| ---------------------------- | ---------------------------------- | ----------------------------------------------------- |
| `ID`                         | `life-l2-paired-expression`        | 全局唯一、稳定、可作为目录名的短 ID。                                  |
| `Domain`                     | `life_science`                     | `life_science`、`materials_science` 或 `earth_science`。 |
| `Sub-domain`                 | `transcriptomics`                  | 选一个主要科学问题所属方向；参考 [§3.2](#32-sub-domain-参考表)。          |
| `Level / time`               | `L2 / 30 分钟`                       | 按 §2 定级，并给 UI 单次运行上限。                                 |
| `Anchor / related`           | `A / D,P,X,V,I,G`                  | 1 个主能力和 2–5 个相关能力。                                    |
| `来源思想`                       | `ScienceAgentBench + CompBioBench` | 指明借鉴的 workflow、rubric 或 verifier 思想；不必复制原题。           |
| `Inputs`                     | 两个文件、合成、约 10 KB                    | 文件作用、关键字段、来源/许可、大致大小和已知 decoy。                        |
| `Prompt`                     | §1.2 的可粘贴正文                        | 目标、输入位置、科学约束和 output contract；一次粘贴即可执行。               |
| `Deliverables`               | CSV、JSON、报告、脚本                     | 固定路径、格式、schema、单位、缺失值和可重跑要求。                          |
| `Hard gates`                 | ID join、contrast、完整性               | 2–4 个一旦错误就不能称为科学完成的条件。                                |
| `DeterministicArtifactScore` | `0–80，Python oracle`               | 每项分值、明确通过条件、容差，以及 Python 或人工检查方式。                     |
| `JudgeScore`                 | `0–20`                             | 只评证据表达、方法说明、克制和可读性。                                   |
| `Ablation`                   | 一个 skill、一个 MCP                    | 通用能力占位符及其预期减少的错误，不放答案。                                |




### 3.2 Sub-domain 参考表

这里的 sub-domain 用于题目路由、覆盖检查和 reviewer 分配，不是唯一学科标准。高层边界参考 [OECD Fields of R&D](https://www.oecd.org/content/dam/oecd/en/publications/reports/2015/10/frascati-manual-2015_g1g57dcb/9789264239012-en.pdf)；实用细分结合 [NSF Biological Sciences](https://www.nsf.gov/bio/about)、[NIH scientific focus areas](https://irp.nih.gov/our-research/scientific-focus-areas)、[DOE Materials Sciences and Engineering](https://www.energy.gov/science/bes/basic-energy-sciences) 和 [NASA Earth Science focus areas](https://science.nasa.gov/earth-science/programs/research-analysis/)，并按当前 AI4S benchmark 的可执行 workflow 做了整理。

**生命科学** `life_science`


| `sub_domain`                             | 典型任务                            |
| ---------------------------------------- | ------------------------------- |
| `genomics_and_genetics`                  | 变异检测、遗传模式、比较基因组、群体遗传            |
| `transcriptomics`                        | bulk RNA-seq、差异表达、剪接、表达响应       |
| `single_cell_and_spatial`                | 细胞注释、聚类、轨迹、多模态/空间映射             |
| `epigenomics_and_regulation`             | ATAC、甲基化、调控元件、染色质分析             |
| `proteomics_and_metabolomics`            | 蛋白/代谢物定量、通路、质谱表格分析              |
| `structural_and_molecular_biology`       | 序列—结构、蛋白复合物、分子功能                |
| `systems_and_synthetic_biology`          | 网络、通路、动力学、工程化生物系统               |
| `microbiology_and_metagenomics`          | 菌群组成、宏基因组、病原体/耐药基因筛查            |
| `organismal_ecology_and_evolution`       | 生理、行为、种群、生态与进化                  |
| `biomedical_and_clinical_bioinformatics` | 临床 metadata、队列分析、候选标志物；不得用于真实诊断 |


**物质科学** `materials_science`


| `sub_domain`                             | 典型任务                          |
| ---------------------------------------- | ----------------------------- |
| `crystallography_and_structure`          | CIF/POSCAR 解析、对称性、晶格与结构 QC    |
| `characterization_and_spectroscopy`      | XRD、散射、显微、光谱匹配与反演             |
| `phase_stability_and_thermodynamics`     | formation energy、凸包、EOS、相图与相变 |
| `electronic_magnetic_optical_properties` | 能带、态密度、磁/光/热性质                |
| `defects_interfaces_and_surfaces`        | 空位、掺杂、界面、表面与吸附                |
| `mechanics_and_fracture`                 | 弹性、塑性、断裂、疲劳与力学曲线              |
| `atomistic_simulation`                   | DFT/MD/MLIP 工作流、收敛与轨迹分析       |
| `synthesis_and_processing`               | 配方、工艺窗口、热处理、过程—结构关系           |
| `electrochemistry_and_energy_materials`  | 电池、离子输运、储能与能源材料               |
| `catalysis`                              | 催化路径、吸附能、活性/选择性               |
| `materials_informatics`                  | 材料数据库、性质预测、筛选与主动学习            |


**地球科学** `earth_science`


| `sub_domain`                             | 典型任务                              |
| ---------------------------------------- | --------------------------------- |
| `geospatial_and_gis`                     | CRS、矢量/栅格操作、空间连接、zonal statistics |
| `remote_sensing`                         | 指数、分类、变化检测、云/NoData mask          |
| `environmental_monitoring`               | 站点/传感器 QC、污染与环境时序                 |
| `hydrology_and_water_cycle`              | 降雨—径流、流域、水量平衡、地下水                 |
| `atmosphere_weather_and_air_quality`     | 天气、气溶胶、大气成分与空气质量                  |
| `climate_variability_and_change`         | 气候趋势、极端事件、归因与不确定性                 |
| `ocean_and_coastal`                      | 海洋、海岸、海平面、海气相互作用                  |
| `cryosphere`                             | 冰川、积雪、海冰与冻土                       |
| `geology_geophysics_and_solid_earth`     | 地质、地震、火山、地球内部与形变                  |
| `geomorphology_and_terrain`              | DEM、坡度、地貌与侵蚀                      |
| `ecosystems_land_cover_and_carbon_cycle` | 土地覆盖、生态系统、植被与碳循环                  |
| `natural_hazards_and_disasters`          | 洪水、火灾、滑坡、地震等风险评估                  |


每题只填一个主要 `sub_domain`；跨方向信息放在可选 `tags`，例如科学问题是流域径流、数据来自遥感时，填 `hydrology_and_water_cycle`，可加 `remote_sensing` tag。列表未覆盖的新方向可以补充，但贡献者需给出一句定义、一个代表 workflow，并由领域 reviewer 确认命名不会与现有项重复。

### 3.3 Prompt 写法

Prompt 只写：目标、输入位置、科学约束、交付物。不要列 gold 步骤或推荐库；不同科学等价实现都应允许。

### 3.4 Output contract

Output contract 最少回答六件事：写到哪里、什么格式、哪些字段、谁必须唯一、单位是什么、缺失值怎么写。以下片段可以直接改写进 Prompt。

**CSV 示例**

> 将结果写入 `output/sample_qc.csv`，列严格为 `sample_id,read_count,q30_fraction,status`；输入中的每个 `sample_id` 恰好一行且不得重复，`read_count` 为非负整数，`q30_fraction` 为 `[0,1]` 内有限小数，无法计算时留空并令 `status=invalid`。

**JSON 示例**

> 写入 `output/summary.json`，必须包含 `n_valid`（整数）、`mean_dnbr`（数值）、`claim_supported`（布尔值）和 `warnings`（字符串数组）；不得输出 `NaN` 或 `Infinity`，所有统计必须能由主 CSV 重算。

**图、报告和脚本示例**

> 保存 `output/hull.png`，横轴为 `x_B`，纵轴为 `formation energy (eV/atom)`，稳定相和亚稳相使用不同图例；另写 `output/report.md`（≤200 字），只总结由表格支持的结论与一项局限；保存可从 workspace 根目录运行的 `output/analyze.py`，它只读取 `inputs/` 并可重新生成上述正式文件。

对 GeoTIFF、CIF、HDF5 等领域格式，还要在 Prompt 中声明 CRS/NoData、晶胞与单位、dataset key 等可验证属性。

- 正式文件全部放 `output/`，文件名固定；
- 表格必须声明列名、ID 唯一性、单位和缺失值写法；
- 数值必须 finite；不允许用聊天回答替代 CSV/JSON；
- L2/L3 默认交付一个可重跑 `.py`；
- 报告默认不超过 300 字，L3 可放宽到 500 字；
- 单题正式 artifact 建议不超过 50 MB。



### 3.5 Hard gate

Hard gate 只放“错了就不能称为完成”的条件，例如：

- 生命：sample mapping、contrast、quality encoding、遗传模式；
- 材料：结构 identity、per-atom 单位、稳定相、非收敛结果；
- 地球：时间方向、NoData/cloud mask、面积/温度单位、水量连续性。

不要把“用了某个 Python 库”“调用了 MCP”或“图够漂亮”设为 gate。

## 4. 打分规则



### 4.1 统一计分

```text
TotalScore = DeterministicArtifactScore (0–80)
             + JudgeScore (0–20)

StrictSuccess = all hard gates pass AND TotalScore >= 80
```

Hard gate 失败时仍保留诊断分，但 `TotalScore` 对外显示最多 49，`StrictSuccess=0`。缺失核心 artifact 时 deterministic score 为 0。

所有题还有一个共用 gate：Prompt 声明的 deliverables 必须全部存在且可解析；缺报告、脚本或图不能算完整交付。

不要用单一平均分掩盖错误；至少同时报：Strict Success、Deterministic Score、Judge Score、wall time 和 hard-gate failure。

### 4.2 DeterministicArtifactScore：Oracle 推荐但可选

“Deterministic”表示：同一份冻结 artifact 交给不同 reviewer，按同一版本规则会得到同一分数；不等于必须自动化。作者至少选择下面一种方式：

- **Python oracle（推荐）**：适合行数多、数值多、有容差、需要重算或跨文件校验的题；
- **人工 deterministic 检查表**：适合输入和输出很小、10 分钟内可以逐项核对的题。

两种方式都应优先检查：

```text
文件存在且可解析
→ schema / 类型 / 必要字段
→ ID/row set、覆盖率、顺序无关性与重复项
→ finite、单位、范围、数值 tolerance
→ 科学 property / invariant
→ 主表、summary、图底层数据之间的一致性
→ 需要时从原始 inputs 重跑
```

推荐的 80 分分配范围：


| 检查类            | 建议分值  | 典型检查                      |
| -------------- | ----- | ------------------------- |
| 文件与 schema     | 5–10  | 文件名、可解析、列/键、类型            |
| ID 与覆盖         | 10–15 | expected set、唯一性、无漏行/额外行  |
| 数值与单位          | 20–35 | finite、范围、方向、换算、tolerance |
| 科学 invariant   | 15–25 | 配对关系、守恒、mask、收敛、遗传模式、稳定相  |
| 跨 artifact 一致性 | 5–10  | summary 可由主表重算，图轴/单位与数据一致 |
| 可重跑性           | 5–10  | 脚本从原始 inputs 重建正式结果       |


没有 Python oracle 时，任务卡必须附一张**隐藏的人工检查表**，每项写明分值、证据、通过条件和容差。不得写“结果基本合理”一类规则。例如：


| criterion              | 分值  | 固定通过条件                                         | reviewer 如何检查    |
| ---------------------- | --- | ---------------------------------------------- | ---------------- |
| `D1_files_schema`      | 10  | 4 个文件均存在；CSV 列严格匹配；JSON 可解析                    | 打开文件并对照 contract |
| `D2_gene_set`          | 10  | gene ID 与 hidden expected set 完全相同且唯一          | 集合比对，忽略行顺序       |
| `D3_paired_delta`      | 35  | 每个 delta 与 hidden answer 的绝对误差 `≤1e-6`         | 用审阅表逐行核对         |
| `D4_direction`         | 15  | 所有方向均符合公开阈值                                    | 由 delta 重算       |
| `D5_cross_consistency` | 5   | summary 的 top gene 和 donor 数可由 CSV/metadata 重算 | 手工重算三项           |
| `D6_rerun`             | 5   | `analyze.py` 在 workspace 副本中运行成功并重建主表          | 运行一次并比较          |


人工检查项只能是 `pass/fail` 或预先定义的比例计分，例如“8 个 ID 每个 2 分”；不能临场给半分。首批至少两位 reviewer 独立评分同一正确解和一个 deliberate-wrong 解；若分数不一致，应先改检查表。

Gold workflow 不做 exact match。L2/L3 的生成脚本应在隔离的 workspace 副本中重跑；Python grader 不要直接 import 未受信代码。

本文 9 个 samples 均提供独立 Python oracle，样例命令：

```bash
python3 docs/oracles/earth-l2-burn-severity/oracle.py \
  --workspace /path/to/workspace
```

Oracle 不执行 harness 生成的脚本；它只做静态检查。真正的 clean rerun 应放在隔离 CI/container 中。



### 4.3 精简人工/LLM judge

Judge 看不到 harness 和实验条件。只评四项，每项 `0 / 3 / 5`：


| 项目          | 0                   | 3           | 5                  |
| ----------- | ------------------- | ----------- | ------------------ |
| Evidence    | 结论与 artifact 冲突或无证据 | 主结论正确但引用不完整 | 主要结论均能定位到 artifact |
| Method      | 方法/单位有实质错误          | 基本正确但有遗漏    | 方法、方向、单位清楚且正确      |
| Restraint   | 明显过度外推              | 有泛化或模糊表述    | 结论边界与证据一致          |
| Readability | 缺失或难以理解             | 可用但有小问题     | 简洁、图表/术语清楚         |


Judge 不得推翻 hard gate。没有图的任务，Readability 只看表格和短报告。建议固定 judge prompt/model；前 20% 结果由领域同事复核。

## 5. Baseline 与轻量消融



### 5.1 实验臂


| Arm | 配置                                | 用途                 |
| --- | --------------------------------- | ------------------ |
| C0  | Codex native，无额外 domain skill/MCP | 产品对照               |
| T0  | 待测 harness，bare                   | 目标产品空白臂            |
| T1  | T0 + 对应 domain skill              | 测通用 workflow 指令的收益 |
| T2  | T1 + 对应 local scientific MCP      | 测 typed tool 的额外收益 |


Skill 可包含方法 checklist、工具说明、常见失败模式；不得包含本题 ID、文件名、gold 数值或答案。MCP 只能提供通用原子能力，不得提供 `solve_this_task()`。

做消融时，T0/T1 必须仍能从原始 inputs 获得相同科学信息。若 MCP 独占必要 reference，则这只是“工具是否可用”的产品对比，不能称 MCP uplift。

### 5.2 控制工作量

建议 MVP 只跑 24 次：

- 9 题：`C0 vs T2`，共 18 runs；
- 3 道 L2 代表题：补 `T0/T1`，共 6 runs；
- 全部先 `k=1`。只有 hard-gate 翻转或结论关键的 run 再复跑 2 次。

不对 9 题的小差异做统计显著性主张。

### 5.3 结果占位


| Slice        | C0   | T0   | T1   | T2   | Skill gain `T1-T0` | MCP gain `T2-T1` |
| ------------ | ---- | ---- | ---- | ---- | ------------------ | ---------------- |
| Life L2      | `__` | `__` | `__` | `__` | `__`               | `__`             |
| Materials L2 | `__` | `__` | `__` | `__` | `__`               | `__`             |
| Earth L2     | `__` | `__` | `__` | `__` | `__`               | `__`             |
| Mean         | `__` | `__` | `__` | `__` | `__`               | `__`             |


这里的“收益 xxx”必须由 paired result 填入，不预设为正。同时记录 hard-gate pass 和 wall time，防止“分数略升但科学失败更多”。

## 6. 9 个 UI-native task samples

这 9 题使用本项目新建的小型合成输入；上游 benchmark 仅提供 workflow 和评分思想参考。

### 6.1 生命科学



#### LIFE-L1：蛋白 marker cluster 注释

- ID：`life-l1-cell-annotation`
- Domain / sub-domain：`life_science / single_cell_and_spatial`
- Level/time：L1，15 分钟
- Anchor：`I`；Related：`D,A,O`
- 来源思想：TB-Science spatial cell annotation 的固定 vocabulary 与 cluster-level grading；ScienceAgentBench 的 artifact saving。
- Inputs：[目录](./inputs/life-l1-cell-annotation/)；2 个合成 CSV，约 12 KB

**Prompt**

> `inputs/cluster_markers.csv` 是同一组织切片中各细胞 cluster 的聚合 marker 强度。请仅使用 `inputs/cell_type_vocabulary.csv` 中的标签，为每个 cluster 选择一个最受 marker 支持的细胞类型。写入 `output/cell_annotations.csv`，列严格为 `cluster,cell_type,evidence_markers`；每个 cluster 恰好一行，`evidence_markers` 用 `;` 分隔。另写 `output/report.md`，不超过 150 字，概括主要谱系和最需谨慎的注释。不要修改 inputs。

**Hard gates**

- 6 个 cluster 完整、唯一；标签全部来自 vocabulary；
- 注释与 marker identity 一致，不把低特异标签替代有明确证据的类型；
- `report.md` 存在，且不把合成 marker 当临床诊断。

**DeterministicArtifactScore（0–80，Python oracle）**：schema/coverage 10；正确标签 45；evidence marker 15；报告存在 10。

**JudgeScore（0–20）**：按 §4.3；重点看证据是否引用正确 marker，是否承认聚合 marker 不能证明更细亚型。

**Ablation**：skill=`cell-marker-annotation-checklist`；MCP=`bio.marker_reference(markers)`。预期减少谱系/marker 误读，不提供本题 cluster 答案。

#### LIFE-L2：配对样本表达响应

- ID：`life-l2-paired-expression`
- Domain / sub-domain：`life_science / transcriptomics`
- Level/time：L2，30 分钟
- Anchor：`A`；Related：`D,P,X,V,I,G`
- 来源思想：ScienceAgentBench 的 loading→processing→analysis→saving；CompBioBench 的 metadata mapping；BioAgent Bench 的结构化结果。
- Inputs：[目录](./inputs/life-l2-paired-expression/)；表达矩阵与乱序 metadata，合成，约 12 KB

**Prompt**

> `inputs/expression_log2cpm.tsv` 是表达矩阵，`inputs/metadata.csv` 是乱序的 donor/condition/batch 信息。按 `sample_id` 连接数据；对每个 donor 计算 `treated-control`，再报告每个 gene 的平均配对差。`mean_paired_delta >= 0.5` 为 `up`，`<= -0.5` 为 `down`，其余为 `stable`。输出 `output/paired_effects.csv`，列为 `gene_id,mean_paired_delta,direction`；输出 `output/summary.json`，至少含 `top_up_gene,top_down_gene,n_donors`；写 `output/report.md`（≤200 字）和可从 workspace 根目录运行的 `output/analyze.py`。不要按列位置猜配对。

**Hard gates**

- sample 必须按 ID join，同 donor 内做 paired contrast；
- contrast 为 `treated-control`，gene set 完整、数值 finite；
- `analyze.py` 可从原始 inputs 重建表格。

**DeterministicArtifactScore（0–80，Python oracle）**：coverage 10；paired delta 40；direction 15；summary 5；脚本 10。

**JudgeScore（0–20）**：按 §4.3；重点看是否指出 IFIT1/CXCL10 等响应方向和 IL7R 反向变化，并说明样本小、合成数据不能外推。

**Ablation**：skill=`paired-expression-analysis`；MCP=`biostats.paired_contrast(matrix,metadata)`。预期主要降低错误 join 和 contrast 方向错误。

#### LIFE-L3：trio 变异优先级流程修复

- ID：`life-l3-variant-prioritization`
- Domain / sub-domain：`life_science / genomics_and_genetics`
- Level/time：L3，60 分钟
- Anchor：`R`；Related：`D,P,A,X,V,I,G`
- 来源思想：BioAgent Bench 的 variant workflow/corrupt-decoy；CORE/AutoMat 的 local code repair 与 claim evidence。
- Inputs：[目录](./inputs/life-l3-variant-prioritization/)；method、pedigree、panel、variants、legacy script 与 stale decoy，合成，约 36 KB

**Prompt**

> 根据 `inputs/method_note.md`、pedigree、gene panel 和 long-format variants，修复或替换 `inputs/legacy_prioritize.py`。不得使用 `stale_candidates.csv` 作为答案。输出 `output/candidates.csv`，列为 `variant_id,gene,inheritance_model,parental_origin`，其中 origin 为 `father|mother|none`；输出 `output/gene_summary.csv`，列为 `gene,inheritance_model,qualifying_variants`；保存 `output/prioritize.py` 和不超过 300 字的 `output/report.md`，说明过滤、遗传模式、修复点和局限。

**Hard gates**

- depth/GQ/AF/consequence 过滤均正确；
- de novo 和 compound-heterozygous 必须使用父母 genotype；
- candidate set、parental origin、gene summary 相互一致；
- 可重跑脚本存在，未复制 stale output。

**DeterministicArtifactScore（0–80，Python oracle）**：candidate set/schema 15；逐 variant 规则 35；gene summary 15；脚本 10；报告存在 5。

**JudgeScore（0–20）**：按 §4.3；重点看报告能否解释 de novo/复合杂合证据，并明确这是合成筛选、不作临床诊断。

**Ablation**：skill=`trio-variant-prioritization`；MCP=`genomics.filter_and_inheritance(records,pedigree)`。预期减少 AF 单位、低深度和遗传模式错误。

### 6.2 物质科学



#### MAT-L1：CIF 入库质检

- ID：`materials-l1-cif-audit`
- Domain / sub-domain：`materials_science / crystallography_and_structure`
- Level/time：L1，20 分钟
- Anchor：`A`；Related：`D,V,O,G`
- 来源思想：MatTools 的 natural-language question→property dictionary→executable verifier；SciAgentGym 的 structure tools。
- Inputs：[目录](./inputs/materials-l1-cif-audit/)；manifest、目标 CIF 与旧导出 decoy，合成，约 16 KB

**Prompt**

> 按 `inputs/sample_manifest.csv` 审核登记的 CIF；忽略未登记的旧导出。输出 `output/structure_report.json`，至少含 `sample_id,source_file,reduced_formula,site_count,a_ang,b_ang,c_ang,volume_a3,space_group_number,nearest_neighbor_a,decoy_ignored`；单位均为 Å 或 Å³。另输出结构等价的 `output/normalized_structure.cif`、可重跑 `output/analyze.py` 和 `output/report.md`（≤150 字），说明结构与主要 QC 风险。

**Hard gates**

- 使用 manifest 指向的结构而不是 decoy；
- formula/site count、晶胞、体积、空间群和最近邻距离正确；
- 单位没有 Å/nm 或 cell/per-atom 混淆。

**DeterministicArtifactScore（0–80，Python oracle）**：source 10；formula/site 10；cell 10；volume 10；symmetry 10；distance 10；decoy 5；normalized CIF 5；脚本 5；报告 5。

**JudgeScore（0–20）**：按 §4.3；重点看单位和 tolerance 说明，且不根据文件名臆测材料来源。

**Ablation**：skill=`crystal-structure-qc`；MCP=`materials.inspect_structure(path)`。预期降低单位、symmetry tolerance 和 decoy 错误。

#### MAT-L2：XRD 两相混合物识别

- ID：`materials-l2-xrd-phase-mixture`
- Domain / sub-domain：`materials_science / characterization_and_spectroscopy`
- Level/time：L2，35 分钟
- Anchor：`X`；Related：`D,P,A,V,I,O,G`
- 来源思想：SciAgentGym 的 XRD peak/index/refinement tasks；TB-Science stacking-disorder diffraction 的数值 artifact；MatTools property grading。
- Inputs：[目录](./inputs/materials-l2-xrd-phase-mixture/)；observed/reference peak 表与测量说明，合成，约 16 KB

**Prompt**

> 按 `inputs/measurement_note.md` 比较 observed peaks 与 reference patterns，识别存在的 phase，并估计非负、和为 1 的 phase fraction。输出 `output/phase_fractions.csv`，列为 `phase,fraction`，必须包含所有三个 reference phase；输出 `output/peak_assignments.csv`，列为 `peak_id,assignment`，共享峰写 `alpha+beta`、噪声写 `noise`；另写 `output/fit_plot.png`、`output/analyze.py` 和 `output/report.md`（≤250 字），说明拟合、自检和不确定性。

**Hard gates**

- fraction 非负、和为 1，gamma decoy 不得被误报为显著相；
- peak identity 和共享峰处理正确；
- 不得把 peak intensity 直接当未归一化相分数。

**DeterministicArtifactScore（0–80，Python oracle）**：fraction contract 15；fraction range/phase presence 25；peak assignments 25；plot 5；脚本 5；报告存在 5。

**JudgeScore（0–20）**：按 §4.3；重点看图与表是否一致，是否说明峰重叠和简单强度模型的局限。

**Ablation**：skill=`powder-xrd-mixture-checklist`；MCP=`materials.match_xrd_peaks(observed,references,tolerance)`。预期降低 peak matching 和归一化错误。

#### MAT-L3：EOS 与压力诱导相变复现

- ID：`materials-l3-eos-transition`
- Domain / sub-domain：`materials_science / phase_stability_and_thermodynamics`
- Level/time：L3，60 分钟
- Anchor：`R`；Related：`D,P,A,X,V,I,G`
- 来源思想：AutoMat/CORE 的 paper/repo claim reproduction；MatTools 的 runnable≠scientifically correct。
- Inputs：[目录](./inputs/materials-l3-eos-transition/)；energy–volume 表、method、legacy script 与 stale result，合成，约 28 KB

**Prompt**

> 按 `inputs/method_note.md` 修复或替换 legacy EOS 分析。必须排除 non-converged row，并在比较前把 cell volume/energy 归一到 per atom；不得使用 `stale_transition.json`。输出 `output/eos_parameters.csv`，列为 `phase,V0_a3_atom,E0_ev_atom,B0_gpa`；输出 `output/transition.json`，含 `transition_pressure_gpa,stable_below,stable_above`；另交 `output/reproduce.py` 和 `output/report.md`（≤300 字），说明修复、相变证据和模型局限。

**Hard gates**

- 排除不收敛点，正确使用 eV/atom 与 Å³/atom；
- 两相 EOS 参数和第一处 0–10 GPa enthalpy crossing 正确；
- stable-below/above 方向与 enthalpy 一致；
- 可重跑脚本存在，未读取 stale result。

**DeterministicArtifactScore（0–80，Python oracle）**：phase/schema 10；EOS 参数 35；transition 20；脚本 10；报告存在 5。数值容差：`V0 0.05 Å³/atom`、`E0 0.005 eV/atom`、`B0 1 GPa`、transition `0.08 GPa`。

**JudgeScore（0–20）**：按 §4.3；重点看是否区分拟合模型与真实材料预测，是否解释 per-cell/per-atom 和 non-convergence 修复。

**Ablation**：skill=`scientific-reproduction-recovery`；MCP=`materials.fit_eos_and_enthalpy(table)`。预期减少 stale、单位和收敛错误。

### 6.3 地球科学



#### EARTH-L1：环境站数据 QC

- ID：`earth-l1-station-qc`
- Domain / sub-domain：`earth_science / environmental_monitoring`
- Level/time：L1，15 分钟
- Anchor：`V`；Related：`D,A,O,I`
- 来源思想：GeoNatureAgent 的 threshold/error handling；ScienceAgentBench 的 data processing milestone。
- Inputs：[目录](./inputs/earth-l1-station-qc/)；站点观测 CSV 与公开 QC rule，合成，约 12 KB

**Prompt**

> 按 `inputs/qc_rules.json` 审核 `station_observations.csv`。输出 `output/qc_flags.csv`，列为 `row_id,reason`，只列需要剔除的行；对 duplicate key 保留最低 row_id。输出清洗后的 `output/clean_observations.csv`，列与输入相同；输出 `output/qc_summary.json`，含 `input_rows,valid_rows,duplicate_rows,invalid_measurement_rows`；另写 `output/report.md`（≤150 字），说明发现的问题，不推测设备或天气成因。

**Hard gates**

- all-and-only duplicate/range-invalid rows 被标记；
- clean table 无重复且没有越界温度、湿度或负降水；
- QC reason 使用公开 vocabulary，不静默删除额外行。

**DeterministicArtifactScore（0–80，Python oracle）**：flags 30；clean row set 20；value ranges 10；summary 10；报告存在 10。

**JudgeScore（0–20）**：按 §4.3；重点看是否区分观测异常与成因，结论是否与 flag/summary 一致。

**Ablation**：skill=`environmental-data-qc`；MCP=`science.profile_table(path,rules)`。预期降低 duplicate policy 和 range 语义错误。

#### EARTH-L2：多时相 dNBR 火烧严重度

- ID：`earth-l2-burn-severity`
- Domain / sub-domain：`earth_science / remote_sensing`
- Level/time：L2，30 分钟
- Anchor：`X`；Related：`D,P,A,V,I,O,G`
- 来源思想：GeoAgentBench/ScienceAgentBench 的 NBR burn-scar workflow；GISAgentBench 的 mask、row-set 和 tolerance-aware grading。
- Inputs：[目录](./inputs/earth-l2-burn-severity/)；像元表与 severity classification，合成，约 12 KB

**Prompt**

> 按 `inputs/classification.json` 对 `burn_pixels.csv` 计算 pre/post NBR、dNBR 和 severity。cloud 任一为 true 的 cell 必须 mask。输出 `output/burn_pixels.csv`，列为 `cell_id,region,dnbr,severity,status`；masked row 的 dnbr/severity 留空，status 为 `masked`，其余为 `valid`。输出 `output/region_summary.csv`，列为 `region,valid_cells,unburned,low,moderate,high,mean_dnbr`；另交 `output/analyze.py` 和 `output/report.md`（≤200 字），比较 north/south，但明确这是合成像元级筛查。

**Hard gates**

- NBR 和 `pre-post` 时间方向正确；
- cloud mask 未进入统计；
- cell/region set 完整唯一，severity threshold 边界正确；
- summary 与逐 cell artifact 一致。

**DeterministicArtifactScore（0–80，Python oracle）**：coverage 5；dNBR 30；severity 15；mask 10；summary 10；脚本 5；报告存在 5。dNBR `atol=1e-6`。

**JudgeScore（0–20）**：按 §4.3；重点看是否正确解释时间方向和 severity，且不把合成 dNBR 当作真实灾情或火因。

**Ablation**：skill=`remote-sensing-index-checklist`；MCP=`earth.compute_index_and_mask(table,formula,mask)`。预期减少 band/时间方向、mask 和阈值错误。

#### EARTH-L3：降雨–径流模型校准与验证

- ID：`earth-l3-rainfall-runoff`
- Domain / sub-domain：`earth_science / hydrology_and_water_cycle`
- Level/time：L3，75 分钟
- Anchor：`R`；Related：`D,P,A,X,V,I,G`
- 来源思想：TB-Science HBV calibration 的 calibration/warm-up/holdout；CORE 风格 local code repair；GeoNature 的错误恢复。
- Inputs：[目录](./inputs/earth-l3-rainfall-runoff/)；catchment 时序、method 与 legacy model，合成，约 24 KB

**Prompt**

> 按 `inputs/method_note.md` 修复或替换 `legacy_bucket_model.py`，校准三参数连续 bucket model。输出 `output/parameters.json`，键为 `capacity_mm,recession_day,et_factor`；输出 `output/daily_simulation.csv`，列为 `date,observed_mm,simulated_mm,period`，period 为 `warmup|calibration|validation`；输出 `output/metrics.json`，含 `calibration_nse,validation_nse,validation_kge`；另交 `output/calibrate.py` 和 `output/report.md`（≤300 字），说明修复、参数、验证性能和局限。验证期不得 reset state。

**Hard gates**

- 参数在 bounds 内，逐日 water balance 按方法说明连续计算；
- warm-up/calibration/validation 切分正确，验证期不重置 storage；
- calibration NSE ≥0.98、validation NSE ≥0.95；
- metrics 与 daily simulation 一致，可重跑脚本存在。

**DeterministicArtifactScore（0–80，Python oracle）**：bounds 5；date/period 10；daily values 15；calibration/validation performance 25；metrics 10；脚本 10；报告存在 5。

**JudgeScore（0–20）**：按 §4.3；重点看是否解释修复的 water-balance bug，区分拟合性能与真实流域适用性，并提及合成/短序列限制。

**Ablation**：skill=`hydrology-calibration-checklist`；MCP=`earth.calibrate_bucket(data,bounds,split)`。预期降低 warm-up、state reset、目标函数和水量平衡错误。

## 7. 贡献指南



### 7.1 贡献目录

新增 task 时：

```text
docs/inputs/<task-id>/              # 只含 agent 可见输入
docs/oracles/<task-id>/oracle.py    # 推荐：独立 Python oracle
docs/manual-graders/<task-id>.md    # 可选：没有 oracle 时的隐藏检查表
```

每题至少提供一种 grader；没有 oracle 时，人工检查表为必需项，也可两者同时提供。两类 grader 均不得复制进 workspace。并在本文加入一张 task card；当前 9 个 samples 均采用一题一个独立 oracle。

### 7.2 输入要求

- 优先合成、公开、可再分发的小数据；写清来源和许可；
- L1 建议 `<5 MB`，L2 `<20 MB`，L3 `<100 MB`；
- 输入需要足够真实，但不要靠下载、GPU 或大数据制造难度；
- decoy/stale/corruption 必须有科研意义，并能由 grader 验证；
- 敏感或真实患者数据不得进入此 UI MVP；
- gold、oracle、hidden mapping、预期数值不能进入 `inputs/`。



### 7.3 Deterministic grader 要求

每题必须选择 Python oracle 或人工 deterministic 检查表，并准备：

1. 一个正确 reference submission，必须得到预期分数并通过 gates；
2. 空输出，必须失败；
3. 一个格式正确但科学错误的输出，必须命中 hard gate；
4. 一个错 ID、漏行或重复行输出；
5. 适用时增加错单位、错方向、NaN/Inf、复制 decoy、未 mask 或 stale output。

使用 Python oracle 时，oracle 和 agent 脚本尽量独立实现，避免同一 bug 同时产生和验证答案；不要直接执行或 import submission 中的未受信代码。使用人工检查表时，hidden expected values、逐项分值、hard-gate 判定、证据位置和 tolerance 必须在提交时写完，且一次评分目标不超过 10 分钟。

Tolerance 要由输入精度或科学方法决定，并写在任务卡及 grader 中；不得在看到 harness 输出后调整。

### 7.4 Review checklist

- [ ] 题目是实际科研 workflow，不是知识问答或普通 CSV 清洗换皮；
- [ ] Prompt 一次粘贴即可执行，不依赖操作员补充解释；
- [ ] `domain/sub_domain` 能准确路由到领域 reviewer；新增 sub-domain 有定义和代表 workflow；
- [ ] 输出 contract 清楚，最多 5–6 个正式 artifact；
- [ ] 2–4 个 hard gates 覆盖最危险的 silent scientific failure；
- [ ] 80 分 deterministic rubric 可由 oracle 或隐藏检查表复核，LLM 不承担科学 gate；
- [ ] Codex 能在时限内开始有效工作，领域同事可稳定完成；
- [ ] skill/MCP 不泄漏答案，MCP 不垄断必要信息；
- [ ] 一位领域 reviewer 与一位 grader reviewer 通过；
- [ ] 许可、输入大小、预计时间和已知局限已记录。



### 7.5 接收基准

一题进入正式评测前必须满足：

- 正确解经所选 grader `3/3` 得到预期结果；
- empty 和 deliberate-wrong controls 经所选 grader `3/3` 失败；
- 两位操作员按 Prompt 独立准备 workspace，不需口头解释；
- 单次 UI run 不超过本级时限的 1.5 倍；
- Codex calibration 不出现明显题意缺失或 grader 假阴性；
- 结果可仅凭冻结 artifact 重评。



## 8. Benchmark 参考

- [ScienceAgentBench](https://github.com/OSU-NLP-Group/ScienceAgentBench)：真实数据 workflow、阶段式 milestone 和 artifact saving。
- [CompBioBench](https://github.com/Genentech/compbiobench-runner)：metadata scrambling、sample reconciliation 和 isolated workspace。
- [BioAgent Bench](https://github.com/bioagent-bench/bioagent-bench)：明确的 CSV/TSV 交付、corrupt/decoy robustness。
- [BixBench](https://github.com/Future-House/BixBench)：capsule-grounded exploration 和数值/范围型问题。
- [MatTools](https://github.com/Grenzlinie/MatTools)：property dictionary，以及 runnable 与 scientific success 的分离。
- [SciAgentGym](https://github.com/CMarsRover/SciAgentGYM)：typed scientific operation 和不同 tool horizon。
- [AutoMat](https://github.com/JHU-CLSP/AutoMat) 与 [CORE-Bench](https://github.com/siegelz/core-bench)：local code/claim reproduction、debug 和 recovery。
- [GeoAgentBench](https://github.com/geox-lab/GABench)：GIS/NBR workflow、关键参数和错误诊断。
- [GeoNatureAgent](https://github.com/gabrielireland/GeoNatureAgent_Benchmark)：threshold、error handling 和 multi-indicator workflow。
- [GISAgentBench](https://arxiv.org/abs/2608.01645)：CRS、NoData、row set 和 tolerance-aware artifact grading。
- [Terminal-Bench-Science](https://github.com/harbor-framework/terminal-bench-science)：科学真实性、output verification 和 negative-control review。

上游只提供设计参考。本样例的 prompt、输入和 grader 为本项目新建；正式发布时仍需逐题记录实际数据许可。
