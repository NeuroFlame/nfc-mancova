"""Declare the federated GICA + MANCOVA computation workflow."""

from framework import (
    ComputationSpec,
    local_step,
    remote_step,
    site_output_step,
    stepped_workflow,
)

from .inputs import load_site_inputs
from .local_math import report_scan_length, run_site_mancova
from .remote_math import (
    aggregate_mancova,
    resolve_common_timepoints,
    write_site_outputs,
)

SPEC = ComputationSpec(
    workflow=stepped_workflow(
        local_step(fn=report_scan_length, input_fn=load_site_inputs),
        remote_step(fn=resolve_common_timepoints),
        local_step(fn=run_site_mancova),
        remote_step(fn=aggregate_mancova),
        site_output_step(fn=write_site_outputs),
    ),
)
