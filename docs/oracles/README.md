# 逐题 Oracle

每道 UI task 使用独立目录：

```text
oracles/<task-id>/oracle.py
```

统一调用方式：

```bash
python3 docs/oracles/<task-id>/oracle.py \
  --workspace /path/to/workspace \
  --out /path/to/evaluation.json
```

`--out` 可省略；JSON 始终写到 stdout。统一结果至少包含：

- `task_id`
- `grader_status`
- `hardgate_pass`
- `deterministic_score`（0–80）
- `criteria`（逐项得分与证据）
- `failure_codes`

Oracle 从 `<workspace>/inputs` 独立重算真值，只检查冻结后的 `<workspace>/output`。不得读取聊天记录或调用网络，也不得 `import` harness 生成的代码。若需验证重跑脚本，应在隔离的 workspace 副本中执行。

缺失或错误的 submission 是正常评分结果：`grader_status=ok`、`hardgate_pass=false`，并给出 0 分或 partial score。只有 workspace/input fixture 损坏或 oracle 自身异常才使用 `grader_status=error`。

新增 oracle 至少要验证正确 reference submission、空输出，以及一个格式正确但触发科学 hard gate 的 deliberate-wrong submission。
