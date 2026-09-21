# 输入输出契约

所有 TSV 有表头、UTF-8；Parquet 保留类型。ID 区分大小写，缺失 donor/ID 不接受。坐标 0-based、左闭右开，TSS 是单碱基坐标。源数据角色、参考、版本和 QC 依据必须保存在输入目录及下载清单中。

## 标准输入

| 文件 | 必需字段/含义 |
|---|---|
| samples.tsv | sample_id 唯一；donor 生物供体或明确记录的独立培养单位；batch 真实批次；condition；cell_type；modality=RNA/ATAC/multiome；role=build/control/perturb；target=NTC 或单 TF gene_id；reference；included=0/1 |
| counts.tsv | 第一列 gene_id 唯一，之后恰为所有纳入 RNA control/perturb sample_id；值为非负整数。可保留比建模基因更多的基因用于库大小 |
| genes.tsv | gene_id、chrom、tss、reference；注释导出另有 transcript_id、strand |
| regions.tsv | region_id、chrom、start、end、kind=promoter/enhancer、gene_id（增强子为 `-`）、reference、parent_region_id。增强子必须扣除全部启动子且互不重叠 |
| motif_sites.parquet | site_id 唯一；region_id、motif_id、chrom、start、end、strand、score、source。score 为扫描原始分数，不是边置信度 |
| enhancer_links.parquet | region_id、gene_id 联合唯一；weight 非负；source 原始预测路径；build_group |
| enhancer_links.parquet.provenance.json | build_sample_ids、reference、links_sha256、source_files；真实构建另有 fragments/membership SHA、donors、heldout_donor、软件提交和列映射 |
| tf_motif_family.tsv | tf_id、motif_id、family_id 联合唯一；允许同 motif 多 TF/家族，需固定映射资源与版本 |
| cells.tsv（RNA） | cell_id、donor、batch、condition、cell_type、role、target、included；MTX 为 gene×cell，genes.txt/cells.txt 每行一个 ID |
| build_cells.tsv（ATAC） | cell_id、sample_id、donor、role、target、included；仅 build/NTC 纳入 fragments；样本 ID 对应 samples.tsv |
| peaks.tsv | region_id=`chrom:start-end`、chrom、start、end，来自实际 scE2G 同一候选峰集 |

下载清单字段请以 `config/downloads.tsv` 为准；空 expected SHA 只记录实际值，不提供发布者完整性背书。不能手写虚假来源 receipt 绕过验证。

## report/ 稳定输出

| 文件 | 字段与解释 |
|---|---|
| samples.tsv / enhancer_links.parquet / motif_sites.parquet | 审核输入的副本；原始证据路径保留 |
| activities.parquet | model、target_context（该次删除的 TF）、sample_id、motif_id、activity、posterior_sd、uncertainty_scope。样本 SD 上游不提供则空；不同 target_context 不直接混合 |
| group_contrasts.tsv | motif_id、delta、z、model、target、scope；真实软件组级比较，不能当供体统计 |
| benchmark_metrics.tsv | model、target、donor、unit、condition、aggregation=max/mean_rank、rank、mrr、top5、n_families、target_families、n_acceptable_families |
| paired_differences.tsv | 各模型相对 promoter 的 MRR 差、重采样区间、家族/供体数及解释状态。按实际表头读取，不把区间越零自动转换成科学结论 |
| condition_summary.tsv | model、condition、mrr、top5；家族和供体等权后的结果 |
| null_calibration.tsv | NTC_effect 与 ranking_null 分行，缺 NTC 重复时 status 标明不足 |
| exclusions.tsv | target、reason；与 feature_audit.tsv 一起审核可评价覆盖率 |
| candidate_edges.parquet | 原始 site 字段、region 字段、gene_id、candidate_tfs（分号集合）、link_weight、link_source、motif_source_sha256、link_source_sha256、evidence_type、causal_label=unassigned |
| feature_audit.tsv / scaling.json | 保留/排除 motif 与共同缩放、范数匹配系数；常量特征不能强行加入 |
| expression_metrics.tsv | 主流程内部严格 FOV 被禁用及原因；不填伪数值 |
| scientific_status.json | 合成诊断或已完成待解释的扰动评价；不自动声称改善 |
| report.html / family_mrr.svg | 可离线查看的表和描述性图 |

`candidate_edges` 保存序列与链接候选全集，可能含未进入最终拟合的 motif；必须与 feature_audit 按 motif_id 连接筛选。不能用 activity Z 替换边置信度。

根目录 run_manifest.json 含最终时间、配置、输入哈希、代码/环境指纹与阶段状态；report 中副本记录报告生成时状态。外部模型目录保存 request、实际 argv、退出码和 stderr；完整审计请保留整个运行 output，而非仅 HTML。
