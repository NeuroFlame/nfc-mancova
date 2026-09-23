"""Central covariate pooling, GIFT aggregate statistics, and report generation."""

import glob
import os
import shutil
import tarfile
from typing import Any, Dict, List, Tuple

import pandas as pd
from framework import artifact

from .gift import gift_mancova_aggregate_stats
from .local_math import SKIP_COVARIATE_COLUMNS
from .report import generate_report
from .types import GlobalResults, SiteMancovaResult, SiteScanInfo, TimepointPlan

AGGREGATION_ARCHIVE_NAME = "aggregation.tar.gz"


def resolve_common_timepoints(
    site_scans: Dict[str, SiteScanInfo], *, parameters: Dict[str, Any], logger
) -> TimepointPlan:
    """Resolve common_timepoints: the minimum site scan length when set to true."""
    requested = parameters.get("common_timepoints", 0)
    if requested is True:
        lengths = [s.scan_length for s in site_scans.values() if s.scan_length]
        if lengths:
            resolved = min(lengths)
            logger.info(
                "common_timepoints negotiated: site lengths=%s -> min=%d",
                lengths,
                resolved,
            )
            return TimepointPlan(common_timepoints=resolved)
        logger.warning(
            "common_timepoints=true but no scan lengths received; disabling truncation"
        )
        return TimepointPlan(common_timepoints=0)
    if isinstance(requested, int) and not isinstance(requested, bool):
        return TimepointPlan(common_timepoints=requested)
    return TimepointPlan(common_timepoints=0)


def combine_site_covariates(
    covariate_dfs: List[pd.DataFrame],
    covariate_types: List[Dict[str, str]],
    output_dir: str,
    logger,
) -> Tuple[Dict[str, list], pd.DataFrame, Dict[str, Any]]:
    """Combine covariate DataFrames from all sites into a single pooled frame.

    Returns (all_covariates, combined_df, all_cov_types).
    """
    logger.info("Combining covariates from %d sites", len(covariate_dfs))

    all_cov_types: Dict[str, Any] = {}
    for types in covariate_types:
        all_cov_types.update(types)

    non_empty = [df for df in covariate_dfs if not df.empty]
    for i, df in enumerate(non_empty):
        logger.info("Site %d: %d subjects", i, len(df))

    if non_empty:
        combined_df = pd.concat(non_empty, ignore_index=True)
        logger.info("Combined: %d total subjects", len(combined_df))
        combined_df.to_csv(
            os.path.join(output_dir, "combined_covariates.csv"), index=False
        )
    else:
        combined_df = pd.DataFrame()

    all_covariates: Dict[str, list] = {}
    for col in combined_df.columns:
        if col in SKIP_COVARIATE_COLUMNS:
            continue
        cov_type = all_cov_types.get(col, "continuous")
        fname = os.path.join(output_dir, f"COINSTAC_COVAR_{col}.txt")
        with open(fname, "w") as f:
            f.write("\n".join(str(v) for v in combined_df[col]))
        all_covariates[col] = [cov_type, fname]
        logger.info("Wrote combined covariate %s (%s)", col, cov_type)

    return all_covariates, combined_df, all_cov_types


def _order_site_names(site_names, parameters: Dict[str, Any]) -> List[str]:
    """Order sites as provisioned, falling back to sorted display names."""
    provisioned = list(parameters.get("site_id_name_map", {}).values())
    ordered = [name for name in provisioned if name in site_names]
    ordered += sorted(name for name in site_names if name not in provisioned)
    return ordered


def _write_site_stats_files(
    site_name: str, result: SiteMancovaResult, aggregation_dir: str
) -> List[str]:
    """Copy a site's received stats_info artifacts into the aggregation directory.

    Received artifacts live in framework staging that is removed at run end.
    """
    written = []
    for test_key, files in result.stat_files.items():
        test_dir = os.path.join(aggregation_dir, site_name, test_key)
        os.makedirs(test_dir, exist_ok=True)
        for filename, ref in files.items():
            destination = os.path.join(test_dir, filename)
            shutil.copyfile(ref.path, destination)
            written.append(filename)
    return written


def _archive_directory(source_dir: str, archive_path: str) -> None:
    """Tar and gzip source_dir, skipping hidden framework-owned entries."""

    def _exclude_hidden(info: tarfile.TarInfo):
        parts = info.name.split("/")
        return None if any(part.startswith(".") for part in parts[1:]) else info

    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source_dir, arcname=".", filter=_exclude_hidden)


def aggregate_mancova(
    site_results: Dict[str, SiteMancovaResult],
    *,
    output_dir: str,
    artifact_dir: str,
    parameters: Dict[str, Any],
    logger,
) -> GlobalResults:
    """Pool site covariates, run GIFT aggregate stats, and build the report."""
    aggregation_dir = output_dir
    os.makedirs(aggregation_dir, exist_ok=True)
    site_names = _order_site_names(site_results.keys(), parameters)
    ordered_results = [site_results[name] for name in site_names]
    logger.info("Aggregating MANCOVA results from %d sites", len(site_names))
    logger.info("Parameters: %s", parameters)

    report_site_results = []
    for name, result in zip(site_names, ordered_results, strict=True):
        written = _write_site_stats_files(name, result, aggregation_dir)
        logger.info("Wrote %d stats file(s) for site %s", len(written), name)
        report_site_results.append(
            {
                "status": result.status,
                "num_subjects": result.num_subjects,
                "num_covariates": result.num_covariates,
                "output_directory": result.output_directory,
                "univariate_stat_info_files": written,
            }
        )

    stat_info_files = sorted(
        glob.glob(
            os.path.join(aggregation_dir, "**", "*mancovan_stats_info.mat"),
            recursive=True,
        )
    )
    logger.info("Collected %d stats file(s) for aggregation", len(stat_info_files))

    combined_covariates, combined_df, _ = combine_site_covariates(
        covariate_dfs=[r.covariates_df for r in ordered_results],
        covariate_types=[r.covariate_types for r in ordered_results],
        output_dir=aggregation_dir,
        logger=logger,
    )

    num_subjects = len(combined_df) if not combined_df.empty else 0
    num_covariates = len(combined_covariates)

    global_results: Dict[str, Any] = {
        "status": "aggregation_completed",
        "num_sites": len(site_names),
        "num_subjects": num_subjects,
        "num_covariates": num_covariates,
        "covariates_combined": bool(combined_covariates),
        "features": parameters.get("features", []),
        "interactions": parameters.get("interactions", []),
        "run_univariate_tests": parameters.get("run_univariate_tests", False),
        "run_mancova": parameters.get("run_mancova", False),
        "mancova_ready": num_subjects > 0 and num_covariates > 0,
        "aggregation_directory": aggregation_dir,
        "multivariate_statistics": None,
        "univariate_tests": None,
        "visualizations": None,
        "multivariate_result_paths": [],
        "univariate_result_paths": {},
    }

    if parameters.get("run_mancova", False):
        # Per-site summaries are only reachable when sites share a filesystem
        # with the server, as in the simulator.
        for result in ordered_results:
            summary_html = os.path.join(
                result.output_directory,
                "coinstac-mancova",
                "gica_cmd_mancovan_results_summary",
                "icatb_mancovan_results_summary.html",
            )
            if os.path.exists(summary_html):
                global_results["multivariate_result_paths"].append(summary_html)
                logger.info("Found per-site MANCOVA summary: %s", summary_html)

    if parameters.get("run_univariate_tests", False) and stat_info_files:
        logger.info(
            "Running global univariate aggregation on %d files", len(stat_info_files)
        )
        for univariate_test in parameters.get("univariate_test_list", []):
            key = list(univariate_test.keys())[0]
            variable = (
                univariate_test[key].get("variable", "")
                if isinstance(univariate_test[key], dict)
                else ""
            )
            test_name = f"{key}-{variable}" if key != "regression" else key
            univariate_out_dir = os.path.join(
                aggregation_dir, f"coinstac-global-univariate-{test_name}"
            )
            os.makedirs(univariate_out_dir, exist_ok=True)

            gift_mancova_aggregate_stats(
                ica_param_file_list=stat_info_files,
                out_dir=univariate_out_dir,
                freq_limits=parameters.get("freq_limits", [0.1, 0.15]),
                t_threshold=parameters.get("t_threshold", 1.0),
                image_values=parameters.get("image_values", "positive"),
                threshdesc=parameters.get("threshdesc", "fdr"),
                p_threshold=parameters.get("p_threshold", 0.05),
                display_p_threshold=parameters.get("display_p_threshold", 0.05),
                site_logger=logger,
            )
            global_results["univariate_result_paths"][test_name] = sorted(
                glob.glob(
                    os.path.join(univariate_out_dir, "**", "*.html"), recursive=True
                )
            )

    report_path = generate_report(
        output_dir=aggregation_dir,
        global_results=global_results,
        site_results=report_site_results,
        site_names=site_names,
        parameters=parameters,
    )
    global_results.pop("report_html", None)
    global_results["report_path"] = report_path
    logger.info("Report written to %s", report_path)

    archive_path = os.path.join(artifact_dir, AGGREGATION_ARCHIVE_NAME)
    _archive_directory(aggregation_dir, archive_path)
    logger.info(
        "Packaged aggregation directory (%d bytes) for site delivery",
        os.path.getsize(archive_path),
    )

    logger.info("Central MANCOVA aggregation completed: %s", global_results["status"])
    return GlobalResults(
        summary=global_results,
        aggregation_archive=artifact(
            AGGREGATION_ARCHIVE_NAME, archive_path, "application/gzip"
        ),
    )


def write_site_outputs(result: GlobalResults, *, output_dir: str, logger):
    """Unpack the aggregation directory and write the report and summary."""
    aggregation_dir = os.path.join(output_dir, "aggregation")
    os.makedirs(aggregation_dir, exist_ok=True)
    with tarfile.open(result.aggregation_archive.path, "r:gz") as archive:
        archive.extractall(aggregation_dir, filter="data")
    logger.info("Unpacked aggregation files to %s", aggregation_dir)

    outputs: Dict[str, Any] = {"global_mancova_results.json": result.summary}
    report_path = os.path.join(aggregation_dir, "index.html")
    if os.path.exists(report_path):
        with open(report_path, "r") as f:
            outputs["index.html"] = f.read()
    else:
        logger.warning("Aggregation archive contained no index.html report")
    return outputs
