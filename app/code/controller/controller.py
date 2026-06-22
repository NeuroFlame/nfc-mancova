import json
from typing import Callable, List

from nvflare.apis.impl.controller import Controller, Task, ClientTask
from nvflare.apis.fl_context import FLContext
from nvflare.apis.signal import Signal
from nvflare.apis.shareable import Shareable

from _utils.logger import NvFlareLogger
from _utils.utils import get_aggregation_directory_path, get_parameters_file_path


TASK_NAME_RUN_MANCOVA = "RUN_MANCOVA"
TASK_NAME_ACCEPT_GLOBAL_RESULTS = "ACCEPT_GLOBAL_RESULTS"
TASK_NAME_QUERY_SCAN_LENGTH = "QUERY_SCAN_LENGTH"
AGGREGATOR_ID = "aggregator"


class MyController(Controller):
    """
    Controller for federated MANCOVA computation.

    Orchestrates the distributed MANCOVA workflow:
    1. Broadcasts Group ICA task to all sites
    2. Collects and aggregates results at central node
    3. Performs global MANCOVA analysis
    4. Distributes results back to sites
    """

    def __init__(
        self,
        min_clients: int = 2,
        wait_time_after_min_received: int = 10,
        task_timeout: int = 0,
    ):
        super().__init__()
        self._task_timeout = task_timeout
        self._min_clients = min_clients
        self._wait_time_after_min_received = wait_time_after_min_received
        self._logger: NvFlareLogger = None

    def start_controller(self, fl_ctx: FLContext) -> None:
        """Initialize the controller and load computation parameters."""
        self.aggregator = self._engine.get_component(AGGREGATOR_ID)
        self._load_and_set_computation_parameters(fl_ctx)
        output_dir = get_aggregation_directory_path(fl_ctx)
        params = fl_ctx.get_prop("COMPUTATION_PARAMETERS", {})
        log_level = params.get("log_level", "info")
        self._logger = NvFlareLogger("controller.log", output_dir, log_level)
        self._logger.info("Controller started")

    def control_flow(self, abort_signal: Signal, fl_ctx: FLContext) -> None:
        """
        Main federated computation workflow for MANCOVA.

        1. (Optional) Negotiate common_timepoints across sites
        2. Broadcast Group ICA task to sites
        3. Collect local results via aggregator
        4. Perform central MANCOVA analysis
        5. Return global results to sites
        """
        params = fl_ctx.get_prop("COMPUTATION_PARAMETERS", {})

        # Step 0 (optional): If common_timepoints=true, query each site for its
        # native scan length and resolve to the global minimum before proceeding.
        if isinstance(params.get("common_timepoints"), bool) and params["common_timepoints"]:
            self._negotiate_common_timepoints(params, fl_ctx, abort_signal)

        self._logger.info("Broadcasting RUN_MANCOVA to all sites")
        self._broadcast_task(
            task_name=TASK_NAME_RUN_MANCOVA,
            data=Shareable(),
            result_cb=self._accept_site_mancova_result,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

        self._logger.info("Aggregating results")
        aggregate_result = self.aggregator.aggregate(fl_ctx)

        self._logger.info("Broadcasting ACCEPT_GLOBAL_RESULTS to all sites")
        self._broadcast_task(
            task_name=TASK_NAME_ACCEPT_GLOBAL_RESULTS,
            data=aggregate_result,
            result_cb=None,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

    def _negotiate_common_timepoints(
        self, params: dict, fl_ctx: FLContext, abort_signal: Signal
    ) -> None:
        """Query all sites for their scan length and set common_timepoints to the minimum."""
        scan_lengths: List[int] = []

        def _collect(client_task: ClientTask, fl_ctx: FLContext) -> bool:
            length = client_task.result.get("scan_length", 0)
            if length:
                scan_lengths.append(int(length))
            return True

        self._logger.info("Broadcasting QUERY_SCAN_LENGTH to all sites")
        self._broadcast_task(
            task_name=TASK_NAME_QUERY_SCAN_LENGTH,
            data=Shareable(),
            result_cb=_collect,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

        if scan_lengths:
            resolved = min(scan_lengths)
            self._logger.info(
                f"common_timepoints negotiated: site lengths={scan_lengths} → min={resolved}"
            )
            params["common_timepoints"] = resolved
        else:
            self._logger.warning(
                "common_timepoints=true but no scan lengths received; disabling truncation"
            )
            params["common_timepoints"] = 0

        fl_ctx.set_prop("COMPUTATION_PARAMETERS", params, private=False, sticky=True)

    def _accept_site_mancova_result(self, client_task: ClientTask, fl_ctx: FLContext) -> bool:
        """Callback to process each site's result and send to aggregator."""
        return self.aggregator.accept(client_task.result, fl_ctx)

    def _broadcast_task(
        self,
        task_name: str,
        data: Shareable,
        result_cb: Callable[[ClientTask, FLContext], bool],
        fl_ctx: FLContext,
        abort_signal: Signal,
    ) -> None:
        """Broadcast a task to all client sites."""
        self.broadcast_and_wait(
            task=Task(
                name=task_name,
                data=data,
                props={},
                timeout=self._task_timeout,
                result_received_cb=result_cb,
            ),
            min_responses=self._min_clients,
            wait_time_after_min_received=self._wait_time_after_min_received,
            fl_ctx=fl_ctx,
            abort_signal=abort_signal,
        )

    def _load_and_set_computation_parameters(self, fl_ctx: FLContext) -> None:
        """Load and distribute computation parameters."""
        with open(get_parameters_file_path(fl_ctx), 'r') as f:
            fl_ctx.set_prop(
                key="COMPUTATION_PARAMETERS",
                value=json.load(f),
                private=False,
                sticky=True,
            )

    def process_result_of_unknown_task(self, task: Task, fl_ctx: FLContext) -> None:
        """Handle unknown task results."""
        pass

    def stop_controller(self, fl_ctx: FLContext) -> None:
        """Cleanup when controller stops."""
        if self._logger is not None:
            self._logger.info("Controller stopped")
            self._logger.close()
