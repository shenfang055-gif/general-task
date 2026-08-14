# UI task sample inputs

本目录保存 `../ai4s-ui-taskbook-v0.1.md` 中 9 个 task sample 的轻量输入。

| Task ID | Sub-domain | Task card |
|---|---|---|
| `life-l1-cell-annotation` | `single_cell_and_spatial` | [LIFE-L1](../ai4s-ui-taskbook-v0.1.md#life-l1蛋白-marker-cluster-注释) |
| `life-l2-paired-expression` | `transcriptomics` | [LIFE-L2](../ai4s-ui-taskbook-v0.1.md#life-l2配对样本表达响应) |
| `life-l3-variant-prioritization` | `genomics_and_genetics` | [LIFE-L3](../ai4s-ui-taskbook-v0.1.md#life-l3trio-变异优先级流程修复) |
| `materials-l1-cif-audit` | `crystallography_and_structure` | [MAT-L1](../ai4s-ui-taskbook-v0.1.md#mat-l1cif-入库质检) |
| `materials-l2-xrd-phase-mixture` | `characterization_and_spectroscopy` | [MAT-L2](../ai4s-ui-taskbook-v0.1.md#mat-l2xrd-两相混合物识别) |
| `materials-l3-eos-transition` | `phase_stability_and_thermodynamics` | [MAT-L3](../ai4s-ui-taskbook-v0.1.md#mat-l3eos-与压力诱导相变复现) |
| `earth-l1-station-qc` | `environmental_monitoring` | [EARTH-L1](../ai4s-ui-taskbook-v0.1.md#earth-l1环境站数据-qc) |
| `earth-l2-burn-severity` | `remote_sensing` | [EARTH-L2](../ai4s-ui-taskbook-v0.1.md#earth-l2多时相-dnbr-火烧严重度) |
| `earth-l3-rainfall-runoff` | `hydrology_and_water_cycle` | [EARTH-L3](../ai4s-ui-taskbook-v0.1.md#earth-l3降雨径流模型校准与验证) |

使用方式：把某个 task 目录的内容复制到一次性 workspace 的 `inputs/`，在 workspace 根目录创建空的 `output/`，然后把文档中的 task prompt 原样交给桌面客户端。

这些文件均为本项目新建的合成样例，仅用于说明出题和评分方式，不复制上游 benchmark 数据。正式评测发布前仍需：领域复核、Python oracle 或人工 deterministic 检查表、错误答案测试、许可记录和至少一次 Codex calibration。

```text
workspace/
├── inputs/     # 本目录中某一道题的内容，只读
└── output/     # harness 生成
```

不要把 oracle、gold answer 或 judge rubric 复制到 workspace。
