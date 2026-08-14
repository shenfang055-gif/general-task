# AI4S 桌面 UI 评测题集

面向生命科学、物质科学和地球科学的桌面端 scientific harness 评测样例。操作员通过本地 UI 提交一次固定 Prompt，harness 从 workspace 的 `inputs/` 读取数据并将正式结果写入 `output/`；评分只依赖冻结后的 artifacts。

Codex 暂作为 baseline。当前版本包含三个领域各 L1–L3 一题，共 9 个 task samples。

## 仓库内容

```text
docs/
├── ai4s-ui-taskbook-v0.1.md     # 任务卡、SOP、评分与贡献指南
├── inputs/<task-id>/            # 复制到 UI workspace 的只读输入
└── oracles/<task-id>/oracle.py  # 每题独立 deterministic grader
```

完整设计见 [AI4S 桌面 UI 评测题集与贡献指南](docs/ai4s-ui-taskbook-v0.1.md)，输入索引见 [docs/inputs/README.md](docs/inputs/README.md)。

## 快速运行

1. 新建一次性 workspace，将一道题的输入复制到 `workspace/inputs/`，并创建空的 `workspace/output/`。
2. 在桌面客户端打开 workspace，将任务卡中的 Prompt 原样粘贴一次。
3. 结束后冻结 workspace，运行对应 oracle：

```bash
python3 docs/oracles/life-l2-paired-expression/oracle.py \
  --workspace /path/to/workspace
```

Oracle 输出 `0–80` 的 `deterministic_score`、逐项 `criteria`、`hardgate_pass` 和 `failure_codes`。再按 taskbook 的统一规则对报告与图表给 `0–20` 的 blind JudgeScore。

## 贡献题目

- 新增一张包含 `domain/sub_domain`、Prompt、deliverables、hard gates 和 rubric 的任务卡；
- 将可再分发输入放入 `docs/inputs/<task-id>/`；
- 推荐提供 `docs/oracles/<task-id>/oracle.py`；不提供 Python oracle 时，必须提供可复核的隐藏人工 deterministic 检查表；
- 用正确解、空输出和至少一个格式正确但科学错误的输出验证 grader。

详细接收标准与消融实验规则以 taskbook 为准。
