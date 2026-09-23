"""Site-level Group ICA preprocessing and MANCOVA execution."""

import copy
import glob
import json
import os
import shutil
import struct
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from framework import artifact, with_state

from .gift import gift_gica, gift_mancova
from .inputs import find_ica_parameter_files, resolve_gica_input_dir
from .types import SiteInputs, SiteMancovaResult, SiteScanInfo, TimepointPlan

NEUROMARK_NETWORKS = {
    "SC": [1, 2, 3, 4, 5],
    "AUD": [6, 7],
    "SM": [8, 9, 10, 11, 12, 13, 14, 15, 16],
    "VIS": [17, 18, 19, 20, 21, 22, 23, 24, 25],
    "CC": [26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42],
    "DMN": [43, 44, 45, 46, 47, 48, 49],
    "CR": [50, 51, 52, 53],
}

SKIP_COVARIATE_COLUMNS = {"filename", "niftifilename"}
STATS_INFO_MEDIA_TYPE = "application/x-matlab-data"


def convert_covariates(
    covariate_filename: str,
    output_dir: str,
    logger,
    covariate_types_file: str = None,
    num_samples: int = None,
) -> Tuple[Dict[str, list], pd.DataFrame, Dict[str, Any]]:
    """Process and convert covariate files for MANCOVA analysis."""
    logger.info("Loading covariates from %s", covariate_filename)
    df = pd.read_csv(covariate_filename)
    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, os.path.basename(covariate_filename))
    if os.path.abspath(covariate_filename) != os.path.abspath(dest):
        shutil.copy(covariate_filename, dest)

    cov_types: Dict[str, str] = {}
    if covariate_types_file and os.path.exists(covariate_types_file):
        keys_df = pd.read_csv(covariate_types_file)
        cov_types = dict(zip(keys_df["name"], keys_df["type"], strict=False))

    col_rename: Dict[str, str] = {}
    inferred_types: Dict[str, str] = {}
    for raw_col in df.columns:
        if raw_col in SKIP_COVARIATE_COLUMNS:
            continue
        if ":" in raw_col:
            clean, typ = raw_col.split(":", 1)
            col_rename[raw_col] = clean
            inferred_types[clean] = typ
    if col_rename:
        df = df.rename(columns=col_rename)

    covariates: Dict[str, list] = {}

    for covariate_name in df.columns:
        if covariate_name in SKIP_COVARIATE_COLUMNS:
            continue
        if covariate_types_file is not None and covariate_name not in cov_types:
            continue

        covariate_series = df[covariate_name]
        if num_samples and num_samples > 0:
            covariate_series = covariate_series[:num_samples]

        cov_type = cov_types.get(
            covariate_name, inferred_types.get(covariate_name, "continuous")
        )

        fname = os.path.join(output_dir, f"COINSTAC_COVAR_{covariate_name}.txt")
        with open(fname, "w") as f:
            f.write("\n".join([str(s) for s in list(covariate_series)]))

        covariates[covariate_name] = [cov_type, fname]
        logger.info("Processed covariate %s (%s): %s", covariate_name, cov_type, fname)

    if num_samples and num_samples > 0:
        df = df.head(num_samples)

    logger.info("Total covariates processed: %d", len(covariates))
    return covariates, df, cov_types


def _prepare_univariate_test(
    test_spec: Dict[str, Any], covariates_df: pd.DataFrame
) -> Any:
    key = list(test_spec.keys())[0]
    test_params = copy.deepcopy(test_spec[key])

    if key == "regression":
        return test_params

    variable = test_params.pop("variable", None)
    if variable is not None and isinstance(test_params, dict):
        datasets = [
            list(np.argwhere(covariates_df[variable] == name).flatten() + 1)
            for name in test_params.get("name", [])
        ]
        test_params["datasets"] = datasets

    return {key: test_params}


def _patch_mat_scans(src: str, dst: str, n_scans: int) -> None:
    """Patch numOfScans and diffTimePoints in an ICA parameter mat file."""
    try:
        import h5py

        if h5py.is_hdf5(src):
            current_n = _read_n_scans(src)
            shutil.copy2(src, dst)
            if current_n != 0 and current_n == n_scans:
                return
            with h5py.File(dst, "r+") as f:
                if "sesInfo/numOfScans" in f:
                    f["sesInfo/numOfScans"][0, 0] = float(n_scans)
                if "sesInfo/diffTimePoints" in f:
                    f["sesInfo/diffTimePoints"][:] = float(n_scans)
            return
    except Exception:
        pass
    shutil.copy2(src, dst)
    current_n = _read_n_scans(src)
    if current_n != 0 and current_n == n_scans:
        return
    with open(dst, "rb") as fh:
        data = bytearray(fh.read())
    double_bytes = struct.pack("<d", float(n_scans))
    for field in ("numOfScans", "diffTimePoints"):
        off, n_elem = _v5_find_field_offset(bytes(data), field)
        if off:
            for i in range(n_elem):
                data[off + i * 8 : off + (i + 1) * 8] = bytearray(double_bytes)
    with open(dst, "wb") as fh:
        fh.write(data)


def _v5_find_field_offset(data: bytes, field: str):
    needle = field.encode("ascii")
    pos = data.find(needle, 128)
    if pos < 0:
        return 0, 0
    search = data[pos + len(needle) :]
    double_tag = struct.pack("<I", 9)
    idx = search.find(double_tag)
    if idx < 0:
        return 0, 0
    type_off = pos + len(needle) + idx
    n_bytes = struct.unpack_from("<I", data, type_off + 4)[0]
    n_elem = max(1, n_bytes // 8)
    val_off = type_off + 8
    return val_off, n_elem


def _apply_common_timepoints(base_dir: str, staging_dir: str, n_tp: int, logger) -> str:
    """Truncate ICA timecourse NIfTIs and patch the parameter mat file to n_tp."""
    import nibabel as nib

    os.makedirs(staging_dir, exist_ok=True)
    truncated = 0
    for fname in os.listdir(base_dir):
        src = os.path.join(base_dir, fname)
        dst = os.path.join(staging_dir, fname)
        if not os.path.isfile(src):
            continue
        if "timecourses" in fname and (
            fname.endswith(".nii") or fname.endswith(".nii.gz")
        ):
            img = nib.load(src)
            data = img.get_fdata()
            if data.ndim >= 2 and data.shape[0] > n_tp:
                trunc = data[:n_tp, ...]
                new_img = nib.Nifti1Image(trunc, img.affine, img.header)
                new_img.header["dim"][1] = n_tp
                nib.save(new_img, dst)
                truncated += 1
            else:
                shutil.copy2(src, dst)
        elif "parameter_info.mat" in fname:
            _patch_mat_scans(src, dst, n_tp)
        else:
            shutil.copy2(src, dst)

    logger.info(
        "common_timepoints=%d: truncated %d NIfTIs -> %s", n_tp, truncated, staging_dir
    )
    return staging_dir


def _read_n_scans(mat_file: str) -> int:
    """Read numOfScans from an ICA parameter mat file (HDF5 or v5)."""
    try:
        import h5py

        with h5py.File(mat_file, "r") as f:
            if "sesInfo/numOfScans" in f:
                return int(f["sesInfo/numOfScans"][0, 0])
    except Exception:
        pass
    try:
        import scipy.io

        mat = scipy.io.loadmat(mat_file, struct_as_record=False, squeeze_me=True)
        return int(mat["sesInfo"].numOfScans)
    except Exception:
        pass
    return 0


def query_scan_length(inputs: SiteInputs, data_dir: str, parameters, logger) -> int:
    """Return the number of timepoints for this site's ICA data."""
    if parameters.get("skip_gica", False):
        base_dir = resolve_gica_input_dir(
            parameters.get("gica_input_dir", "."), data_dir
        )
        mat_files = sorted(
            glob.glob(
                os.path.join(base_dir, "**", "*parameter_info.mat"), recursive=True
            )
        )
        if mat_files:
            length = _read_n_scans(mat_files[0])
            if length:
                logger.info("query_scan_length: read %d from %s", length, mat_files[0])
                return length

    if inputs.nifti_files:
        import nibabel as nib

        img = nib.load(inputs.nifti_files[0])
        if img.ndim >= 4:
            length = img.shape[3]
            logger.info(
                "query_scan_length: read %d from %s", length, inputs.nifti_files[0]
            )
            return length

    logger.warning("query_scan_length: could not determine scan length")
    return 0


def report_scan_length(
    inputs: SiteInputs, *, data_dir: str, parameters: Dict[str, Any], logger
):
    """Report this site's scan length when common_timepoints negotiation is on.

    The validated inputs are cached as local state for the MANCOVA step.
    """
    scan_length = 0
    if parameters.get("common_timepoints") is True:
        scan_length = query_scan_length(inputs, data_dir, parameters, logger)
    return with_state(SiteScanInfo(scan_length=scan_length), inputs)


def _run_univariate_tests(
    ica_parameters, covariates, covariates_df, output_dir, parameters, logger
) -> Dict[str, list]:
    """Run each configured univariate test and return its stats_info files."""
    stats_files: Dict[str, list] = {}
    for univariate_test in parameters.get("univariate_test_list", []):
        key = list(univariate_test.keys())[0]
        test_obj = _prepare_univariate_test(univariate_test, covariates_df)
        out_dir = os.path.join(output_dir, f"coinstac-univariate-{key}")
        os.makedirs(out_dir, exist_ok=True)

        # Only pass covariates named in this test so all sites produce
        # stat_info matrices of identical shape for the aggregation step.
        test_params = univariate_test[key]
        if key == "regression":
            tested_vars = (
                set(test_params.keys()) if isinstance(test_params, dict) else set()
            )
        else:
            v = test_params.get("variable") if isinstance(test_params, dict) else None
            tested_vars = {v} if v else set()
        covariates_for_test = {
            k: v for k, v in covariates.items() if k in tested_vars
        } or covariates
        logger.info("Covariates for %s test: %s", key, list(covariates_for_test.keys()))

        gift_mancova(
            ica_param_file=ica_parameters,
            out_dir=out_dir,
            TR=parameters.get("TR", 2),
            features=parameters.get("features", []),
            comp_network_names=parameters.get("comp_network_names", NEUROMARK_NETWORKS),
            covariates=covariates_for_test,
            univariate_tests=test_obj,
            run_name=f"coinstac-mancovan-univariate-{key}",
            numOfPCs=parameters.get("numOfPCs", [4, 4, 4]),
            freq_limits=parameters.get("freq_limits", [0.1, 0.15]),
            t_threshold=parameters.get("t_threshold", 0.05),
            image_values=parameters.get("image_values", "positive"),
            threshdesc=parameters.get("threshdesc", "fdr"),
            p_threshold=parameters.get("p_threshold", 0.05),
            display_p_threshold=parameters.get("display_p_threshold", 0.05),
            display_local_result_summary=False,
            write_stats_info=1,
            site_logger=logger,
        )

        stats_files[key] = sorted(
            glob.glob(
                os.path.join(out_dir, "**", "*mancovan_stats_info.mat"), recursive=True
            )
        )
        logger.info("Found %d stats file(s) for test '%s'", len(stats_files[key]), key)
    return stats_files


def _stage_stats_artifacts(
    stats_files: Dict[str, list], artifact_dir: str
) -> Dict[str, Dict[str, Any]]:
    """Copy stats_info files into artifact_dir and declare them as artifacts."""
    staged: Dict[str, Dict[str, Any]] = {}
    for key, paths in stats_files.items():
        staged[key] = {}
        for path in paths:
            filename = os.path.basename(path)
            name = f"{key}-{filename}"
            staged_path = os.path.join(artifact_dir, name)
            shutil.copyfile(path, staged_path)
            staged[key][filename] = artifact(name, staged_path, STATS_INFO_MEDIA_TYPE)
    return staged


def run_site_mancova(
    plan: TimepointPlan,
    state: SiteInputs,
    *,
    data_dir: str,
    output_dir: str,
    artifact_dir: str,
    parameters: Dict[str, Any],
    logger,
) -> SiteMancovaResult:
    """Run site-level GICA and univariate MANCOVA, returning stats for pooling."""
    inputs = state
    logger.info("Running edge MANCOVA in %s", data_dir)
    logger.info("Parameters: %s", parameters)
    os.makedirs(output_dir, exist_ok=True)
    nifti_files = inputs.nifti_files

    covariates: Dict[str, list] = {}
    covariates_df = pd.DataFrame()
    cov_types: Dict[str, Any] = {}
    if inputs.covariates_file:
        covariates, covariates_df, cov_types = convert_covariates(
            covariate_filename=inputs.covariates_file,
            output_dir=output_dir,
            logger=logger,
            covariate_types_file=inputs.covariate_types_file,
            num_samples=len(nifti_files),
        )

    gica_output_dir = os.path.join(output_dir, "coinstac-gica")
    os.makedirs(gica_output_dir, exist_ok=True)

    skip_gica = parameters.get("skip_gica", False)
    gica_input_dir = parameters.get("gica_input_dir")

    if not skip_gica:
        template = parameters.get("scica_template") or parameters.get("template")
        curr_tr = parameters.get("TR", 2)
        curr_tr = curr_tr if isinstance(curr_tr, list) else [curr_tr]

        logger.info("Running Group ICA via GIFT")
        gift_gica(
            in_files=nifti_files,
            ref_files=template,
            mask=parameters.get("mask"),
            out_dir=gica_output_dir,
            dim=parameters.get("num_components", 53),
            algoType=parameters.get("algorithm", 16),
            run_name="coinstac-gica",
            scaleType=2,
            TR=curr_tr,
            comp_network_names=parameters.get("comp_network_names"),
            site_logger=logger,
        )
        base_dir = gica_output_dir
    elif gica_input_dir:
        base_dir = resolve_gica_input_dir(gica_input_dir, data_dir)
    else:
        base_dir = gica_output_dir

    common_timepoints = plan.common_timepoints
    if common_timepoints and "timecourses spectra" in parameters.get("features", []):
        staging_dir = os.path.join(output_dir, "coinstac-gica-truncated")
        base_dir = _apply_common_timepoints(
            base_dir, staging_dir, common_timepoints, logger
        )

    ica_parameters = find_ica_parameter_files(base_dir, logger)

    if parameters.get("run_mancova", False):
        logger.info("Running local full MANCOVA (site-level, not federated)")
        mancova_out_dir = os.path.join(output_dir, "coinstac-mancova")
        os.makedirs(mancova_out_dir, exist_ok=True)
        try:
            gift_mancova(
                ica_param_file=ica_parameters,
                out_dir=mancova_out_dir,
                TR=parameters.get("TR", 2),
                features=parameters.get("features", []),
                comp_network_names=parameters.get(
                    "comp_network_names", NEUROMARK_NETWORKS
                ),
                covariates=covariates,
                run_name="coinstac-mancovan",
                numOfPCs=parameters.get("numOfPCs", [4, 4, 4]),
                freq_limits=parameters.get("freq_limits", [0.1, 0.15]),
                t_threshold=parameters.get("t_threshold", 0.05),
                image_values=parameters.get("image_values", "positive"),
                threshdesc=parameters.get("threshdesc", "fdr"),
                p_threshold=parameters.get("p_threshold", 0.05),
                display_p_threshold=parameters.get("display_p_threshold", 0.05),
                display_local_result_summary=True,
                write_stats_info=0,
                site_logger=logger,
            )
        except Exception:
            logger.exception("Full MANCOVA failed (non-fatal)")

    stats_files: Dict[str, list] = {}
    if parameters.get("run_univariate_tests", False):
        logger.info("Running local univariate tests")
        stats_files = _run_univariate_tests(
            ica_parameters, covariates, covariates_df, output_dir, parameters, logger
        )

    _write_edge_summary(
        {
            "status": "completed",
            "data_directory": data_dir,
            "output_directory": output_dir,
            "covariates": covariates,
            "covariate_types": cov_types,
            "features": parameters.get("features", []),
            "gica_output_dir": gica_output_dir,
            "num_subjects": len(nifti_files),
            "num_covariates": len(covariates),
        },
        output_dir,
        logger,
    )

    logger.info("Edge MANCOVA completed")
    return SiteMancovaResult(
        status="completed",
        num_subjects=len(nifti_files),
        num_covariates=len(covariates),
        covariates_df=covariates_df,
        covariate_types=cov_types,
        features=parameters.get("features", []),
        output_directory=output_dir,
        stat_files=_stage_stats_artifacts(stats_files, artifact_dir),
    )


def _write_edge_summary(summary: Dict[str, Any], output_dir: str, logger) -> None:
    path = os.path.join(output_dir, "edge_mancova_results.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=4, default=str)
    logger.info("Saved %s", path)
