# NeuroFLAME Computation: MANCOVA (nfc-mancova)

Federated MANCOVA (Multivariate Analysis of Covariance) with Group ICA for multi-site neuroimaging analysis. A NeuroFLAME port of [COINSTAC MANCOVA](https://github.com/trendscenter/coinstac-mancova).

## Overview

**nfc-mancova** enables multi-site MANCOVA analysis without sharing raw neuroimaging data. Each site runs Group ICA locally using the GIFT toolbox; statistical results are then aggregated at the central node to produce global multivariate and univariate analyses across all sites.

The pipeline runs in three phases:

1. **Edge Node** — Group ICA preprocessing and local univariate statistical tests at each site
2. **Central Node** — Covariate aggregation, global univariate pooling, and multivariate MANCOVA
3. **Result Distribution** — Global results returned to all sites

## Architecture

| Component | Location | Role |
|---|---|---|
| Controller | `app/code/controller/controller.py` | Orchestrates the federated workflow; broadcasts tasks and coordinates aggregation |
| Executor | `app/code/executor/executor.py` | Routes NVFlare tasks to edge computation logic |
| Edge computation | `app/code/executor/mancova_edge_computation.py` | Runs Group ICA and local univariate tests at each site |
| Aggregator | `app/code/aggregator/aggregator.py` | Accepts site results and triggers central aggregation |
| Central aggregation | `app/code/aggregator/mancova_central_aggregation.py` | Pools covariates and runs global MANCOVA |
| GIFT wrappers | `app/code/_utils/gift_wrappers.py` | Thin NiPype wrappers around GIFT Group ICA and MANCOVA |
| Data transfer | `app/code/_utils/data_transfer.py` | Serialises binary files (`.mat`) to/from bytes for transfer through NVFlare Shareables |

## Quick Start

### Building

```bash
# Production image
docker build -f Dockerfile-prod -t nfc-mancova:latest .

# Development image
docker build -f Dockerfile-dev -t nfc-mancova-dev:latest .
```

### Local Development

```bash
bash dockerRun.sh
```

### Running a Federated Computation

Refer to the NeuroFLAME provisioning and deployment documentation for running computations across federated sites.

## MATLAB / GIFT Environment

The computation requires the GIFT standalone toolbox and MATLAB Runtime (MCR).

| Environment Variable | Description | Default |
|---|---|---|
| `GIFT_HOME` | Root of the GIFT toolbox install | `/app/groupicatv4.0b` |
| `MCRROOT` / `MATLAB_RUNTIME` | Root of the MATLAB Runtime installation | `/usr/local/MATLAB/MATLAB_Runtime/v91` |
| `MATLAB_CMD` | Command used by NiPype to launch the GIFT standalone runtime | `$GIFT_HOME/GroupICATv4.0b_standalone/run_groupica.sh $MCRROOT/` |

To install MATLAB Runtime before building the image:

```bash
./download_mcr.sh
```

If the `groupicatv4.0b` toolbox is available locally, place it at the repo root so it can be copied into the container at build time.

## Input Data

Each site's data directory must contain:

- **NIfTI files** (`*.nii` or `*.nii.gz`) — one per subject at the top level of the data directory
- **`*covariates.csv`** — one row per subject (in the same order as sorted NIfTI filenames), one column per covariate
- **`*covariate_keys.csv`** *(optional)* — two columns: `name` and `type` (`"continuous"` or `"categorical"`); all covariates default to continuous if omitted

Standard fMRI preprocessing (realignment, normalisation to MNI space, smoothing) must be applied before running this computation.

## Configuration

Computation parameters are passed via `parameters.json` (path set by `PARAMETERS_FILE_PATH` env var, or `test_data/server/parameters.json` in simulation). See [display_notes.md](display_notes.md) for a full parameter reference and example settings.

### Minimal Example

```json
{
    "scica_template": "NeuroMark.nii",
    "mask": "default&icv",
    "TR": 2,
    "num_components": 53,
    "features": ["spatial", "spectra", "fnc"],
    "run_univariate_tests": true,
    "univariate_test_list": [
        {"regression": {"name": ["age", "diagnosis"]}}
    ],
    "run_mancova": true,
    "site_id_name_map": {
        "site-1": "Site A",
        "site-2": "Site B"
    }
}
```

## File Structure

```
nfc-mancova/
├── app/
│   ├── code/
│   │   ├── _utils/
│   │   │   ├── data_transfer.py       # Binary file serialisation helpers
│   │   │   ├── gift_wrappers.py       # NiPype/GIFT interface wrappers
│   │   │   └── utils.py               # NVFlare path utilities
│   │   ├── controller/
│   │   │   └── controller.py
│   │   ├── executor/
│   │   │   ├── executor.py
│   │   │   └── mancova_edge_computation.py
│   │   └── aggregator/
│   │       ├── aggregator.py
│   │       └── mancova_central_aggregation.py
│   └── config/
│       ├── config_fed_server.json
│       └── config_fed_client.json
├── system/
│   ├── entry_central.py
│   ├── entry_edge.py
│   ├── entry_provision.py
│   └── provision/
├── test_data/
│   └── server/
│       └── parameters.json
├── display_notes.md
├── requirements.txt
├── Dockerfile-prod
├── Dockerfile-dev
├── dockerRun.sh
└── download_mcr.sh
```

## References

- Original COINSTAC MANCOVA: https://github.com/trendscenter/coinstac-mancova
- GIFT Toolbox: https://icatb.sourceforge.io/
- NeuroFLAME: https://github.com/NeuroFlame
