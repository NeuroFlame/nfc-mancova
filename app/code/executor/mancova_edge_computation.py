"""
MANCOVA Edge Node Computation Module

Handles site-level Group ICA preprocessing and MANCOVA execution.
All logging goes through the per-site ConfigDTO.logger so concurrent
site threads in the simulator never write to a shared handler.
"""

import copy
import glob
import os
import shutil
import struct
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd

from _utils.gift_wrappers import gift_gica, gift_mancova
from _utils.types import ConfigDTO
from .edge_validation import validate_edge_inputs, validate_ica_parameters

NEUROMARK_NETWORKS = {
    "SC": [1, 2, 3, 4, 5],
    "AUD": [6, 7],
    "SM": [8, 9, 10, 11, 12, 13, 14, 15, 16],
    "VIS": [17, 18, 19, 20, 21, 22, 23, 24, 25],
    "CC": [26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42],
    "DMN": [43, 44, 45, 46, 47, 48, 49],
    "CR": [50, 51, 52, 53],
}


def convert_covariates(
    covariate_filename: str,
    output_dir: str,
    config: ConfigDTO,
    covariate_types_file: str = None,
    num_samples: int = None,
) -> Tuple[Dict[str, list], pd.DataFrame, Dict[str, Any]]:
    """Process and convert covariate files for MANCOVA analysis."""
    config.logger.info("Loading covariates from", covariate_filename)
    df = pd.read_csv(covariate_filename)
    os.makedirs(output_dir, exist_ok=True)
    dest = os.path.join(output_dir, os.path.basename(covariate_filename))
    if os.path.abspath(covariate_filename) != os.path.abspath(dest):
        shutil.copy(covariate_filename, dest)

    cov_types: Dict[str, str] = {}
    if covariate_types_file and os.path.exists(covariate_types_file):
        keys_df = pd.read_csv(covariate_types_file)
        cov_types = dict(zip(keys_df["name"], keys_df["type"]))

    _SKIP_COLS = {"filename", "niftifilename"}

    col_rename: Dict[str, str] = {}
    inferred_types: Dict[str, str] = {}
    for raw_col in df.columns:
        if raw_col in _SKIP_COLS:
            continue
        if ":" in raw_col:
            clean, typ = raw_col.split(":", 1)
            col_rename[raw_col] = clean
            inferred_types[clean] = typ
    if col_rename:
        df = df.rename(columns=col_rename)

    covariates: Dict[str, list] = {}

    for covariate_name in df.columns:
        if covariate_name in _SKIP_COLS:
            continue
        if covariate_types_file is not None and covariate_name not in cov_types:
            continue

        covariate_series = df[covariate_name]
        if num_samples and num_samples > 0:
            covariate_series = covariate_series[:num_samples]

        cov_type = cov_types.get(covariate_name, inferred_types.get(covariate_name, "continuous"))

        fname = os.path.join(output_dir, f"COINSTAC_COVAR_{covariate_name}.txt")
        with open(fname, "w") as f:
            f.write("\n".join([str(s) for s in list(covariate_series)]))

        covariates[covariate_name] = [cov_type, fname]
        config.logger.info(f"Processed covariate {covariate_name} ({cov_type}): {fname}")

    if num_samples and num_samples > 0:
        df = df.head(num_samples)

    config.logger.info(f"Total covariates processed: {len(covariates)}")
    return covariates, df, cov_types


def _prepare_univariate_test(test_spec: Dict[str, Any], covariates_df: pd.DataFrame) -> Any:
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
    search = data[pos + len(needle):]
    double_tag = struct.pack("<I", 9)
    idx = search.find(double_tag)
    if idx < 0:
        return 0, 0
    type_off = pos + len(needle) + idx
    n_bytes = struct.unpack_from("<I", data, type_off + 4)[0]
    n_elem = max(1, n_bytes // 8)
    val_off = type_off + 8
    return val_off, n_elem


def _apply_common_timepoints(base_dir: str, staging_dir: str, n_tp: int, config: ConfigDTO) -> str:
    """Truncate ICA timecourse NIfTIs and patch the parameter mat file to n_tp timepoints."""
    import nibabel as nib

    os.makedirs(staging_dir, exist_ok=True)
    truncated = 0
    for fname in os.listdir(base_dir):
        src = os.path.join(base_dir, fname)
        dst = os.path.join(staging_dir, fname)
        if not os.path.isfile(src):
            continue
        if "timecourses" in fname and (fname.endswith(".nii") or fname.endswith(".nii.gz")):
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

    config.logger.info(f"common_timepoints={n_tp}: truncated {truncated} NIfTIs → {staging_dir}")
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


def query_scan_length(config: ConfigDTO) -> int:
    """Return the number of timepoints for this site's ICA data."""
    params = config.parameters
    skip_gica = params.get("skip_gica", False)
    gica_input_dir = params.get("gica_input_dir", ".")

    if skip_gica:
        base_dir = (
            gica_input_dir
            if os.path.isabs(gica_input_dir)
            else os.path.join(config.data_dir, gica_input_dir)
        )
        mat_files = sorted(glob.glob(os.path.join(base_dir, "**", "*parameter_info.mat"), recursive=True))
        if mat_files:
            length = _read_n_scans(mat_files[0])
            if length:
                config.logger.info(f"query_scan_length: read {length} from {mat_files[0]}")
                return length

    nifti_files = sorted(
        glob.glob(os.path.join(config.data_dir, "*.nii.gz"))
        + glob.glob(os.path.join(config.data_dir, "*.nii"))
    )
    if nifti_files:
        import nibabel as nib
        img = nib.load(nifti_files[0])
        if img.ndim >= 4:
            length = img.shape[3]
            config.logger.info(f"query_scan_length: read {length} from {nifti_files[0]}")
            return length

    config.logger.warning("query_scan_length: could not determine scan length")
    return 0


def run_edge_mancova(config: ConfigDTO) -> Dict[str, Any]:
    """Execute site-level MANCOVA computations.

    Returns a dict with:
      - JSON-serializable metadata fields
      - "univariate_stat_info_files": {test_key: {filename: bytes}}
        ready to be wrapped in a DXO(DataKind.COLLECTION)
    """
    config.logger.info("Running edge MANCOVA in", config.data_dir)
    config.logger.info("Parameters:", config.parameters)
    os.makedirs(config.output_dir, exist_ok=True)

    validate_edge_inputs(config)

    try:
        nifti_files = sorted(
            glob.glob(os.path.join(config.data_dir, "*.nii.gz"))
            + glob.glob(os.path.join(config.data_dir, "*.nii"))
        )
        max_subjects = config.parameters.get("max_subjects")
        if max_subjects:
            nifti_files = nifti_files[:max_subjects]
        config.logger.info(f"Found {len(nifti_files)} NIfTI files (max_subjects={max_subjects})")

        covar_files = glob.glob(os.path.join(config.data_dir, "*covariates.csv"))
        covar_type_files = glob.glob(os.path.join(config.data_dir, "*covariate_keys.csv"))

        covariates: Dict[str, list] = {}
        covariates_df = pd.DataFrame()
        cov_types: Dict[str, Any] = {}

        if covar_files:
            covar_file = covar_files[0]
            covar_type_file = covar_type_files[0] if covar_type_files else None
            config.logger.info("Processing covariates from", covar_file)
            covariates, covariates_df, cov_types = convert_covariates(
                covariate_filename=covar_file,
                output_dir=config.output_dir,
                config=config,
                covariate_types_file=covar_type_file,
                num_samples=len(nifti_files),
            )

        gica_output_dir = os.path.join(config.output_dir, "coinstac-gica")
        os.makedirs(gica_output_dir, exist_ok=True)

        skip_gica = config.parameters.get("skip_gica", False)
        gica_input_dir = config.parameters.get("gica_input_dir")
        base_dir = None

        if not skip_gica:
            template = config.parameters.get("scica_template") or config.parameters.get("template")
            mask = config.parameters.get("mask")
            curr_TR = config.parameters.get("TR", 2)
            curr_TR = curr_TR if isinstance(curr_TR, list) else [curr_TR]

            config.logger.info("Running Group ICA via GIFT")
            gift_gica(
                in_files=nifti_files,
                ref_files=template,
                mask=mask,
                out_dir=gica_output_dir,
                dim=config.parameters.get("num_components", 53),
                algoType=config.parameters.get("algorithm", 16),
                run_name="coinstac-gica",
                scaleType=2,
                TR=curr_TR,
                comp_network_names=config.parameters.get("comp_network_names"),
                site_logger=config.logger,
            )
            base_dir = gica_output_dir
        elif gica_input_dir:
            base_dir = (
                gica_input_dir
                if os.path.isabs(gica_input_dir)
                else os.path.join(config.data_dir, gica_input_dir)
            )
        else:
            base_dir = gica_output_dir

        common_timepoints = config.parameters.get("common_timepoints", 0)
        if common_timepoints and "timecourses spectra" in config.parameters.get("features", []):
            staging_dir = os.path.join(config.output_dir, "coinstac-gica-truncated")
            base_dir = _apply_common_timepoints(base_dir, staging_dir, common_timepoints, config)

        ica_parameters = validate_ica_parameters(base_dir, config)

        # {test_key: {filename: bytes}} — DXO(DataKind.COLLECTION)-ready
        stat_info_files: Dict[str, Dict[str, bytes]] = {}

        if config.parameters.get("run_mancova", False):
            config.logger.info("Running local full MANCOVA (site-level, not federated)")
            mancova_out_dir = os.path.join(config.output_dir, "coinstac-mancova")
            os.makedirs(mancova_out_dir, exist_ok=True)
            try:
                gift_mancova(
                    ica_param_file=ica_parameters,
                    out_dir=mancova_out_dir,
                    TR=config.parameters.get("TR", 2),
                    features=config.parameters.get("features", []),
                    comp_network_names=config.parameters.get("comp_network_names", NEUROMARK_NETWORKS),
                    covariates=covariates,
                    run_name="coinstac-mancovan",
                    numOfPCs=config.parameters.get("numOfPCs", [4, 4, 4]),
                    freq_limits=config.parameters.get("freq_limits", [0.1, 0.15]),
                    t_threshold=config.parameters.get("t_threshold", 0.05),
                    image_values=config.parameters.get("image_values", "positive"),
                    threshdesc=config.parameters.get("threshdesc", "fdr"),
                    p_threshold=config.parameters.get("p_threshold", 0.05),
                    display_p_threshold=config.parameters.get("display_p_threshold", 0.05),
                    display_local_result_summary=True,
                    write_stats_info=0,
                    site_logger=config.logger,
                )
            except Exception as mancova_err:
                config.logger.error("Full MANCOVA failed (non-fatal):", mancova_err)

        if config.parameters.get("run_univariate_tests", False):
            config.logger.info("Running local univariate tests")
            for univariate_test in config.parameters.get("univariate_test_list", []):
                key = list(univariate_test.keys())[0]
                test_obj = _prepare_univariate_test(univariate_test, covariates_df)
                out_dir = os.path.join(config.output_dir, f"coinstac-univariate-{key}")
                os.makedirs(out_dir, exist_ok=True)

                # Only pass covariates named in this test so all sites produce
                # stat_info matrices of identical shape for the aggregation step.
                test_params = univariate_test[key]
                if key == "regression":
                    tested_vars = set(test_params.keys()) if isinstance(test_params, dict) else set()
                else:
                    v = test_params.get("variable") if isinstance(test_params, dict) else None
                    tested_vars = {v} if v else set()
                covariates_for_test = {k: v for k, v in covariates.items() if k in tested_vars} or covariates
                config.logger.info(f"Covariates for {key} test:", list(covariates_for_test.keys()))

                gift_mancova(
                    ica_param_file=ica_parameters,
                    out_dir=out_dir,
                    TR=config.parameters.get("TR", 2),
                    features=config.parameters.get("features", []),
                    comp_network_names=config.parameters.get("comp_network_names", NEUROMARK_NETWORKS),
                    covariates=covariates_for_test,
                    univariate_tests=test_obj,
                    run_name=f"coinstac-mancovan-univariate-{key}",
                    numOfPCs=config.parameters.get("numOfPCs", [4, 4, 4]),
                    freq_limits=config.parameters.get("freq_limits", [0.1, 0.15]),
                    t_threshold=config.parameters.get("t_threshold", 0.05),
                    image_values=config.parameters.get("image_values", "positive"),
                    threshdesc=config.parameters.get("threshdesc", "fdr"),
                    p_threshold=config.parameters.get("p_threshold", 0.05),
                    display_p_threshold=config.parameters.get("display_p_threshold", 0.05),
                    display_local_result_summary=False,
                    write_stats_info=1,
                    site_logger=config.logger,
                )

                file_blobs: Dict[str, bytes] = {}
                for mat_path in sorted(glob.glob(
                    os.path.join(out_dir, "**", "*mancovan_stats_info.mat"), recursive=True
                )):
                    with open(mat_path, "rb") as f:
                        file_blobs[os.path.basename(mat_path)] = f.read()
                stat_info_files[key] = file_blobs
                config.logger.info(f"Packaged {len(file_blobs)} stats file(s) for test '{key}'")

        results = {
            "status": "completed",
            "data_directory": config.data_dir,
            "output_directory": config.output_dir,
            "covariates": covariates,
            "covariates_df": (
                covariates_df.where(covariates_df.notna(), other=None).to_dict()
                if not covariates_df.empty else {}
            ),
            "covariate_types": cov_types,
            "features": config.parameters.get("features", []),
            "gica_output_dir": gica_output_dir,
            "num_subjects": len(nifti_files),
            "num_covariates": len(covariates),
            # DXO payload — binary blobs, not JSON-serialised into the shareable dict
            "univariate_stat_info_files": stat_info_files,
        }

        config.logger.info("Edge MANCOVA completed:", results["status"])
        return results

    except Exception as e:
        config.logger.error("Error during edge MANCOVA:", str(e))
        return {
            "status": "failed",
            "error": str(e),
            "data_directory": config.data_dir,
            "output_directory": config.output_dir,
            "univariate_stat_info_files": {},
        }
