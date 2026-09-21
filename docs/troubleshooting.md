# 故障排查

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
