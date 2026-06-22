import json
import os

from nvflare.apis.dxo import DXO, DataKind, from_shareable
from nvflare.apis.executor import Executor
from nvflare.apis.fl_constant import FLContextKey
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import ReservedHeaderKey, Shareable
from nvflare.apis.signal import Signal

from _utils.logger import NvFlareLogger
from _utils.types import ConfigDTO
from _utils.utils import get_data_directory_path, get_output_directory_path
from .mancova_edge_computation import run_edge_mancova, query_scan_length


TASK_NAME_RUN_MANCOVA = "RUN_MANCOVA"
TASK_NAME_ACCEPT_GLOBAL_RESULTS = "ACCEPT_GLOBAL_RESULTS"
TASK_NAME_QUERY_SCAN_LENGTH = "QUERY_SCAN_LENGTH"


class MyExecutor(Executor):
    def execute(
        self,
        task_name: str,
        shareable: Shareable,
        fl_ctx: FLContext,
        abort_signal: Signal,
    ) -> Shareable:

        site_name = fl_ctx.get_prop(FLContextKey.CLIENT_NAME, "unknown")
        output_dir = get_output_directory_path(fl_ctx)
        computation_parameters = _get_computation_parameters(fl_ctx)
        log_level = computation_parameters.get("log_level", "info")

        site_logger = NvFlareLogger(f"{site_name}.log", output_dir, log_level)
        site_logger.info("Task:", task_name)

        try:
            if task_name == TASK_NAME_QUERY_SCAN_LENGTH:
                config = ConfigDTO(
                    site_name=site_name,
                    data_dir=get_data_directory_path(fl_ctx),
                    output_dir=output_dir,
                    parameters=computation_parameters,
                    logger=site_logger,
                )
                length = query_scan_length(config)
                result = Shareable()
                result["scan_length"] = length
                return result

            if task_name == TASK_NAME_RUN_MANCOVA:
                config = ConfigDTO(
                    site_name=site_name,
                    data_dir=get_data_directory_path(fl_ctx),
                    output_dir=output_dir,
                    parameters=computation_parameters,
                    logger=site_logger,
                )
                local_results = run_edge_mancova(config)

                # Binary stats files go into a DXO; everything else stays in the Shareable.
                stats_files = local_results.pop("univariate_stat_info_files", {})
                dxo = DXO(data_kind=DataKind.COLLECTION, data=stats_files)

                outgoing = Shareable()
                outgoing["edge_results"] = {
                    k: v for k, v in local_results.items()
                    if k not in ("covariates",)  # drop large non-essential dicts
                }
                _merge_dxo(outgoing, dxo)

                _save_json(
                    {k: v for k, v in local_results.items()
                     if not isinstance(v, (bytes, dict)) or k != "covariates_df"},
                    "edge_mancova_results.json",
                    output_dir,
                    site_logger,
                )
                return outgoing

            if task_name == TASK_NAME_ACCEPT_GLOBAL_RESULTS:
                try:
                    dxo = from_shareable(shareable)
                    # dxo.data = {rel_path: bytes} — full aggregation output directory
                    agg_dir = os.path.join(output_dir, "aggregation")
                    os.makedirs(agg_dir, exist_ok=True)
                    for rel_path, blob in dxo.data.items():
                        dest = os.path.join(agg_dir, rel_path)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(dest, "wb") as f:
                            f.write(blob)
                    site_logger.info(f"Unpacked {len(dxo.data)} aggregation files to {agg_dir}")
                except Exception as dxo_err:
                    site_logger.warning("DXO unpack failed, falling back to report_html:", str(dxo_err))

                # Always write the HTML report string when present (backward compat + fallback).
                global_results = shareable.get("global_results", {})
                report_html = global_results.get("report_html")
                if report_html:
                    with open(os.path.join(output_dir, "index.html"), "w") as f:
                        f.write(report_html)
                    site_logger.info("Report written to", output_dir + "/index.html")

                _save_json(
                    {k: v for k, v in global_results.items() if k != "report_html"},
                    "global_mancova_results.json",
                    output_dir,
                    site_logger,
                )
                return Shareable()

            site_logger.error("Unknown task:", task_name)
            raise ValueError(f"Unknown task: {task_name}")

        finally:
            site_logger.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_computation_parameters(fl_ctx: FLContext) -> dict:
    return fl_ctx.get_peer_context().get_prop("COMPUTATION_PARAMETERS", {})


def _merge_dxo(outgoing: Shareable, dxo: DXO) -> None:
    """Inline a DXO into an existing Shareable so from_shareable() can reconstruct it."""
    dxo_spl = dxo.to_shareable()
    header_map = dxo_spl.get(ReservedHeaderKey.HEADERS, {})
    for hdr_key, hdr_val in header_map.items():
        outgoing.set_header(hdr_key, hdr_val)
    for key, val in dxo_spl.items():
        if key != ReservedHeaderKey.HEADERS:
            outgoing[key] = val


def _save_json(data: dict, filename: str, output_dir: str, logger: NvFlareLogger) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=4, default=str)
        logger.info("Saved", path)
    except Exception as e:
        raise RuntimeError(f"Failed to save {filename}: {e}")
