# 故障排查

## NumPy 源码编译报 GCC 版本不足

这是 pip 未选到兼容二进制包后尝试源码编译的结果。先运行 `getconf GNU_LIBC_VERSION`，不能仅凭 GCC 版本断定操作系统。当前固定 MARADONER 要求 `jax>=0.8`、`jaxlib>=0.8`；已核对 JAXlib 0.8.0 的 CPython 3.11 Linux x86_64 wheel 为 manylinux_2_27。NumPy 2.4.6 的对应 wheel 也要求 glibc 2.27+。

若主机 glibc 低于 2.27，本安装方式不支持，需另选可用的新系统节点或经集群允许的 Apptainer/Singularity 容器。不能只安装新 GCC 或强制降级 JAX 绕过上游依赖。新版 bootstrap 在下载前检查 glibc，并对 MARADONER 的依赖使用 `--only-binary=:all:`，无合适 wheel 时明确失败，不再隐式源码编译。

若 glibc 已满足要求，检查镜像是否缺少 wheel，以及 `pip config debug` 和 PIP_NO_BINARY 等变量。不要在尚未确认原因前重建全部环境。参考：https://pypi.org/project/jaxlib/0.8.0/ 与 https://pypi.org/project/numpy/2.4.6/ 。

若 bootstrap 在 MARADONER 的 GitHub clone 处报 `Empty reply from server`，表示 Git 连接未收到有效响应，不能仅凭此判断具体代理或防火墙原因。更新 `scripts/bootstrap.sh` 和 `scripts/fetch_maradoner.py` 后直接重跑安装。新版使用官方 codeload 固定提交 ZIP、重试并记录源码哈希；既有环境继续复用，无需删除 `.runtime/`。

若服务器也无法访问 codeload，可在能联网的机器下载 `https://codeload.github.com/autosome-ru/MARADONER/zip/d01f9140bfee69d91e8e1fd3eac1e923e308d9a5`，上传 ZIP 后执行：

```bash
MARADONER_ARCHIVE=/absolute/path/MARADONER-source.zip bash scripts/bootstrap.sh
```

scE2G 仍需要完整 Git 子模块；不能用普通源码 ZIP 冒充完整安装。网络仍受限时保留新的错误日志，另行准备包含子模块的固定版本源码。

| 现象 | 处理 |
|---|---|
| 缺 prepared 文件 | 按安装文档审核、导出标准输入；dry-run 只列缺口，不生成假数据 |
| Conda 下载或求解失败 | 检查网络、磁盘及 channels；保留日志，重新运行 bootstrap。已有环境不自动更新；调整版本需另建项目副本并记录解析结果 |
| 真实软件 import/版本错误 | 查看 results/environment 和 bridge.log；不把生产 backend 改为 synthetic_ridge |
| scE2G 运行失败 | 查看 sce2g.log、其 `.snakemake/log` 与阶段日志；确认上游资源可下载、参考一致、内存足够。该接口固定提交，不承诺任意新版本兼容 |
| FIMO 位点表异常 | 检查 scan/fimo.log 和独立 fimo.tsv；检查 FASTA 染色体命名、motif MEME 格式、区间长度 |
| 跨参考/重复/未知 ID | 修正源映射，记录转换，不通过删除检查绕过 |
| 无可评价 TF | 检查 retained motifs、TF ID、单扰动、同 donor/batch NTC；缺对照不能跨条件凑配对 |
| 留一 receipt 不匹配 | 从排除该 donor 的 fragments 重新运行链接，samples 中相应 build 行也不纳入 |
| 内存不足 | 限定细胞类型、分条件、先小数据；模型含稠密矩阵，不能因上游稀疏就假定任意规模可跑 |
| .run.lock 已存在 | 先检查文件内 PID 是否仍工作；只有确认进程终止后才能手工移除此文件并重跑 |
| 中途失败后旧报告缺失 | 有意失效，避免把旧成功当本次成功；修正后同命令续跑 |
| .previous/.running 占空间 | 这些是旧阶段/失败审计产物；确认无需追溯后仅清理对应运行目录，勿递归删除项目根目录 |

数值复现：同平台、相同环境/线程和输入可用 `numpy.testing.assert_allclose` 比较活动矩阵（建议 rtol=1e-6、atol=1e-8）；跨 BLAS/JAX/平台需要单独声明容差。边界近似并列的排名可能变化，应检查原差值，不承诺位级跨平台一致。

没有服务器 SSH 信息时，本地交付不会被描述为已经部署。服务器验收顺序：安装 → 合成单测 → 真实工具小测 → 匹配数据有限试跑 → 完整科学评价。
