"""Load and validate site-local inputs for federated MANCOVA."""

import glob
import os
from typing import Any, Dict, List

from .types import SiteInputs


def resolve_gica_input_dir(gica_input_dir: str, data_dir: str) -> str:
    """Resolve a pre-computed GICA directory relative to the site data directory."""
    if os.path.isabs(gica_input_dir):
        return gica_input_dir
    return os.path.join(data_dir, gica_input_dir)


def find_nifti_files(data_dir: str) -> List[str]:
    """Return the site's NIfTI inputs in a stable order."""
    return sorted(
        glob.glob(os.path.join(data_dir, "*.nii.gz"))
        + glob.glob(os.path.join(data_dir, "*.nii"))
    )


def validate_parameters(parameters: Dict[str, Any], data_dir: str, logger) -> None:
    """Raise if required inputs are missing or logically inconsistent."""
    if parameters.get("skip_gica", False):
        gica_input_dir = parameters.get("gica_input_dir", "")
        if not gica_input_dir:
            raise ValueError(
                "skip_gica is true but gica_input_dir is not set. "
                "Provide the path to the pre-existing GIFT ICA output directory "
                '(relative to the site data directory, e.g. "coinstac-gica").'
            )
        base_dir = resolve_gica_input_dir(gica_input_dir, data_dir)
        if not os.path.isdir(base_dir):
            raise FileNotFoundError(f"GICA input directory not found: {base_dir}")
        logger.info("Validated GICA input dir: %s", base_dir)

    if parameters.get("run_univariate_tests", False) and not parameters.get(
        "univariate_test_list"
    ):
        raise ValueError("run_univariate_tests=True but univariate_test_list is empty")

    if not parameters.get("features", []):
        logger.warning("No features specified; MANCOVA may produce limited results")


def load_site_inputs(data_dir: str, parameters: Dict[str, Any], logger) -> SiteInputs:
    """Validate parameters and discover NIfTI and covariate files for this site."""
    validate_parameters(parameters, data_dir, logger)

    nifti_files = find_nifti_files(data_dir)
    max_subjects = parameters.get("max_subjects")
    if max_subjects:
        nifti_files = nifti_files[:max_subjects]
    logger.info(
        "Found %d NIfTI files (max_subjects=%s)", len(nifti_files), max_subjects
    )

    covariate_files = glob.glob(os.path.join(data_dir, "*covariates.csv"))
    covariate_type_files = glob.glob(os.path.join(data_dir, "*covariate_keys.csv"))

    logger.info("Edge input validation passed")
    return SiteInputs(
        nifti_files=nifti_files,
        covariates_file=covariate_files[0] if covariate_files else None,
        covariate_types_file=covariate_type_files[0] if covariate_type_files else None,
    )


def find_ica_parameter_files(base_dir: str, logger) -> List[str]:
    """Find ICA parameter files under base_dir, raising if none exist."""
    ica_parameters = sorted(
        glob.glob(os.path.join(base_dir, "**", "*parameter_info.mat"), recursive=True)
    )
    if not ica_parameters:
        raise FileNotFoundError(f"No ICA parameter files found in {base_dir}")
    logger.info("Found %d ICA parameter file(s) in %s", len(ica_parameters), base_dir)
    return ica_parameters
