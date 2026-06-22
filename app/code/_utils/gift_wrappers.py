"""
GIFT MATLAB wrapper utilities for nfc-mancova.

This module provides thin wrappers around the COINSTAC GIFT interface for
Group ICA and MANCOVA execution.

The functions are intended to be used by edge and aggregator modules when
MATLAB Runtime and the GIFT toolbox are available.
"""

import importlib
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from _utils.logger import NvFlareLogger

nib = None
resample_from_to = None
gift = None

GIFT_HOME = os.environ.get("GIFT_HOME", "/app/groupicatv4.0b")
MCR_ROOT = os.environ.get(
    "MCRROOT",
    os.environ.get("MATLAB_RUNTIME", "/usr/local/MATLAB/MATLAB_Runtime/v91"),
)
MATLAB_CMD = os.environ.get(
    "MATLAB_CMD",
    f"{GIFT_HOME}/GroupICATv4.0b_standalone/run_groupica.sh {MCR_ROOT}/",
)


def _load_gift_modules():
    global nib, resample_from_to, gift
    if gift is not None and nib is not None:
        return

    try:
        nib = importlib.import_module("nibabel")
        resample_from_to = importlib.import_module("nibabel.processing").resample_from_to
        gift = importlib.import_module("nipype.interfaces.gift")
    except ImportError as e:
        raise ImportError(
            "GIFT wrapper imports failed. Ensure nipype and nibabel are installed: "
            f"{e}"
        )

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 60  # seconds between "still running" log lines


def _run_with_logging(cmd, label: str, site_logger: "Optional[NvFlareLogger]" = None) -> Any:
    """Run a nipype command with periodic heartbeat logging and full error capture.

    When site_logger is provided (a NvFlareLogger), heartbeat lines go to that
    per-site log so two concurrent GIFT calls are never interleaved under the same
    logger. Falls back to the module-level logger for aggregator calls.
    """
    _log_info = site_logger.info if site_logger is not None else logger.info
    _log_error = site_logger.error if site_logger is not None else logger.error

    result_holder: list = [None]
    error_holder: list = [None]
    done = threading.Event()

    def _worker():
        try:
            result_holder[0] = cmd.run()
        except Exception as exc:
            error_holder[0] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    start = time.monotonic()

    while not done.wait(HEARTBEAT_INTERVAL):
        elapsed = int(time.monotonic() - start)
        _log_info(f"{label}: still running ({elapsed}s elapsed)...")

    elapsed = int(time.monotonic() - start)

    if error_holder[0] is not None:
        exc = error_holder[0]
        _log_error(f"{label} failed after {elapsed}s:\n{exc}")
        raise exc

    _log_info(f"{label}: completed in {elapsed}s")
    return result_holder[0]


DEFAULT_THRESHDESC = "fdr"
DEFAULT_DISPLAY_RESULTS = 1
DEFAULT_FEATURES = []
DEFAULT_COVARIATES = {}
DEFAULT_INTERACTIONS = []
DEFAULT_P_THRESHOLD = 1.0
DEFAULT_COMP_NETWORK_NAMES: Dict[str, Any] = {}


def get_interpolated_nifti(template_filename: str, input_filename: str, destination_dir: str = "/out") -> str:
    """Interpolate a NIfTI file to match the spatial dimensions of a template."""
    _load_gift_modules()
    base_dir = os.path.dirname(input_filename)
    input_prefix, input_ext = os.path.splitext(input_filename)
    template_img = nib.load(template_filename)
    input_img = nib.load(input_filename)
    template_img = template_img.slicer[:, :, :, : input_img.shape[3]]
    template_dim = template_img.shape

    if input_img.shape == template_dim:
        return input_filename

    output_filename = os.path.join(
        base_dir,
        "%s_INTERP_%d_%d_%d.nii"
        % (
            input_prefix,
            template_img.shape[0],
            template_img.shape[1],
            template_img.shape[2],
        ),
    )

    if os.path.exists(output_filename):
        return output_filename

    output_img = resample_from_to(input_img, template_img)
    if destination_dir is not None:
        output_filename = os.path.join(destination_dir, os.path.basename(output_filename))
    nib.save(output_img, output_filename)

    return output_filename


def gift_gica(
    in_files: List[str],
    ref_files: str,
    mask: Optional[str],
    out_dir: str,
    dim: int = 53,
    algoType: int = 16,
    run_name: str = "coinstac-gica",
    group_pca_type: str = "subject specific",
    scaleType: int = 2,
    TR: Any = 2,
    comp_network_names: Optional[Dict[str, Any]] = None,
    site_logger: "Optional[NvFlareLogger]" = None,
) -> Any:
    """Run GIFT Group ICA using nipype."""
    _load_gift_modules()
    if not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    gift.GICACommand.set_mlab_paths(matlab_cmd=MATLAB_CMD, use_mcr=True)
    gc = gift.GICACommand()
    gc.inputs.in_files = in_files
    gc.inputs.algoType = algoType
    gc.inputs.prefix = run_name
    gc.inputs.group_pca_type = group_pca_type
    gc.inputs.backReconType = 1
    gc.inputs.preproc_type = 1
    gc.inputs.numReductionSteps = 1
    gc.inputs.scaleType = scaleType
    gc.inputs.group_ica_type = "spatial"
    gc.inputs.which_analysis = 1
    gc.inputs.refFiles = get_interpolated_nifti(in_files[0], ref_files, out_dir)
    gc.inputs.display_results = DEFAULT_DISPLAY_RESULTS
    gc.inputs.TR = TR
    if mask is not None:
        gc.inputs.mask = mask
    if comp_network_names is not None:
        gc.inputs.network_summary_opts = {"comp_network_names": comp_network_names}
    if dim > 0:
        gc.inputs.dim = dim

    gc.inputs.out_dir = out_dir
    return _run_with_logging(gc, "GIFT GICA", site_logger)


def gift_mancova(
    ica_param_file: Any,
    out_dir: str,
    run_name: str = "coinstac-mancovan",
    comp_network_names: Optional[Dict[str, Any]] = None,
    TR: Any = 2,
    features: Optional[List[str]] = None,
    covariates: Optional[Dict[str, Any]] = None,
    interactions: Optional[List[Any]] = None,
    numOfPCs: Any = 53,
    feature_params: Optional[Dict[str, Any]] = None,
    p_threshold: float = DEFAULT_P_THRESHOLD,
    univariate_tests: Optional[Any] = None,
    freq_limits: Any = [0.1, 0.15],
    t_threshold: float = 1.0,
    image_values: str = "positive",
    threshdesc: str = DEFAULT_THRESHDESC,
    display_p_threshold: float = DEFAULT_P_THRESHOLD,
    display_local_result_summary: bool = False,
    write_stats_info: int = 1,
    site_logger: "Optional[NvFlareLogger]" = None,
) -> Any:
    """Run GIFT MANCOVA analysis using nipype."""
    _load_gift_modules()
    if not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    gift.MancovanCommand.set_mlab_paths(matlab_cmd=MATLAB_CMD, use_mcr=True)
    gc = gift.MancovanCommand()
    gc.inputs.ica_param_file = ica_param_file
    gc.inputs.out_dir = out_dir
    gc.inputs.comp_network_names = comp_network_names or DEFAULT_COMP_NETWORK_NAMES
    gc.inputs.TR = TR
    gc.inputs.features = features or DEFAULT_FEATURES
    gc.inputs.covariates = covariates or DEFAULT_COVARIATES
    gc.inputs.interactions = interactions or DEFAULT_INTERACTIONS
    gc.inputs.numOfPCs = numOfPCs
    gc.inputs.feature_params = feature_params or {}
    gc.inputs.p_threshold = p_threshold
    gc.inputs.write_stats_info = write_stats_info

    if display_local_result_summary:
        gc.inputs.display = {
            "freq_limits": freq_limits,
            "structFile": "/app/groupicatv4.0b/icatb/src/icatb_templates/ch2bet.nii",
            "t_threshold": t_threshold,
            "image_values": image_values,
            "threshdesc": threshdesc,
            "p_threshold": display_p_threshold,
        }

    if univariate_tests is not None:
        gc.inputs.univariate_tests = univariate_tests

    return _run_with_logging(gc, "GIFT MANCOVA", site_logger)


def gift_mancova_aggregate_stats(
    ica_param_file_list: Any,
    out_dir: str,
    freq_limits: Any = [0.1, 0.15],
    p_threshold: float = DEFAULT_P_THRESHOLD,
    t_threshold: float = 1.0,
    image_values: str = "positive",
    threshdesc: str = DEFAULT_THRESHDESC,
    display_p_threshold: float = DEFAULT_P_THRESHOLD,
    site_logger: "Optional[NvFlareLogger]" = None,
) -> Any:
    """Aggregate MANCOVA stats info files into global results."""
    _load_gift_modules()
    if not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    gift.MancovanCommand.set_mlab_paths(matlab_cmd=MATLAB_CMD, use_mcr=True)
    mc = gift.MancovanCommand()
    mc.inputs.out_dir = out_dir
    mc.inputs.ica_param_file = ica_param_file_list
    mc.inputs.display = {
        "freq_limits": freq_limits,
        "structFile": "/app/groupicatv4.0b/icatb/src/icatb_templates/ch2bet.nii",
        "t_threshold": t_threshold,
        "image_values": image_values,
        "threshdesc": threshdesc,
        "p_threshold": display_p_threshold,
        "display_connectogram": 1,
    }
    return _run_with_logging(mc, "GIFT aggregate stats", site_logger)
