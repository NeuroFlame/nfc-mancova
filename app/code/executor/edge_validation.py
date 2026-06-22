import glob
import os
from typing import List

from _utils.types import ConfigDTO


def validate_edge_inputs(config: ConfigDTO) -> None:
    """Raise if required edge inputs are missing or logically inconsistent."""
    params = config.parameters

    if params.get("skip_gica", False):
        gica_input_dir = params.get("gica_input_dir", ".")
        base_dir = (
            gica_input_dir
            if os.path.isabs(gica_input_dir)
            else os.path.join(config.data_dir, gica_input_dir)
        )
        if not os.path.exists(base_dir):
            raise FileNotFoundError(f"GICA input directory not found: {base_dir}")
        config.logger.info("Validated GICA input dir:", base_dir)

    if params.get("run_univariate_tests", False) and not params.get("univariate_test_list"):
        raise ValueError("run_univariate_tests=True but univariate_test_list is empty")

    features = params.get("features", [])
    if not features:
        config.logger.warning("No features specified; MANCOVA may produce limited results")

    config.logger.info("Edge input validation passed")


def validate_ica_parameters(base_dir: str, config: ConfigDTO) -> List[str]:
    """Find ICA parameter files under base_dir. Raises FileNotFoundError if none found."""
    ica_parameters = sorted([
        p for p in glob.glob(
            os.path.join(base_dir, "**", "*parameter_info.mat"), recursive=True
        )
        if os.path.exists(p)
    ])
    if not ica_parameters:
        raise FileNotFoundError(f"No ICA parameter files found in {base_dir}")
    config.logger.info(f"Found {len(ica_parameters)} ICA parameter file(s) in {base_dir}")
    return ica_parameters
