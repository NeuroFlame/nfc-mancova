### Overview

Federated MANCOVA (Multivariate Analysis of Covariance) with Group ICA enables multi-site neuroimaging analysis without sharing raw data. Each site runs Group ICA locally using the GIFT toolbox, then statistical results are aggregated at the central node to produce global multivariate and univariate analyses across all sites.

This computation is a NeuroFLAME port of the [COINSTAC MANCOVA](https://github.com/trendscenter/coinstac-mancova) pipeline. The federated design mirrors the original: edge nodes run Group ICA and local univariate preprocessing, the central node aggregates covariates and runs global MANCOVA.

### Example Settings

```json
{
    "scica_template": "NeuroMark.nii",
    "mask": "default&icv",
    "TR": 2,
    "num_components": 53,
    "algorithm": 16,
    "skip_gica": false,
    "gica_input_dir": "",
    "features": ["fnc correlations", "timecourses spectra"],
    "common_timepoints": false,
    "comp_network_names": {
        "SC":  [1, 2, 3, 4, 5],
        "AUD": [6, 7],
        "SM":  [8, 9, 10, 11, 12, 13, 14, 15, 16],
        "VIS": [17, 18, 19, 20, 21, 22, 23, 24, 25],
        "CC":  [26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42],
        "DMN": [43, 44, 45, 46, 47, 48, 49],
        "CR":  [50, 51, 52, 53]
    },
    "run_univariate_tests": true,
    "univariate_test_list": [
        {
            "regression": {
                "age": ["gender"],
                "gender": ["age"]
            }
        }
    ],
    "run_mancova": false,
    "interactions": [],
    "numOfPCs": [4, 4, 4],
    "freq_limits": [0.1, 0.15],
    "threshdesc": "fdr",
    "p_threshold": 0.05,
    "display_p_threshold": 0.05,
    "t_threshold": 1.0,
    "image_values": "positive",
}
```

### Settings Specification

| Variable Name | Type | Description | Allowed Options | Default | Required |
| --- | --- | --- | --- | --- | --- |
| `scica_template` | `string` | Template used as the spatial reference for Group ICA. Provide a filename for a GIFT built-in template (e.g. `NeuroMark.nii`, `Neuromark_fMRI_2.0.nii`) or a full path to a locally available template within the container filesystem. | Any GIFT built-in template name or an absolute container path | `"NeuroMark.nii"` | ✅ true |
| `mask` | `string` | Brain mask applied during Group ICA. Use `"default"` or `"default&icv"` for GIFT's automatic masking (recommended), or provide an absolute container path to a NIfTI mask file. | `"default"`, `"default&icv"`, or a container path | `"default&icv"` | ✅ true |
| `TR` | `number` or `array` | Repetition time of the fMRI acquisition in seconds. Provide a single value applied to all subjects, or a list with one value per subject. | Any positive number or list of positive numbers | `2` | ✅ true |
| `num_components` | `number` | Number of independent components to extract during Group ICA. The NeuroMark 1.0 template uses 53. | Any positive integer | `53` | ✅ true |
| `algorithm` | `number` | ICA algorithm used by GIFT. 16 corresponds to GIG-ICA, which is recommended when using a spatial template. | Integer 1–17 (see GIFT documentation for full list) | `16` | ❌ false |
| `skip_gica` | `boolean` | Skip the Group ICA step and use a pre-existing ICA output directory instead. Requires `gica_input_dir` to point to a valid GIFT output. | `true`, `false` | `false` | ❌ false |
| `gica_input_dir` | `string` | Path to a pre-existing GIFT Group ICA output directory, relative to the site data directory. Only used when `skip_gica` is `true`. | Any valid path | `""` | ❌ false |
| `features` | `array` | GIFT MANCOVA features to compute for each component. | `"fnc correlations"`, `"timecourses spectra"`, `"spatial maps"` | `[]` | ✅ true |
| `common_timepoints` | `boolean` or `number` | Ensures all sites use the same timecourse length when `"timecourses spectra"` is included in `features`. Set to `true` to auto-negotiate the minimum scan length across all participating sites (requires a pre-round query). Set to an explicit integer to truncate every site to exactly that many timepoints. Set to `false` (or omit) to disable truncation. Only needed when sites have different native scan lengths. | `false`, `true`, or a positive integer | `false` | ❌ false |
| `comp_network_names` | `object` | Dictionary mapping network labels to lists of component indices. Used to assign components to functional networks for reporting. If omitted the NeuroMark 53-component network map is used. | Any dict of `string → array of integers` | NeuroMark 53-component map | ❌ false |
| `run_univariate_tests` | `boolean` | Whether to run site-level univariate tests (e.g. regression, one-sample t-test, two-sample t-test) and aggregate their statistics at the central node. | `true`, `false` | `false` | ❌ false |
| `univariate_test_list` | `array` | List of univariate tests to run. Each element is a single-key object where the key is the test type. For `"regression"`, the value is a dict mapping each outcome variable to a list of covariates to include as confounds: `{"regression": {"age": ["gender"], "gender": ["age"]}}`. For group tests (`"one sample t-test"`, `"two sample t-test"`), include a `"variable"` key naming the grouping covariate. | See example above | `[]` | ❌ false |
| `run_mancova` | `boolean` | Whether to run multivariate MANCOVA at the central node using pooled data from all sites. | `true`, `false` | `false` | ❌ false |
| `interactions` | `array` | Interaction terms to include in the multivariate MANCOVA model. | List of covariate name pairs | `[]` | ❌ false |
| `numOfPCs` | `array` | Number of principal components to retain per feature type during dimensionality reduction before MANCOVA. Provide one integer per entry in `features`. | List of positive integers | `[4, 4, 4]` | ❌ false |
| `freq_limits` | `array` | Frequency band limits in Hz used for spectral feature computation. | Two-element list `[low, high]` | `[0.1, 0.15]` | ❌ false |
| `threshdesc` | `string` | Multiple comparisons correction method applied to statistical maps. | `"fdr"`, `"none"` | `"fdr"` | ❌ false |
| `p_threshold` | `number` | P-value threshold for computing statistical results. | Any value in (0, 1] | `0.05` | ❌ false |
| `display_p_threshold` | `number` | P-value threshold used when rendering result images in the HTML report. | Any value in (0, 1] | `0.05` | ❌ false |
| `t_threshold` | `number` | T-statistic threshold used when rendering result images in the HTML report. | Any positive number | `1.0` | ❌ false |
| `image_values` | `string` | Controls which voxel values are shown in result images. | `"positive"`, `"negative"`, `"both"`, `"absolute value"` | `"positive"` | ❌ false |

### Input Description

Each site's data directory must contain:

- **NIfTI files** (`*.nii` or `*.nii.gz`) — one file per subject, at the top level of the data directory. Files are discovered automatically via glob. All NIfTI files present will be included in the analysis.
- **`*covariates.csv`** — a CSV file whose name ends in `covariates.csv`. Each row is one subject (in the same order as the sorted NIfTI file list). Columns are covariate names; an optional `filename` column is ignored. Any covariate used in `univariate_test_list` must appear here. Column headers may optionally encode type using the format `name:type` (e.g. `age:continuous`, `diagnosis:categorical`), which takes precedence over `*covariate_keys.csv`.
- **`*covariate_keys.csv`** (optional) — a CSV file whose name ends in `covariate_keys.csv` with two columns: `name` (covariate name) and `type` (`"continuous"` or `"categorical"`). If omitted, all covariates default to `"continuous"`.

All NIfTI files must be valid 4D functional MRI images (X × Y × Z × Time) readable by the GIFT toolbox. Standard preprocessing (motion correction, slice-timing correction, spatial normalisation, smoothing) is assumed to have been performed prior to running this computation.

When `skip_gica` is `true`, the data directory must instead contain a GIFT Group ICA output in the subdirectory pointed to by `gica_input_dir`. The NIfTI files and covariates CSV must still be present and correctly ordered.

### Algorithm Description

1. **Server — Common Timepoints Negotiation** *(if `common_timepoints` is `true`)*

   Before dispatching the main computation, the server broadcasts a `QUERY_SCAN_LENGTH` task to all sites. Each site reports the number of timepoints in its ICA timecourse data (read from the GIFT parameter mat file when `skip_gica` is `true`, or from the raw NIfTI when running fresh GICA). The server computes the global minimum and resolves `common_timepoints` to that integer. All subsequent steps see an explicit count.

2. **Edge Node — Input Validation**

   Before any computation begins, each site validates its inputs: the GIFT ICA output directory is confirmed to exist when `skip_gica` is `true`; `univariate_test_list` is checked for completeness when `run_univariate_tests` is `true`; and a warning is logged if `features` is empty. Validation errors are raised immediately with a descriptive message so failures are caught before any MATLAB runtime is invoked.

3. **Edge Node — Group ICA**

   Each site runs GIFT Group ICA on its local NIfTI files using the specified template and parameters. The spatially constrained ICA identifies independent components that align with the provided template. If `skip_gica` is `true` and `gica_input_dir` points to an existing GIFT output, this step is skipped and the pre-computed ICA is used instead.

4. **Edge Node — Common Timepoints Truncation** *(if `common_timepoints` is non-zero)*

   Before running MANCOVA, each site truncates its ICA timecourse NIfTIs to the specified number of timepoints and patches the `numOfScans` and `diffTimePoints` fields in the GIFT parameter mat file. Both HDF5/MATLAB 7.3 and v5 binary mat file formats are supported; v5 files that already match the target length are copied without modification. The truncated data is staged to a separate directory; the original ICA output is not modified.

5. **Edge Node — Covariate Preparation**

   Covariates are loaded from the site's CSV file and written to per-covariate text files required by the GIFT MANCOVA interface. Covariate types (continuous vs. categorical) are read from the covariate keys file or inferred from column header suffixes, defaulting to continuous if not specified.

6. **Edge Node — Per-Site Full MANCOVA** *(if `run_mancova` is `true`)*

   Each site runs a full site-level GIFT MANCOVA (multivariate, FNC + spectra features) on its local ICA output. This run is not federated — its purpose is to generate the per-site HTML report and component images that appear in the final report. The result summary HTML is written to `coinstac-mancova/gica_cmd_mancovan_results_summary/`. The per-site MANCOVA does not produce `mancovan_stats_info.mat` files and its outputs are not transferred to the central node.

7. **Edge Node — Local Univariate Tests** *(if `run_univariate_tests` is `true`)*

   Each site runs GIFT MANCOVA in univariate mode on its local ICA output. For each test in `univariate_test_list`, GIFT computes site-level statistics and writes a `*mancovan_stats_info.mat` file. Only covariates named in the test specification are passed to GIFT, so that all sites produce statistics matrices of compatible shape regardless of site-specific nuisance regressors. The `.mat` file bytes are packaged into a DXO (NVFlare Data Exchange Object with `DataKind.COLLECTION`) keyed by test name, which the central node extracts and writes to disk without deserialising the MATLAB binary.

8. **Central Node — Covariate Aggregation**

   The central node extracts per-site `mancovan_stats_info.mat` bytes from the incoming DXO and writes them to per-site subdirectories within the aggregation directory. It then receives covariate DataFrames from all sites, concatenates them into a single pooled dataset, and regenerates combined covariate text files.

9. **Central Node — Univariate Aggregation** *(if `run_univariate_tests` is `true`)*

   The `.mat` stats files written to disk in the previous step are passed to `gift_mancova_aggregate_stats`, which pools the site-level statistics and generates global HTML reports and PNG component maps for each univariate test.

10. **Central Node — Report Generation and Delivery**

    A self-contained HTML report (`index.html`) is produced embedding all result images. The full aggregation output directory — HTML, PNG component maps, spectral heatmaps, effect-size charts, and the connectogram — is then packaged into a DXO and broadcast back to every participating site via the `ACCEPT_GLOBAL_RESULTS` task. Each site unpacks the package into its `aggregation/` output subdirectory, giving every site identical access to the global results without requiring access to the server filesystem.

### Assumptions

- All NIfTI files at the top level of each site's data directory will be included. Subdirectories are not scanned.
- Subjects in `covariates.csv` must be in the same order as the alphabetically sorted NIfTI file list.
- Standard fMRI preprocessing (realignment, normalisation to MNI space, spatial smoothing) has been applied to all data before running this computation.
- All sites use the same ICA template, number of components, and TR to ensure comparability of ICA outputs across sites.
- When `skip_gica` is `true`, the pre-existing ICA output must have been generated by GIFT with a compatible configuration.
- When `"timecourses spectra"` is included in `features` and sites have different native scan lengths, `common_timepoints` must be set (either `true` for auto-negotiation, or an explicit integer). Mismatched scan lengths without truncation will cause the aggregation to fail.

### Output Description

#### Edge Node Outputs (per site)

Results are written to each site's output directory within the job workspace. In a production NeuroFLAME deployment, each site can only access its own output directory.

- `index.html` — self-contained HTML report summarising the full federated analysis. Includes per-site MANCOVA summaries and globally aggregated statistical images.
- `edge_mancova_results.json` — summary of the edge computation: status, number of subjects, covariates found, and file paths. Binary stat file blobs are excluded.
- `global_mancova_results.json` — top-level summary received from the central node: status, number of sites and subjects, paths to global result files.
- `{site_name}.log` — per-site log file capturing all computation steps including GIFT heartbeat lines. Each site writes to its own log so concurrent sites never interleave output.
- `coinstac-gica/` — GIFT Group ICA output directory (ICA components, timecourses, parameter mat file).
- `coinstac-gica-truncated/` *(if `common_timepoints` is non-zero)* — GICA output with timecourse NIfTIs truncated to the common length and the parameter mat file patched accordingly.
- `coinstac-mancova/` *(if `run_mancova` is `true`)* — per-site full MANCOVA output including `gica_cmd_mancovan_results_summary/icatb_mancovan_results_summary.html` and component PNG images.
- `coinstac-univariate-<test>/` — one directory per univariate test containing `*mancovan_stats_info.mat` (transferred to the central node) plus a local HTML summary.
- `aggregation/` — full copy of the central node's aggregation output delivered back to the site after the federated run completes. Contains all global HTML reports, PNG maps (spectral heatmaps, effect-size charts, connectogram), and CSV files.

#### Central Node Outputs

The central node's aggregation directory is also delivered to every site (see `aggregation/` above). The following files are produced there:

- `combined_covariates.csv` — pooled covariate table across all sites.
- `COINSTAC_COVAR_<name>.txt` — one text file per covariate with pooled values passed to GIFT.
- `coinstac-global-univariate-<test>/` *(if `run_univariate_tests` is `true`)* — globally aggregated statistics, HTML report, and PNG component maps per univariate test.
- `index.html` — the aggregated HTML report (same content distributed to all sites).
- `controller.log` / `aggregator.log` — server-side log files for the controller and aggregator components.
- `<site_name>/` — per-site subdirectory holding the `mancovan_stats_info.mat` files received from each site.
