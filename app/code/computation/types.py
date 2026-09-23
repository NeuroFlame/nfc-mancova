"""Define values exchanged by the federated MANCOVA computation."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class SiteInputs:
    """Validated site-local files discovered in the data directory."""

    nifti_files: List[str]
    covariates_file: Optional[str] = None
    covariate_types_file: Optional[str] = None


@dataclass
class SiteScanInfo:
    """Native scan length reported by a site for common-timepoint negotiation."""

    scan_length: int


@dataclass
class TimepointPlan:
    """Globally resolved number of timepoints every site truncates to (0 = off)."""

    common_timepoints: int


@dataclass
class SiteMancovaResult:
    """Per-site summary sent to the aggregator after local GICA/MANCOVA.

    ``stat_files`` maps each univariate test key to ``{filename: ArtifactRef}``
    for the GIFT ``*_mancovan_stats_info.mat`` files; it is typed as ``Any`` so
    the framework passes materialized artifact references through untouched.
    """

    status: str
    num_subjects: int
    num_covariates: int
    covariates_df: pd.DataFrame
    covariate_types: Dict[str, str]
    features: List[str]
    output_directory: str
    stat_files: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class GlobalResults:
    """Aggregated results broadcast back to every site.

    ``aggregation_archive`` is an ArtifactRef to a gzipped tarball of the
    central aggregation directory, including the HTML report.
    """

    summary: Dict[str, Any]
    aggregation_archive: Any
