### Overview

This document outlines the process NeuroFLAME uses to provision federated networks for their respective studies. It details the inputs required during the provisioning step and specifies the expected outputs.

### Provisioning

The provisioning step creates "runKits," which are folders that each site will use to launch, configure, and connect to the federated network associated with a study run. Once the computation container completes the provisioning step, these runKits will be distributed by NeuroFLAME to the respective sites and the central node. Each runKit will be mounted to the computation containers for both the site and the central node involved in the run.

### Input

The input will be a JSON file containing the following fields:

```json
{
    "users": [
        {"id": "user-id-1", "name": "Site A"},
        {"id": "user-id-2", "name": "Site B"}
    ],
    "computation_parameters": "string containing computation parameters",
    "fed_learn_port": 1234,
    "admin_port": 5678,
    "host_identifier": "IP or hostname"
}
```

- **users**: A list of objects with `id` (unique user ID) and `name` (human-readable site name) for each active member in the run. The `name` is used to label sites in result reports. If `users` is not provided, a flat `user_ids` list of IDs will be accepted as a fallback (site names will display as raw IDs).
- **computation_parameters**: A JSON object set by the consortium leader in the study configuration.
- **host_identifier**: The IP address or hostname where the central node can be reached.
- **fed_learn_port**: The port clients will use to connect to the central node.
- **admin_port**: The port where the admin component will be hosted.

provision_input.json can be found at `<path to provision_input.json>`

### Output

The output will be a set of files named for the userId of each site and an additional file named `centralNode`. These will be distributed to their respective sites.

