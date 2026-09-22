# Podman 构建全部软件 → SIF 集群运行

## 架构

最终只部署 **1 个完整软件镜像**。基础层固定 Debian Bookworm / Python 3.11 镜像摘要，上层在 Podman build 中安装全部阶段依赖。多阶段 Containerfile 中的 base 是构建层，不是额外部署的运行容器。

| 镜像内环境 | 职责与隔离原因 |
|---|---|
| core | 数据整理、矩阵、统计、报告与项目 Python 包 |
| maradoner | MARADONER、JAX、NumPy ≥2.1，独立于旧 scE2G 科学计算栈 |
| r | Seurat、Signac、Matrix、JSON 接口 |
| scan | MEME/FIMO、bedtools、htslib |
| sce2g | 固定 Snakemake 7.32.4 与 Mamba 调度环境，隔离 core 的 Snakemake 8 |
| upstream stage environments（3 个） | ABC、ENCODE-rE2G、scE2G，遵循固定上游 YAML，另限制 NumPy <2 避免 sklearn 1.2.1 ABI 冲突 |

环境数量不等于容器数量；这些都封装在同一镜像中。依赖冲突用镜像内前缀隔离，当前没有必须拆分运行镜像的系统级冲突。环境安装求解或检查失败会让镜像构建失败，不能因此声称依赖已经兼容。

## 构建机

Linux amd64 上安装并配置 Podman，预留足够磁盘、内存和网络后，在项目根目录运行：

```bash
bash scripts/build_podman.sh
```

构建过程：基础工具检查 → 五套环境 → 固定 MARADONER/scE2G 及子模块 → 三套上游阶段环境 → 安装项目包 → 导入与版本检查 → 真实 MARADONER/FIMO/R 小型测试。每套环境的实际解析清单、pip freeze 和子模块提交保存在镜像 `/opt/maradoner-enhancer/build-evidence` 或 `/opt/me-stage-envs`。构建不是只生成空基础镜像。

首次构建包含较多 Python/R 和生物信息依赖，耗时和磁盘开销较大；Podman 层缓存可复用成功阶段。研究数据、本地环境、结果、Git 历史被 `.containerignore` 排除。此前服务器上的源码下载不再是运行依赖；构建机自行获取固定源码。

导出产物为 `.container/images/maradoner-enhancer-software.tar`、SHA256、Podman 镜像 ID、inspect 元数据与版本记录。此 tar 使用 docker-archive 格式，但构建和导出均由 Podman 完成，不需 Docker daemon。

## 集群运行

上传项目配置与数据，以及 `.container/images/` 后，在有 Apptainer/Singularity 的 Linux x86_64 节点执行：

```bash
bash scripts/container.sh convert
bash scripts/container.sh check
bash scripts/container.sh smoke
bash scripts/container.sh exec bash /opt/maradoner-enhancer/scripts/check_environment.sh --network
bash scripts/container.sh run --config config/project.yaml --cores 8 --dry-run
# 准备真实输入后：
bash scripts/container.sh run --config config/project.yaml --cores 8
```

**没有 bootstrap 步骤。** `container.sh bootstrap` 和 `scripts/bootstrap.sh` 均明确拒绝运行时安装。镜像内软件位于只读 `/opt/maradoner-enhancer`；不绑定/使用宿主 `.runtime`、`.tools`、旧 `.container/runtime`。修改软件依赖需要重新 Podman build 和转换新镜像。

`convert` 只读取 Podman 归档转换 SIF、记录来源与校验和，不安装分析软件。同名旧 SIF 来自另一 tar 时会报错，需先保留并移走旧 SIF 及其记录，防止误复用。可在另一台有运行时的 Linux 机器完成转换，再上传 SIF 和来源/校验记录。

## scE2G 的预装环境

构建脚本依据固定 Snakemake 7.32.4 的真实 Env.hash 接口验证并预建缓存，固定缓存前缀为 `/opt/me-stage-envs`。运行前核对三个上游 YAML、post-deploy 脚本和预装环境；缺失或变化直接报错并要求重建。Snakemake 只复用已经存在的环境，运行时 Conda 离线，pip 禁止访问索引。

scE2G 上游会在工作流目录下写临时文件并下载参考资源，因此运行时将其工作流文件复制到输出目录的 upstream_workflow。复制工作流与下载参考数据不是安装软件；Python/R 包和可执行程序仍来自镜像。该副本可能较大，首次运行需要额外空间。完整 scE2G 工具/参考数据小测用 `container.sh smoke --with-sce2g`；镜像构建默认不下载完整研究参考资源来执行整条科学流程。

## 数据和作业

项目路径绑定为相同物理绝对路径。配置、数据、结果、临时文件可写；退出容器后保留。额外数据挂载示例：

```bash
ME_CONTAINER_BIND=/PUBLIC/data:/PUBLIC/data bash scripts/container.sh run --config config/project.yaml --cores 8
```

容器共享宿主内核，需要集群支持运行时。计算在获配资源的节点执行，cores 不代替调度器申请。缺少 Apptainer/Singularity 时先加载集群模块；脚本不安装系统服务。

## 验证边界

开发机可做语法、单元测试和模拟 Podman/Apptainer 参数验证；没有可用 Podman 时不声称镜像已成功构建。构建中的实际环境求解、导入和小测为交付到服务器前必须通过的门槛。真实生物数据的匹配审核、有限试跑和科学评价另行完成。

参考：[Podman save](https://docs.podman.io/en/latest/markdown/podman-save.1.html)、[Apptainer 归档转换](https://apptainer.org/docs/user/latest/appendix.html)、[上游 scE2G 三环境定义](https://github.com/EngreitzLab/scE2G/blob/7cb2af750fb96006f5d2b7c5475dcff30ea0e6c9/workflow/envs/sce2g_container.def)。
