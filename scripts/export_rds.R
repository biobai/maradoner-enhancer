#!/usr/bin/env Rscript
# Explicit extraction contract: no slot guessing, no dense cell matrix conversion.
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 4) stop("Usage: export_rds.R input.rds assay output_dir metadata_mapping.json")
suppressPackageStartupMessages(library(SeuratObject))
suppressPackageStartupMessages(library(Matrix))
suppressPackageStartupMessages(library(jsonlite))
x <- readRDS(args[1])
assay <- args[2]
out <- args[3]
map <- fromJSON(args[4])
if (!inherits(x, "Seurat")) stop("Expected Seurat object; convert other objects explicitly")
if (!(assay %in% Assays(x))) stop("Requested assay missing")
# A split Assay5 layer must be explicitly joined by the data preparation author.
layers <- Layers(x[[assay]], search="^counts")
if (length(layers) != 1 || layers[1] != "counts") stop("Expected one counts layer; explicitly join split count layers before export")
counts <- LayerData(x, assay=assay, layer="counts")
if (!inherits(counts, "sparseMatrix")) stop("counts must be sparse")
if (any(!is.finite(counts@x)) || any(counts@x < 0) || any(counts@x != round(counts@x))) stop("Non-integer raw counts")
meta <- x[[]][colnames(counts), , drop=FALSE]
required <- c("donor","batch","condition","cell_type","role","target","included")
if (!all(required %in% names(map))) stop("Mapping JSON must specify all metadata fields")
if (!all(unlist(map[required]) %in% colnames(meta))) stop("Metadata columns absent; do not invent donor/NTC labels")
md <- data.frame(cell_id=rownames(meta), stringsAsFactors=FALSE)
for (k in required) md[[k]] <- meta[[map[[k]]]]
if (anyDuplicated(rownames(counts)) || anyDuplicated(colnames(counts))) stop("Duplicate IDs")
dir.create(out, recursive=TRUE, showWarnings=FALSE)
writeMM(counts, file.path(out, "matrix.mtx"))
writeLines(rownames(counts), file.path(out, "genes.txt"))
writeLines(colnames(counts), file.path(out, "cells.txt"))
write.table(md, file.path(out,"cells.tsv"), sep="\t", quote=FALSE, row.names=FALSE)
capture.output(sessionInfo(), file=file.path(out,"R_sessionInfo.txt"))
