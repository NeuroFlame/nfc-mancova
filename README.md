# NeuroFLAME Computation: MANCOVA (nfc-mancova)

Federated MANCOVA (Multivariate Analysis of Covariance) with Group ICA for multi-site neuroimaging analysis. A NeuroFLAME port of [COINSTAC MANCOVA](https://github.com/trendscenter/coinstac-mancova).

## Overview

**nfc-mancova** enables multi-site MANCOVA analysis without sharing raw neuroimaging data. Each site runs Group ICA locally using the GIFT toolbox; statistical results are then aggregated at the central node to produce global multivariate and univariate analyses across all sites.

The pipeline runs in three phases:

1. **Edge Node** — Group ICA preprocessing and local univariate statistical tests at each site
2. **Central Node** — Covariate aggregation, global univariate pooling, and multivariate MANCOVA
3. **Result Distribution** — Global results returned to all sites

## Architecture

This computation is authored against [computation-nvflare-boilerplate](https://github.com/NeuroFlame/computation-nvflare-boilerplate).
Only `app/code/computation/` is computation-specific; `app/code/framework/`,
`app/code/runtime/`, `app/config/`, `system/`, and the tooling scripts are
boilerplate-managed and are updated with `scripts/migrate_computation.py`
from the boilerplate repository.

The shared code includes the provisioned participant-count fix (each task waits
for every provisioned participant), native-temporary-filesystem artifact
staging for Docker Desktop compatibility, and the run-scoped cache API.
The computation-specific MATLAB/GIFT Dockerfile sections and dependencies are
preserved when updating shared code; do not overwrite those Dockerfiles with
the generic boilerplate versions.

### Reusing files across iterations

Author functions can request `cache_dir` on either sites or central. Each
participant has a separate cache, stable across iterations within one run and
removed at run shutdown. `cache_file()` validates a filename and returns its
path; authors choose how to read and write the contents:

```python
from framework import cache_file


def compute_local(inputs, *, cache_dir):
    path = cache_file("local-statistics.npy", cache_dir=cache_dir)
    # Write/read this path with the appropriate library for your file format.
    ...
```

Caching does not transfer files. To send a cached file, copy it into the current
step's iteration-specific `artifact_dir` and return that copy with `artifact()`.
See the boilerplate's
[author API guide](https://github.com/NeuroFlame/computation-nvflare-boilerplate/blob/main/docs/computation_development/core_components_and_workflow.md)
and [artifact guide](https://github.com/NeuroFlame/computation-nvflare-boilerplate/blob/main/docs/computation_development/artifacts.md).

The workflow is declared in `app/code/computation/spec.py`:

| Step | Runs on | Function | Purpose |
|---|---|---|---|
| `local_step` | sites | `inputs.load_site_inputs` → `local_math.report_scan_length` | Validate parameters, discover NIfTI/covariate files, report scan length when `common_timepoints` is `true` |
| `remote_step` | central | `remote_math.resolve_common_timepoints` | Resolve the shared timepoint count (minimum across sites) |
| `local_step` | sites | `local_math.run_site_mancova` | Run GIFT Group ICA and local univariate MANCOVA tests; send `*_mancovan_stats_info.mat` files as artifacts |
| `remote_step` | central | `remote_math.aggregate_mancova` | Pool covariates, run GIFT aggregate stats, build the HTML report, and send the aggregation directory back as an artifact |
| `site_output_step` | sites | `remote_math.write_site_outputs` | Unpack the aggregation directory and write `index.html` and `global_mancova_results.json` |

| Module | Role |
|---|---|
| `computation/types.py` | Dataclasses exchanged between steps |
| `computation/gift.py` | Thin NiPype wrappers around GIFT Group ICA and MANCOVA |
| `computation/report.py` | Self-contained HTML report |

## Running this computation

Run the NVFlare simulator in Docker against `test_data/`:

```bash
./run_local_simulation.sh site1,site2            # builds Dockerfile-dev, then simulates
./run_local_simulation.sh site1,site2 --no-build # reuse the image after code-only changes
```

Site results land in `test_output/simulate_job/<site>/` and central results in
`test_output/simulate_job/server/`.

Lint, format-check, compile, and unit tests:

```bash
make check
```

For an interactive shell in the dev image, use `./dockerRun.sh`; `./dockerRunVault.sh`
mounts the real GICA vault data (see the script header).

Publishing production images uses `./dockerPush.sh` (a wrapper for
`scripts/publish_computation_image.py`) with the image coordinates in
`.neuroflame.json`.

## MATLAB / GIFT Environment

The computation requires the GIFT standalone toolbox and MATLAB Runtime (MCR).

| Environment Variable | Description | Default |
|---|---|---|
| `GIFT_HOME` | Root of the GIFT toolbox install | `/app/groupicatv4.0b` |
| `MCRROOT` / `MATLAB_RUNTIME` | Root of the MATLAB Runtime installation | `/usr/local/MATLAB/MATLAB_Runtime/v91` |
| `MATLAB_CMD` | Command used by NiPype to launch the GIFT standalone runtime | `$GIFT_HOME/GroupICATv4.0b_standalone/run_groupica.sh $MCRROOT/` |

Both Dockerfiles install MATLAB Runtime R2016b and copy the GIFT toolbox
from `groupicatv4.0b/` at the repo root (not committed; see `.gitignore`), so
that directory must exist before building.

### Smaller runtime images

Both Dockerfiles use an installation stage followed by a slim Python 3.11
runtime stage. The final image keeps the full MATLAB R2016b runtime and the
selected GIFT standalone, Python packages, toolbox support, and plotting fonts.
Build tools, installer scratch files, package caches, and the duplicate GIFT
standalone distribution are not copied into the final image. The final image
does not retain the install-stage MCR extraction cache, so the first GIFT call
extracts its cache at runtime.

The production candidate measured 3.34 GB versus 5.02 GB for the full image
(Docker uncompressed sizes). R2016b uses binary file manifests, unlike the JSON
manifests used by the VBM R2022b product selector; MATLAB product/GPU pruning is
not applied here.

`scripts/runtime_smoke.m` exercises deterministic MATLAB matrix calculations,
GIFT NIfTI reads, and PNG rendering through the standalone executable. Mount
a writable scratch directory at `/checks` and the script at
`/smoke/runtime_smoke.m`, then invoke:

```sh
/app/groupicatv4.0b/GroupICATv4.0b_standalone/run_groupica.sh \
  /usr/local/MATLAB/MATLAB_Runtime/v91/ /smoke/runtime_smoke.m
```

Compare the saved MAT variables (excluding creation-header timestamps) and PNG
image-data chunks between full and slim images. MATLAB embeds creation times
in PNG metadata, so whole-file hashes differ even for identical image data.
The baseline and slim smoke runs matched every saved numerical variable and
the PNG image-data chunks exactly. This is a runtime compatibility smoke
check, not a full federated GICA/MANCOVA numerical regression. Publish images
through `bash dockerPush.sh`; use `--local` for a labeled local-only build.

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
    "run_mancova": true
}
```

## File Structure

```
nfc-mancova/
├── app/
│   ├── code/
│   │   ├── computation/        # computation-specific code (edit here)
│   │   ├── framework/          # boilerplate-managed
│   │   └── runtime/            # boilerplate-managed NVFlare entrypoints
│   ├── config/                 # boilerplate-managed NVFlare job config
│   └── local_data/             # mask.nii and NeuroMark.nii
├── system/                     # boilerplate-managed provisioning and entrypoints
├── scripts/                    # boilerplate-managed manifest and publishing tools
├── tests/
├── test_data/
├── .neuroflame.json            # computation version and image coordinates
├── display_notes.md
├── Dockerfile-dev / Dockerfile-prod
└── run_local_simulation.sh
```

## References

- Original COINSTAC MANCOVA: https://github.com/trendscenter/coinstac-mancova
- GIFT Toolbox: https://icatb.sourceforge.io/
- NeuroFLAME: https://github.com/NeuroFlame
