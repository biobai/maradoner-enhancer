# MARADONER Enhancer Integration: Server Distribution

Upload this directory to an internet-connected Linux x86_64 server. Root access is not required. It contains production code, configuration, environment specifications, workflows, and operational documentation. Local virtual environments, research datasets, generated results, unit tests, and development validation records are excluded.

## Installation and execution

For older cluster hosts, use the Apptainer/Singularity entry point (see the [container deployment guide](docs/container.md), in Chinese):

```bash
bash scripts/container.sh pull
bash scripts/container.sh bootstrap
bash scripts/container.sh smoke
bash scripts/container.sh run --config config/project.yaml --cores 8 --dry-run
```

This uses a pinned official Bookworm base image and persistent project-local environments. It requires an available cluster container runtime, but no Docker daemon or root access. Existing source downloads are reused; container environments are isolated from the host environments. Use the container wrapper for all subsequent analysis on an older host.

The current pip-based MARADONER installation requires Linux x86_64 with glibc >= 2.27 because its JAX dependency uses newer Linux wheels. Check with `getconf GNU_LIBC_VERSION`. Older hosts need a suitable newer node or an approved container; upgrading GCC alone is insufficient. Bootstrap checks this before downloading environments and requires binary dependency wheels.

From this directory on the server, run:

```bash
bash scripts/bootstrap.sh
bash scripts/check_environment.sh --network
bash scripts/run_smoke_test.sh
bash scripts/run_pipeline.sh --config config/project.yaml --cores 8 --dry-run
# After preparing the documented inputs and updating the configuration:
bash scripts/run_pipeline.sh --config config/project.yaml --cores 8
```

In this distribution, `run_smoke_test.sh` checks the actual MARADONER, FIMO, and R installations without running the development unit tests. It generates small synthetic inputs; success establishes software operation, not scientific validity. Add `--with-sce2g` to check the official small scE2G example:

```bash
bash scripts/run_smoke_test.sh --with-sce2g
```

Production inputs still require review and preparation. The project does not infer donor, non-targeting control (NTC), transcription factor (TF), or cell-type labels from undocumented conventions. `config/downloads.tsv` lists small public metadata resources only. Read the [installation and data preparation guide](docs/installation.md) before editing `config/project.yaml`. Resource budgets are initial examples, not measured requirements.

## Directory layout

If GitHub Git connections fail, bootstrap retrieves MARADONER from the official pinned-commit archive on `codeload.github.com`, with retries and recorded source hashes. Existing verified source is reused. If that host is also inaccessible, download the pinned ZIP on another machine and run `MARADONER_ARCHIVE=/absolute/path/source.zip bash scripts/bootstrap.sh`. scE2G still requires its Git repository and submodules; a plain ZIP is insufficient.

| Directory | Purpose |
|---|---|
| src/me | Input adapters, matrices, software interfaces, evaluation, and evidence networks |
| scripts | Installation, preflight checks, server acceptance, execution, and donor-exclusion robustness |
| config | Production parameters, candidate datasets, and explicit field-mapping templates |
| envs | Isolated environments and version constraints |
| workflow | Snakemake stage scheduling |
| docs | Scientific design, data contracts, installation, and troubleshooting |

Execution creates `.runtime/`, `.tools/`, `data/`, `results/`, and `tmp/` within the project. Installation does not change system Python or global Conda configuration. Reports are written to the configured output/report directory; failure logs and the complete run manifest remain under output.

Development validation passed 23 tests and a four-arm run using actual MARADONER on synthetic data. Fresh Linux installation, actual scE2G/FIMO/R execution, and biological data evaluation still require server-side validation. A positive scientific result is not an acceptance requirement.

Further documentation, currently in Chinese: [scientific design](docs/design.md), [data dictionary](docs/data_dictionary.md), and [troubleshooting](docs/troubleshooting.md). External software is installed at pinned commits and remains subject to its respective licenses.
