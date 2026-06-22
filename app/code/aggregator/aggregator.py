import glob
import os
from typing import Any, Dict, Optional

from nvflare.apis.dxo import DXO, DataKind, from_shareable
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_constant import ReservedKey
from nvflare.apis.shareable import Shareable
from nvflare.app_common.abstract.aggregator import Aggregator

from _utils.logger import NvFlareLogger
from _utils.utils import get_aggregation_directory_path
from .mancova_central_aggregation import aggregate_mancova_results


class MyAggregator(Aggregator):

    def __init__(self):
        super().__init__()
        self.site_results: Dict[str, Dict[str, Any]] = {}
        self._logger: Optional[NvFlareLogger] = None
        self._aggregation_dir: str = ""

    # ------------------------------------------------------------------
    # Lazy logger — aggregation_dir is only known on first accept() call
    # ------------------------------------------------------------------
    def _get_logger(self, fl_ctx: FLContext) -> NvFlareLogger:
        if self._logger is None:
            self._aggregation_dir = get_aggregation_directory_path(fl_ctx)
            computation_params = fl_ctx.get_prop("COMPUTATION_PARAMETERS", {})
            log_level = computation_params.get("log_level", "info")
            self._logger = NvFlareLogger("aggregator.log", self._aggregation_dir, log_level)
        return self._logger

    # ------------------------------------------------------------------
    # accept — called once per site when its RUN_MANCOVA result arrives
    # ------------------------------------------------------------------
    def accept(self, site_result: Shareable, fl_ctx: FLContext) -> bool:
        logger = self._get_logger(fl_ctx)

        site_id = site_result.get_peer_prop(key=ReservedKey.IDENTITY_NAME, default=None)
        computation_parameters = fl_ctx.get_prop(key="COMPUTATION_PARAMETERS", default={})
        site_id_name_map = computation_parameters.get("site_id_name_map", {})
        site_name = site_id_name_map.get(site_id, site_id)

        logger.info("Accepting result from site:", site_name)

        # ---- JSON metadata ----
        site_metadata = site_result.get("edge_results", {})

        # ---- Binary stats files via DXO ----
        # Writes {test_key}/{filename}.mat under aggregation_dir/site_name/
        try:
            dxo = from_shareable(site_result)
            site_dir = os.path.join(self._aggregation_dir, site_name)
            for test_key, file_dict in dxo.data.items():
                test_dir = os.path.join(site_dir, test_key)
                os.makedirs(test_dir, exist_ok=True)
                for filename, blob in file_dict.items():
                    with open(os.path.join(test_dir, filename), "wb") as f:
                        f.write(blob)
            logger.info(f"Wrote DXO stats files for site {site_name}")
        except Exception as e:
            logger.warning("DXO extraction failed for site", site_name, "-", str(e))

        self.site_results[site_name] = site_metadata
        return True

    # ------------------------------------------------------------------
    # aggregate — called after all sites have submitted
    # ------------------------------------------------------------------
    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        logger = self._get_logger(fl_ctx)
        aggregation_dir = self._aggregation_dir
        computation_parameters = fl_ctx.get_prop("COMPUTATION_PARAMETERS", {})

        # Preserve insertion order defined by site_id_name_map
        site_id_name_map = computation_parameters.get("site_id_name_map", {})
        ordered_names = list(site_id_name_map.values())
        site_names = [n for n in ordered_names if n in self.site_results]
        site_names += [k for k in self.site_results if k not in ordered_names]
        site_results = [self.site_results[n] for n in site_names]

        # Collect stats files written to disk by accept()
        stat_info_files = sorted(glob.glob(
            os.path.join(aggregation_dir, "**", "*mancovan_stats_info.mat"), recursive=True
        ))
        logger.info(f"Collected {len(stat_info_files)} stats file(s) for aggregation")

        global_results = aggregate_mancova_results(
            site_results=site_results,
            site_names=site_names,
            stat_info_files=stat_info_files,
            parameters=computation_parameters,
            aggregation_dir=aggregation_dir,
            logger=logger,
        )

        # Package the full aggregation directory for delivery back to clients
        payload = _package_dir(aggregation_dir, logger)
        logger.info(f"Packaged {len(payload)} files for client delivery")

        dxo = DXO(data_kind=DataKind.COLLECTION, data=payload)
        outgoing = dxo.to_shareable()
        # Strip report_html binary from global_results to keep Shareable lean;
        # the full HTML file is already inside the DXO payload.
        outgoing["global_results"] = {
            k: v for k, v in global_results.items() if k != "report_html"
        }
        # Keep report_html for the backward-compat fallback in the executor.
        outgoing["global_results"]["report_html"] = global_results.get("report_html", "")

        logger.close()
        return outgoing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _package_dir(source_dir: str, logger: NvFlareLogger) -> Dict[str, bytes]:
    """Read every file under source_dir and return {rel_path: bytes}."""
    payload: Dict[str, bytes] = {}
    for root, _, files in os.walk(source_dir):
        for fname in files:
            if fname.startswith("."):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, source_dir)
            try:
                with open(full_path, "rb") as f:
                    payload[rel_path] = f.read()
            except Exception as e:
                logger.warning("Could not read file for packaging:", rel_path, "-", str(e))
    return payload
