# MARADONER Enhancer Integration

A research workflow for testing whether enhancer links improve motif-family perturbation identification and for exporting regulatory candidates with traceable evidence.

## Container architecture

**Podman builds all software before deployment. Runtime installation is disabled.**

One final runtime image contains the complete project. A pinned Debian Bookworm base supports separate internal environments for core Python, MARADONER, R/Seurat/Signac, motif scanning, and the scE2G scheduler. The three upstream scE2G/ENCODE-rE2G/ABC environments are also prebuilt. Conflicting dependency versions are isolated inside this single image rather than split across multiple runtime containers.

The Containerfile has base and software stages. The server runs the completed image; it does not use `bootstrap` to install software. Environment changes require rebuilding the image.

## Build and deploy

On a Linux amd64 build machine with Podman and sufficient memory/disk:

```bash
bash scripts/build_podman.sh
```

Transfer the project configuration, inputs, and generated `.container/images/` directory to the cluster. Then run:

```bash
bash scripts/container.sh convert
bash scripts/container.sh check
bash scripts/container.sh smoke
bash scripts/container.sh run --config config/project.yaml --cores 8 --dry-run
# After preparing and reviewing real inputs:
bash scripts/container.sh run --config config/project.yaml --cores 8
```

Podman exports a Docker-compatible archive without requiring Docker. Apptainer/Singularity converts that archive to SIF and runs it on the cluster. Direct registry pulls and runtime bootstrap are disabled.

Software resides under `/opt/maradoner-enhancer` in the image. Only configuration, data, results, logs, workflow working files, and temporary files are writable in the bound project directory. Host `.runtime`, `.tools`, and the old `.container/runtime` are not used for software execution.

The build must pass dependency checks and a real MARADONER/FIMO/R smoke test before producing the final image. Image-level acceptance has not yet been executed on the current Windows development machine. Scientific evaluation on matched biological data remains separate from software acceptance.

## Inputs and outputs

Production inputs require explicit review of donor, batch, condition, cell type, controls, TF labels, raw counts, and genome/motif references. `config/downloads.tsv` lists metadata resources, not complete research datasets. Resource settings in `config/project.yaml` are initial budgets, not measured requirements.

Four arms compare promoters, scE2G enhancer links, distance links, and distance-stratified permutations using a common feature universe. Family MRR is the primary metric. Candidate network edges retain sequence/link evidence without automatic causal or activation/repression labels.

Reports are written to the configured output/report directory. Complete run manifests, software logs, and failed attempts are retained for audit. A successful run does not automatically establish improved inference.

Detailed documentation is currently in Chinese: [container deployment](docs/container.md), [installation and data preparation](docs/installation.md), [scientific design](docs/design.md), [data dictionary](docs/data_dictionary.md), and [troubleshooting](docs/troubleshooting.md).
