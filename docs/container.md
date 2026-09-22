# Apptainer / Singularity 容器部署

此入口面向旧 glibc 的 Linux x86_64 集群。宿主机只负责调用已经安装的 Apptainer 或 Singularity；项目工具在固定摘要的 Debian Bookworm / Python 3.11 官方基础镜像内安装和执行。无需 Docker daemon 或用户 root，也不要求在集群上执行 apt-get。集群仍必须允许容器运行；容器共享宿主机内核，不保证能绕过所有内核或管理员策略限制。

## 服务器步骤

将新增 `container/`、`scripts/container.sh` 及更新的 `scripts/bootstrap.sh`、`scripts/fetch_maradoner.py` 上传到现有项目对应位置。先检查运行时：

```bash
command -v apptainer || command -v singularity
# 若无输出，查看模块并加载集群实际提供的名称：
module avail
# 例如：module load apptainer（仅当集群提供该名称）
```

在项目根目录执行：

```bash
bash scripts/container.sh pull
bash scripts/container.sh bootstrap
bash scripts/container.sh smoke
bash scripts/container.sh exec bash scripts/check_environment.sh --network
bash scripts/container.sh run --config config/project.yaml --cores 8 --dry-run
# 审核并准备真实输入后：
bash scripts/container.sh run --config config/project.yaml --cores 8
```

`pull` 会拉取固定 amd64 摘要，记录 SIF SHA256，并验证容器启动、基础工具和项目目录写权限。它不表示全部生物信息软件已安装。`bootstrap` 才在容器中建立五个隔离环境。`smoke --with-sce2g` 额外运行 scE2G 官方小例子。

容器内默认不读取宿主用户的 pip/Conda 配置，使用官方 PyPI。需要清华镜像时显式传入：

```bash
ME_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple bash scripts/container.sh bootstrap
```

## 持久化与已有下载

| 宿主路径 | 用途 |
|---|---|
| .container/images | 基础 SIF、SHA256、源镜像 URI |
| .container/runtime | 容器专用 Micromamba 环境，容器内绑定为项目 .runtime |
| .container/cache、tmp、home | 镜像缓存、转换临时文件和隔离用户目录 |
| .tools | 复用已有 MARADONER、scE2G 及子模块源码 |
| data、results、tmp | 原项目中的持久化数据、结果和分析临时文件 |

旧宿主 `.runtime` 不删除、不用于容器安装；容器内以子目录绑定将它遮盖。不要在宿主直接执行 `.container/runtime` 中的程序。所有后续安装、smoke 和分析均使用 `container.sh`。环境路径固定在当前项目的真实绝对路径；安装完成后不要移动项目目录。通过 `/home` 软链接进入时，脚本会用 `pwd -P` 统一为实际物理目录。

已有源码复用；环境需要在容器中重建，这是有意隔离宿主 ABI。运行结果仍存原项目目录，退出容器不会丢失。基础镜像是只读的，环境写入绑定的用户目录。

外部数据目录需要显式绑定，并在配置中使用容器可见路径：

```bash
ME_CONTAINER_BIND=/PUBLIC/data:/PUBLIC/data bash scripts/container.sh run --config config/project.yaml --cores 8
```

同一个分析的预检与运行应使用相同绑定。普通项目内路径不需要额外设置。集群上的计算需在获配资源的计算节点或作业脚本中执行；`--cores` 不是调度器资源申请。

## 拉取失败或没有容器运行时

若没有 Apptainer/Singularity，需要先加载集群模块或请管理员提供受支持运行时；这些脚本不会安装系统运行时。若 Docker Hub 不通，可在另一台 Linux x86_64 机器运行同一 `container.sh pull`，将 `.container/images/` 中的 SIF、SHA256 和 source_uri.txt 一并上传，然后执行 `container.sh check`。不要用不同镜像替换而保留旧校验和。

本次本地验证覆盖 shell 语法与模拟运行时的参数、目录绑定及命令转发；当前 Windows 开发机未实际启动 SIF。真正的服务器验收以 `pull/check`、`bootstrap`、`smoke` 输出为准，不宣称容器已在目标集群运行成功。

参考：[Apptainer OCI 镜像](https://apptainer.org/docs/user/latest/docker_and_oci.html)、[目录绑定](https://apptainer.org/docs/user/latest/bind_paths_and_mounts.html)、[官方 Python Bookworm 镜像定义](https://github.com/docker-library/python/blob/master/3.11/bookworm/Dockerfile)。
