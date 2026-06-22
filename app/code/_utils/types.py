from typing import Any, Dict, NamedTuple

from _utils.logger import NvFlareLogger


class ConfigDTO(NamedTuple):
    """Typed configuration passed through every edge and aggregator call.

    Replaces the separate data_dir/output_dir/parameters/logger arguments that
    were previously threaded individually through the computation stack.
    """
    site_name: str
    data_dir: str
    output_dir: str
    parameters: Dict[str, Any]
    logger: NvFlareLogger
