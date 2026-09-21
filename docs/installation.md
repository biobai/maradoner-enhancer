# Linux 安装与数据准备

## 环境

支持目标：联网 Linux x86_64、bash、curl、tar、git；用户可写项目目录。使用 CPU，不要求 root。先用 `df -h .`、`free -h` 检查空间内存。`bootstrap.sh` 在 `.runtime/` 创建 Micromamba 与 core、maradoner、r、scan、sce2g 五环境，固定两个源码提交；不会改系统 Python 或全局 Conda 配置。初始化可能较慢，scE2G 首次运行另解析其上游阶段环境并下载资源。

```bash
bash scripts/bootstrap.sh
bash scripts/check_environment.sh --network
bash scripts/run_smoke_test.sh --real-tools
.runtime/envs/core/bin/python scripts/real_tool_smoke.py --with-sce2g
```

各命令失败应先处理再继续。本部署版 smoke 仅做服务器真实工具验收，不包含开发机单元测试。scE2G 小测使用上游 chr22 示例，是软件验收，不验证科学改善。安装结果位于 `results/environment/`。预检提示缺少 prepared 输入是预期状态；完成准备后须确认缺口消失。默认参数只是初始预算，先以限定区域/TF/细胞类型试运行。

## 公开数据与审核

`config/downloads.tsv` 当前只含小型公开元数据。下载器支持 Range 续传、重试、提供校验和时验证并记录实际 SHA256；未提供参考校验和不能声称已与发布者核对。

```bash
.runtime/envs/core/bin/python -m me.cli download config/downloads.tsv data/metadata
```

大对象须在确定匹配背景后，将真实 URL、相对目标名和公开 SHA256（若有）添加到独立下载清单。不要下载全部 Perturb-seq 作为默认动作。记录作者 QC 来源和排除理由，优先作者原始 pseudobulk。预处理不能凭细胞名称猜供体/NTC。

## RNA

RDS 要求 Seurat 原始 counts；模板 `config/rds_metadata_mapping.example.json` 的值必须替换为真实元数据列名，role/target/included 需经审核标准化。分层 counts 需明确合并后才允许导出。

```bash
.runtime/envs/r/bin/Rscript scripts/export_rds.R data/raw/rna.rds RNA data/rna_export config/rds_metadata_mapping.example.json
.runtime/envs/core/bin/python -m me.cli aggregate-mtx --matrix data/rna_export/matrix.mtx --genes data/rna_export/genes.txt --cells data/rna_export/cells.txt --metadata data/rna_export/cells.tsv --output data/prepared --reference GRCh38_GENCODEv43
```

H5AD 需 X 是原始整数 counts，obs 已有标准字段：

```bash
.runtime/envs/core/bin/python -m me.cli aggregate-h5ad --input data/raw/rna.h5ad --output data/prepared --reference GRCh38_GENCODEv43
```

将 rna_samples.tsv 与经审核的建网 ATAC 样本行合并为 samples.tsv。ATAC role=build、target=NTC；RNA role=control/perturb，单 TF target 使用与基因表一致的 ID。不要仅因同 donor 而写成同细胞 multiome。基因符号/Ensembl/版本后缀必须先按固定注释显式映射并留转换表；不得静默去重。按预定注释和可用 RNA 交集准备 genes.tsv，不按扰动效果挑基因。

## ATAC、区域与链接

准备 `build_cells.tsv`（数据字典），条形码必须与相应 fragments 库一致。示例为一个库；多库条形码重名必须先添加可追溯命名空间，再合并对应 fragments，不能直接拼表。先建网得到 scE2G 的实际候选峰，审核峰和注释后扫描同一峰宇宙。

```bash
export PATH="$PWD/.runtime/envs/scan/bin:$PATH"
.runtime/envs/core/bin/python -m me.cli fragments --input data/raw/fragments.tsv.gz --membership data/prepared/build_cells.tsv --output data/prepared/build.fragments.tsv.gz
.runtime/envs/core/bin/python -m me.cli sce2g --repository .tools/scE2G --fragments data/prepared/build.fragments.tsv.gz --output data/sce2g --snakemake .runtime/envs/sce2g/bin/snakemake --cores 8 --memory-mb 32000
```

读取该固定版本实际输出列名与候选区，整理有表头的 `peaks.tsv`（region_id 必须 `chrom:start-end`）。用相同参考 GTF、FASTA 和冻结的 MEME motif：

```bash
.runtime/envs/core/bin/python -m me.cli regions --gtf data/reference/genes.gtf.gz --peaks data/prepared/peaks.tsv --reference GRCh38_GENCODEv43 --output data/annotation
.runtime/envs/core/bin/python -m me.cli scan --regions data/annotation/regions.tsv --fasta data/reference/genome.fa --motifs data/reference/motifs.meme --fimo .runtime/envs/scan/bin/fimo --output data/scan
.runtime/envs/core/bin/python -m me.cli import-links --predictions data/sce2g/results/build/scATAC_powerlaw_v3/scE2G_predictions.tsv.gz --columns config/link_columns.example.json --regions data/annotation/regions.tsv --genes data/annotation/genes.tsv --provenance data/sce2g/provenance.json --output data/prepared/enhancer_links.parquet --reference GRCh38_GENCODEv43
```

`link_columns.example.json` 只是显式映射模板，必须根据真实列名修改；它不是声称已验证的 scE2G 列接口。确认 scE2G 参考、TSS、cis 窗口和本项目一致；否则停止并统一参考。将 project.yaml 的 genes/regions/sites 指向上述文件。准备 tf_motif_family.tsv 与对应资源引用，固定后才查看评价结果。

## 执行与复现

```bash
bash scripts/run_pipeline.sh --config config/project.yaml --cores 8 --dry-run
bash scripts/run_pipeline.sh --config config/project.yaml --cores 8 --until features
bash scripts/run_pipeline.sh --config config/project.yaml --cores 8
```

同命令重跑会校验内容指纹并复用成功阶段；`--force` 强制重跑。当前模型串行拟合以限制内存；cores 是资源预算，不承诺全部核心满载。阶段内部失败从该阶段重启，不宣称恢复优化器迭代。也可用 core 环境 Snakemake 运行 `workflow/Snakefile`，修改环境/外部源码后用 `--forcerun report` 触发指纹复核；直接脚本入口每次都会检查。

每个条件/细胞类型/留一折使用不同配置、输出路径。复制整个项目代码到服务器后重新安装环境，不复制 Windows 虚拟环境。最终报告位于所配 output/report，HTML 与 SVG 可离线查看。
