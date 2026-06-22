"""
Smoke test for nfc-mancova core logic.

Exercises covariate handling, .mat byte serialisation, aggregation,
and report generation without requiring NVFlare or GIFT/MATLAB.
"""

import os
import sys
import json
import tempfile

# Make app/code importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app", "code"))

import numpy as np
import pandas as pd

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def check(label, condition, detail=""):
    if condition:
        print(f"  {PASS}  {label}")
    else:
        print(f"  {FAIL}  {label}" + (f" — {detail}" if detail else ""))
    return condition


# ---------------------------------------------------------------------------
# Test 1: convert_covariates
# ---------------------------------------------------------------------------
def test_convert_covariates():
    print("\n[1] convert_covariates")
    from executor.mancova_edge_computation import convert_covariates

    with tempfile.TemporaryDirectory() as tmp:
        # Write a minimal covariates CSV
        cov_file = os.path.join(tmp, "covariates.csv")
        df = pd.DataFrame({"age": [25, 30, 35], "sex": [0, 1, 0], "filename": ["a.nii", "b.nii", "c.nii"]})
        df.to_csv(cov_file, index=False)

        # Write covariate keys
        keys_file = os.path.join(tmp, "covariate_keys.csv")
        pd.DataFrame({"name": ["age", "sex"], "type": ["continuous", "categorical"]}).to_csv(keys_file, index=False)

        covariates, out_df, cov_types = convert_covariates(
            covariate_filename=cov_file,
            output_dir=tmp,
            covariate_types_file=keys_file,
            num_samples=3,
        )

        check("returns 2 covariates", len(covariates) == 2)
        check("age type is continuous", covariates["age"][0] == "continuous")
        check("sex type is categorical", covariates["sex"][0] == "categorical")
        check("filename column excluded", "filename" not in covariates)
        check("age txt file written", os.path.exists(covariates["age"][1]))
        check("sex txt file written", os.path.exists(covariates["sex"][1]))
        check("output df has 3 rows", len(out_df) == 3)


# ---------------------------------------------------------------------------
# Test 2: _prepare_univariate_test
# ---------------------------------------------------------------------------
def test_prepare_univariate_test():
    print("\n[2] _prepare_univariate_test")
    from executor.mancova_edge_computation import _prepare_univariate_test

    df = pd.DataFrame({"diagnosis": ["HC", "SZ", "HC", "SZ"]})

    # Regression — should return unwrapped inner dict
    reg_spec = {"regression": {"name": ["age"]}}
    result = _prepare_univariate_test(reg_spec, df)
    check("regression returns unwrapped dict", isinstance(result, dict) and "name" in result)
    check("regression not double-wrapped", "regression" not in result)

    # Two-sample t-test — should return wrapped {key: params} with datasets
    tt_spec = {"two sample t-test": {"variable": "diagnosis", "name": ["HC", "SZ"]}}
    result = _prepare_univariate_test(tt_spec, df)
    check("t-test returns wrapped dict", "two sample t-test" in result)
    check("t-test has datasets", "datasets" in result["two sample t-test"])
    datasets = result["two sample t-test"]["datasets"]
    check("HC dataset has 2 entries", len(datasets[0]) == 2)
    check("SZ dataset has 2 entries", len(datasets[1]) == 2)
    check("variable key removed", "variable" not in result["two sample t-test"])


# ---------------------------------------------------------------------------
# Test 3: data_transfer round-trip
# ---------------------------------------------------------------------------
def test_data_transfer():
    print("\n[3] data_transfer byte round-trip")
    from _utils.data_transfer import file_to_bytes, bytes_to_file

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "fake_stats_info.mat")
        original = b"\x00\x01\x02\x03MATLAB binary data mock\xff\xfe"
        with open(src, "wb") as f:
            f.write(original)

        data = file_to_bytes(src)
        check("file_to_bytes reads correct length", len(data) == len(original))
        check("file_to_bytes content matches", data == original)

        dst = os.path.join(tmp, "restored.mat")
        bytes_to_file(dst, data)
        check("bytes_to_file creates file", os.path.exists(dst))
        with open(dst, "rb") as f:
            restored = f.read()
        check("restored bytes match original", restored == original)

        # Missing file returns empty bytes (no crash)
        empty = file_to_bytes(os.path.join(tmp, "nonexistent.mat"))
        check("missing file returns empty bytes", empty == b"")


# ---------------------------------------------------------------------------
# Test 4: combine_site_covariates — covariate regeneration
# ---------------------------------------------------------------------------
def test_combine_site_covariates():
    print("\n[4] combine_site_covariates")
    from _utils.data_transfer import file_to_bytes, bytes_to_file
    from aggregator.mancova_central_aggregation import combine_site_covariates

    with tempfile.TemporaryDirectory() as tmp:
        # Simulate two sites sending edge results
        site1_df = pd.DataFrame({"age": [25, 30], "sex": [0, 1]})
        site2_df = pd.DataFrame({"age": [40, 45], "sex": [1, 0]})

        # Write a fake .mat file for site1
        mat_bytes = b"fake mat content site1"
        mat_path = os.path.join(tmp, "site1_mancovan_stats_info.mat")
        bytes_to_file(mat_path, mat_bytes)

        site_results = [
            {
                "covariates_df": site1_df.to_dict(),
                "covariates": {"age": ["continuous", "/site1/age.txt"], "sex": ["categorical", "/site1/sex.txt"]},
                "covariate_types": {"name": ["age", "sex"], "type": ["continuous", "categorical"]},
                "ica_parameters": ["/site1/param_info.mat"],
                "univariate_stat_info_files": [
                    {"name": "site1_mancovan_stats_info.mat", "data": file_to_bytes(mat_path)}
                ],
            },
            {
                "covariates_df": site2_df.to_dict(),
                "covariates": {"age": ["continuous", "/site2/age.txt"], "sex": ["categorical", "/site2/sex.txt"]},
                "covariate_types": {"name": ["age", "sex"], "type": ["continuous", "categorical"]},
                "ica_parameters": ["/site2/param_info.mat"],
                "univariate_stat_info_files": [],
            },
        ]

        all_cov, combined_df, cov_types, ica_params, stat_files = combine_site_covariates(
            site_results=site_results,
            output_dir=tmp,
        )

        check("combined df has 4 subjects", len(combined_df) == 4)
        check("combined_covariates has age", "age" in all_cov)
        check("combined_covariates has sex", "sex" in all_cov)

        # Paths must be local (in tmp), not the original per-site paths
        check("age path is local", all_cov["age"][1].startswith(tmp))
        check("sex path is local", all_cov["sex"][1].startswith(tmp))
        check("age txt file exists", os.path.exists(all_cov["age"][1]))
        check("sex txt file exists", os.path.exists(all_cov["sex"][1]))

        # Verify age file contains 4 values
        with open(all_cov["age"][1]) as f:
            lines = f.read().strip().split("\n")
        check("age txt has 4 values", len(lines) == 4)
        check("age values correct", lines == ["25", "30", "40", "45"])

        # ICA params collected from both sites
        check("ica_params from both sites", len(ica_params) == 2)

        # .mat bytes decoded and written locally
        check("stat_info .mat written locally", len(stat_files) == 1)
        check("stat_info file exists", os.path.exists(stat_files[0]))
        with open(stat_files[0], "rb") as f:
            check("stat_info bytes match original", f.read() == mat_bytes)


# ---------------------------------------------------------------------------
# Test 5: report_generator
# ---------------------------------------------------------------------------
def test_report_generator():
    print("\n[5] report_generator")
    from _utils.report_generator import generate_report

    with tempfile.TemporaryDirectory() as tmp:
        global_results = {
            "status": "aggregation_completed",
            "num_sites": 2,
            "num_subjects": 10,
            "num_covariates": 3,
            "features": ["spatial", "spectra", "fnc"],
            "run_mancova": True,
            "run_univariate_tests": True,
            "multivariate_result_paths": [os.path.join(tmp, "coinstac-multivariate", "report.html")],
            "univariate_result_paths": {
                "regression": [os.path.join(tmp, "coinstac-global-univariate-regression", "report.html")]
            },
            "aggregation_directory": tmp,
        }

        site_results = [
            {"num_subjects": 5, "num_covariates": 3, "status": "completed"},
            {"num_subjects": 5, "num_covariates": 3, "status": "completed"},
        ]

        parameters = {
            "scica_template": "NeuroMark.nii",
            "num_components": 53,
            "TR": 2,
            "features": ["spatial", "spectra", "fnc"],
            "numOfPCs": [4, 4, 4],
            "freq_limits": [0.1, 0.15],
            "threshdesc": "fdr",
            "p_threshold": 0.05,
        }

        report_path = generate_report(tmp, global_results, site_results, parameters)

        check("report written", os.path.exists(report_path))
        check("report is index.html", os.path.basename(report_path) == "index.html")

        with open(report_path) as f:
            html = f.read()

        check("contains site count", "2" in html)
        check("contains subject count", "10" in html)
        check("contains features", "spatial" in html)
        check("contains multivariate section", "Multivariate MANCOVA" in html)
        check("contains univariate section", "regression" in html)
        check("contains NeuroMark template", "NeuroMark.nii" in html)
        check("valid HTML structure", html.startswith("<!DOCTYPE html>") and "</html>" in html)


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    results = []
    for fn in [
        test_convert_covariates,
        test_prepare_univariate_test,
        test_data_transfer,
        test_combine_site_covariates,
        test_report_generator,
    ]:
        try:
            fn()
            results.append(True)
        except Exception as e:
            print(f"  {FAIL}  Uncaught exception: {e}")
            import traceback; traceback.print_exc()
            results.append(False)

    total = len(results)
    passed = sum(results)
    print(f"\n{'='*40}")
    print(f"  {passed}/{total} test groups passed")
    if passed < total:
        sys.exit(1)
