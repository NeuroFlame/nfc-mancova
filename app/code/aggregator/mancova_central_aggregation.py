"""
MANCOVA Central Node Aggregation Module

Handles server-side covariate combination, GIFT aggregate stats, and report generation.
Binary stats files are now written to disk by the aggregator's accept() step and passed
in as explicit file paths — no bytes-to-disk extraction happens here.
"""

import glob
import os
from typing import Any, Dict, List, Tuple

import pandas as pd

from _utils.gift_wrappers import gift_mancova_aggregate_stats
from _utils.logger import NvFlareLogger
from _utils.report_generator import generate_report


def combine_site_covariates(
    site_results: List[Dict[str, Any]],
    output_dir: str,
    logger: NvFlareLogger,
) -> Tuple[Dict[str, list], pd.DataFrame, Dict[str, Any]]:
    """Combine covariate DataFrames from all sites into a single pooled frame.

    Returns (all_covariates, combined_df, all_cov_types).
    Stats files are handled separately — the aggregator writes them via DXO.
    """
    logger.info(f"Combining covariates from {len(site_results)} sites")

    all_covariate_dfs: List[pd.DataFrame] = []
    all_cov_types: Dict[str, Any] = {}

    for i, site_result in enumerate(site_results):
        try:
            if site_result.get("covariates_df"):
                df = pd.DataFrame(site_result["covariates_df"])
                all_covariate_dfs.append(df)
                logger.info(f"Site {i}: {len(df)} subjects")

            if "covariate_types" in site_result:
                all_cov_types.update(site_result["covariate_types"])

        except Exception as e:
            logger.warning(f"Error processing site {i} covariates:", str(e))

    if all_covariate_dfs:
        combined_df = pd.concat(all_covariate_dfs, ignore_index=True)
        logger.info(f"Combined: {len(combined_df)} total subjects")
        combined_file = os.path.join(output_dir, "combined_covariates.csv")
        combined_df.to_csv(combined_file, index=False)
    else:
        combined_df = pd.DataFrame()

    _SKIP_COLS = {"filename", "niftifilename"}
    all_covariates: Dict[str, list] = {}
    for col in combined_df.columns:
        if col in _SKIP_COLS:
            continue
        cov_type = all_cov_types.get(col, "continuous")
        fname = os.path.join(output_dir, f"COINSTAC_COVAR_{col}.txt")
        with open(fname, "w") as f:
            f.write("\n".join(str(v) for v in combined_df[col]))
        all_covariates[col] = [cov_type, fname]
        logger.info(f"Wrote combined covariate {col} ({cov_type})")

    return all_covariates, combined_df, all_cov_types


def aggregate_mancova_results(
    site_results: List[Dict[str, Any]],
    site_names: List[str],
    stat_info_files: List[str],
    parameters: Dict[str, Any],
    aggregation_dir: str,
    logger: NvFlareLogger,
) -> Dict[str, Any]:
    """Aggregate edge node results at the central node."""
    logger.info(f"Aggregating MANCOVA results from {len(site_results)} sites")
    logger.info("Parameters:", parameters)

    try:
        os.makedirs(aggregation_dir, exist_ok=True)

        combined_covariates, combined_df, cov_types = combine_site_covariates(
            site_results=site_results,
            output_dir=aggregation_dir,
            logger=logger,
        )

        num_subjects = len(combined_df) if not combined_df.empty else 0
        num_covariates = len(combined_covariates)

        global_results: Dict[str, Any] = {
            "status": "aggregation_completed",
            "num_sites": len(site_results),
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
            for sr in site_results:
                site_out = sr.get("output_directory", "")
                if site_out:
                    summary_html = os.path.join(
                        site_out, "coinstac-mancova",
                        "gica_cmd_mancovan_results_summary",
                        "icatb_mancovan_results_summary.html",
                    )
                    if os.path.exists(summary_html):
                        global_results["multivariate_result_paths"].append(summary_html)
                        logger.info("Found per-site MANCOVA summary:", summary_html)

        if parameters.get("run_univariate_tests", False) and stat_info_files:
            logger.info(f"Running global univariate aggregation on {len(stat_info_files)} files")
            for univariate_test in parameters.get("univariate_test_list", []):
                key = list(univariate_test.keys())[0]
                variable = (
                    univariate_test[key].get("variable", "")
                    if isinstance(univariate_test[key], dict) else ""
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
                    glob.glob(os.path.join(univariate_out_dir, "**", "*.html"), recursive=True)
                )

        report_path = generate_report(
            output_dir=aggregation_dir,
            global_results=global_results,
            site_results=site_results,
            site_names=site_names,
            parameters=parameters,
        )
        global_results["report_path"] = report_path
        logger.info("Report written to", report_path)
        with open(report_path, "r") as f:
            global_results["report_html"] = f.read()

        logger.info("Central MANCOVA aggregation completed:", global_results["status"])
        return global_results

    except Exception as e:
        logger.error("Error during aggregation:", str(e))
        return {
            "status": "aggregation_failed",
            "error": str(e),
            "num_sites": len(site_results),
        }
