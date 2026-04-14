from typing import Dict, Any
from nvflare.apis.shareable import Shareable
from nvflare.apis.fl_context import FLContext
from nvflare.app_common.abstract.aggregator import Aggregator
from nvflare.apis.fl_constant import ReservedKey
from .get_global_average import get_global_average

class MyAggregator(Aggregator):
    """
    SrrAggregator handles the aggregation of results from multiple client sites.
    It stores individual site results and computes a global result based on the aggregation logic.

    This class can be customized if specific aggregation logic is needed.
    """

    def __init__(self):
        """
        Initializes the SrrAggregator with a dictionary to store results from multiple sites.
        """
        super().__init__()
        # Store results as a dictionary
        self.site_results: Dict[str, Dict[str, Any]] = {}

    def accept(self, site_result: Shareable, fl_ctx: FLContext) -> bool:
        """
        Accepts a result from a site and stores it for later aggregation.

        This method is called when a client site sends a result. Developers can override this 
        if they need to handle or validate the results differently before storing them.

        :param site_result: The result received from the client site.
        :param fl_ctx: The federated learning context for this run.
        :return: Boolean indicating if the result was successfully accepted.
        """
        site_id = site_result.get_peer_prop(
            key=ReservedKey.IDENTITY_NAME, default=None)
        computation_parameters = fl_ctx.get_prop(key="COMPUTATION_PARAMETERS", default={})
        site_id_name_map = computation_parameters.get("site_id_name_map", {})
        site_name = site_id_name_map.get(site_id, site_id)

        # Store the result for the site using its identity name as the key
        self.site_results[site_name] = site_result["result"]
        return True

    def aggregate(self, fl_ctx: FLContext) -> Shareable:
        """
        Aggregates the results from all accepted client sites and produces a global result.

        This is where the global aggregation logic happens. Developers can override this
        if they need to change how the results from each site are combined.

        :param fl_ctx: The federated learning context for this run.
        :return: A Shareable object containing the aggregated global result.
        """

        # Retrieve the decimal places from the computation parameters
        computation_parameters = fl_ctx.get_prop("COMPUTATION_PARAMETERS")
        decimal_places = computation_parameters.get("decimal_places", 2)

        # Transform site_results into the format expected by get_global_average
        items = [
            {"average": result["average"], "count": result["count"]}
            for result in self.site_results.values()
            if "average" in result and "count" in result
        ]

        # Compute the global average using the helper function
        global_average = get_global_average(items, decimal_places)

        # Create a new Shareable to store the aggregated result
        outgoing_shareable = Shareable()
        outgoing_shareable["global_average"] = global_average
        return outgoing_shareable
