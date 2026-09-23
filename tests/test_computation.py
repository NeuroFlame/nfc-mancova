"""Unit tests for the MANCOVA computation logic that runs without GIFT/MATLAB."""

import logging
import os
import tarfile
import tempfile
import unittest

import pandas as pd
from computation import local_math, remote_math
from computation.inputs import load_site_inputs
from computation.report import generate_report
from computation.spec import SPEC
from computation.types import (
    GlobalResults,
    SiteInputs,
    SiteMancovaResult,
    SiteScanInfo,
)
from framework import ArtifactRef
from framework.serialization import deserialize_value, serialize_value
from framework.workflow import get_task_names

LOGGER = logging.getLogger("test_computation")


class WorkflowTests(unittest.TestCase):
    def test_task_names(self):
        self.assertEqual(
            get_task_names(SPEC.workflow),
            ["report_scan_length", "run_site_mancova", "write_site_outputs"],
        )

    def test_site_result_round_trips_through_framework_serialization(self):
        result = SiteMancovaResult(
            status="completed",
            num_subjects=2,
            num_covariates=1,
            covariates_df=pd.DataFrame({"age": [25, None]}),
            covariate_types={"age": "continuous"},
            features=["fnc correlations"],
            output_directory="/out",
        )
        restored = deserialize_value(serialize_value(result), SiteMancovaResult)
        self.assertEqual(restored.num_subjects, 2)
        self.assertEqual(restored.covariate_types, {"age": "continuous"})
        pd.testing.assert_frame_equal(restored.covariates_df, result.covariates_df)

    def test_materialized_artifacts_pass_through_typed_fields(self):
        ref = ArtifactRef(name="a.mat", path="/tmp/a.mat")
        restored = deserialize_value(
            {
                "status": "completed",
                "num_subjects": 1,
                "num_covariates": 0,
                "covariates_df": serialize_value(pd.DataFrame()),
                "covariate_types": {},
                "features": [],
                "output_directory": "/out",
                "stat_files": {"regression": {"a.mat": ref}},
            },
            SiteMancovaResult,
        )
        self.assertIs(restored.stat_files["regression"]["a.mat"], ref)


class InputTests(unittest.TestCase):
    def test_discovers_niftis_and_covariates(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("b.nii", "a.nii.gz", "c.nii"):
                open(os.path.join(tmp, name), "w").close()
            open(os.path.join(tmp, "covariates.csv"), "w").close()
            inputs = load_site_inputs(tmp, {"max_subjects": 2}, LOGGER)
        self.assertEqual(
            [os.path.basename(p) for p in inputs.nifti_files], ["a.nii.gz", "b.nii"]
        )
        self.assertTrue(inputs.covariates_file.endswith("covariates.csv"))
        self.assertIsNone(inputs.covariate_types_file)

    def test_skip_gica_requires_input_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_site_inputs(tmp, {"skip_gica": True}, LOGGER)
            with self.assertRaises(FileNotFoundError):
                load_site_inputs(
                    tmp, {"skip_gica": True, "gica_input_dir": "missing"}, LOGGER
                )

    def test_univariate_tests_require_a_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_site_inputs(tmp, {"run_univariate_tests": True}, LOGGER)


class LocalMathTests(unittest.TestCase):
    def test_convert_covariates(self):
        with tempfile.TemporaryDirectory() as tmp:
            cov_file = os.path.join(tmp, "covariates.csv")
            pd.DataFrame(
                {
                    "age": [25, 30, 35],
                    "sex": [0, 1, 0],
                    "filename": ["a.nii", "b.nii", "c.nii"],
                }
            ).to_csv(cov_file, index=False)
            keys_file = os.path.join(tmp, "covariate_keys.csv")
            pd.DataFrame(
                {"name": ["age", "sex"], "type": ["continuous", "categorical"]}
            ).to_csv(keys_file, index=False)

            covariates, out_df, cov_types = local_math.convert_covariates(
                covariate_filename=cov_file,
                output_dir=os.path.join(tmp, "out"),
                logger=LOGGER,
                covariate_types_file=keys_file,
                num_samples=2,
            )

            self.assertEqual(set(covariates), {"age", "sex"})
            self.assertEqual(covariates["sex"][0], "categorical")
            with open(covariates["age"][1]) as f:
                self.assertEqual(f.read(), "25\n30")
            self.assertEqual(len(out_df), 2)
            self.assertEqual(cov_types["age"], "continuous")

    def test_convert_covariates_infers_types_from_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            cov_file = os.path.join(tmp, "covariates.csv")
            pd.DataFrame({"sex:categorical": [0, 1]}).to_csv(cov_file, index=False)
            covariates, out_df, _ = local_math.convert_covariates(cov_file, tmp, LOGGER)
        self.assertEqual(covariates["sex"][0], "categorical")
        self.assertIn("sex", out_df.columns)

    def test_prepare_univariate_test(self):
        df = pd.DataFrame({"diagnosis": ["HC", "SZ", "HC", "SZ"]})
        regression = local_math._prepare_univariate_test(
            {"regression": {"age": ["sex"]}}, df
        )
        self.assertEqual(regression, {"age": ["sex"]})

        ttest = local_math._prepare_univariate_test(
            {"ttest2": {"variable": "diagnosis", "name": ["HC", "SZ"]}}, df
        )
        self.assertNotIn("variable", ttest["ttest2"])
        self.assertEqual(
            [list(map(int, d)) for d in ttest["ttest2"]["datasets"]], [[1, 3], [2, 4]]
        )

    def test_scan_length_only_queried_when_negotiating(self):
        inputs = SiteInputs(nifti_files=[])
        stateful = local_math.report_scan_length(
            inputs, data_dir="/data", parameters={}, logger=LOGGER
        )
        self.assertEqual(stateful.payload.scan_length, 0)
        self.assertIs(stateful.state, inputs)

    def test_stats_files_are_staged_as_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "x_mancovan_stats_info.mat")
            with open(src, "wb") as f:
                f.write(b"mat")
            artifact_dir = os.path.join(tmp, "artifacts")
            os.makedirs(artifact_dir)
            staged = local_math._stage_stats_artifacts(
                {"regression": [src]}, artifact_dir
            )
            ref = staged["regression"]["x_mancovan_stats_info.mat"]
            self.assertEqual(ref.name, "regression-x_mancovan_stats_info.mat")
            self.assertEqual(os.path.dirname(ref.path), artifact_dir)
            self.assertTrue(os.path.exists(ref.path))


class RemoteMathTests(unittest.TestCase):
    def test_resolve_common_timepoints(self):
        scans = {"a": SiteScanInfo(150), "b": SiteScanInfo(120), "c": SiteScanInfo(0)}
        resolve = remote_math.resolve_common_timepoints
        self.assertEqual(
            resolve(
                scans, parameters={"common_timepoints": True}, logger=LOGGER
            ).common_timepoints,
            120,
        )
        self.assertEqual(
            resolve(
                scans, parameters={"common_timepoints": 90}, logger=LOGGER
            ).common_timepoints,
            90,
        )
        for value in (False, None, "yes"):
            self.assertEqual(
                resolve(
                    scans, parameters={"common_timepoints": value}, logger=LOGGER
                ).common_timepoints,
                0,
            )

    def test_site_order_follows_provisioning(self):
        parameters = {"site_id_name_map": {"id2": "beta", "id1": "alpha"}}
        self.assertEqual(
            remote_math._order_site_names(["zeta", "alpha", "beta"], parameters),
            ["beta", "alpha", "zeta"],
        )

    def test_combine_site_covariates(self):
        with tempfile.TemporaryDirectory() as tmp:
            all_cov, combined_df, cov_types = remote_math.combine_site_covariates(
                covariate_dfs=[
                    pd.DataFrame({"age": [25, 30], "sex": [0, 1]}),
                    pd.DataFrame(),
                    pd.DataFrame({"age": [40, 45], "sex": [1, 0]}),
                ],
                covariate_types=[{"sex": "categorical"}, {}, {"age": "continuous"}],
                output_dir=tmp,
                logger=LOGGER,
            )
            self.assertEqual(len(combined_df), 4)
            self.assertEqual(all_cov["sex"][0], "categorical")
            with open(all_cov["age"][1]) as f:
                self.assertEqual(f.read().split("\n"), ["25", "30", "40", "45"])
            self.assertTrue(
                os.path.exists(os.path.join(tmp, "combined_covariates.csv"))
            )
        self.assertEqual(cov_types, {"sex": "categorical", "age": "continuous"})

    def test_aggregation_archive_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = os.path.join(tmp, "server")
            os.makedirs(os.path.join(server_dir, ".artifacts"))
            os.makedirs(os.path.join(server_dir, "site1", "regression"))
            with open(os.path.join(server_dir, "index.html"), "w") as f:
                f.write("<html>report</html>")
            with open(os.path.join(server_dir, "site1", "regression", "s.mat"), "w"):
                pass
            archive_path = os.path.join(server_dir, ".artifacts", "agg.tar.gz")
            remote_math._archive_directory(server_dir, archive_path)
            with tarfile.open(archive_path) as archive:
                names = archive.getnames()
            self.assertFalse(any(".artifacts" in name for name in names))

            site_dir = os.path.join(tmp, "site1")
            outputs = remote_math.write_site_outputs(
                GlobalResults(
                    summary={"status": "aggregation_completed"},
                    aggregation_archive=ArtifactRef("agg.tar.gz", archive_path),
                ),
                output_dir=site_dir,
                logger=LOGGER,
            )
            self.assertEqual(outputs["index.html"], "<html>report</html>")
            self.assertEqual(
                outputs["global_mancova_results.json"]["status"],
                "aggregation_completed",
            )
            self.assertTrue(
                os.path.exists(
                    os.path.join(
                        site_dir, "aggregation", "site1", "regression", "s.mat"
                    )
                )
            )


class ReportTests(unittest.TestCase):
    def test_generate_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            global_results = {
                "status": "aggregation_completed",
                "num_sites": 2,
                "num_subjects": 10,
                "num_covariates": 3,
                "features": ["fnc correlations"],
                "run_mancova": True,
                "run_univariate_tests": True,
                "multivariate_result_paths": [],
                "univariate_result_paths": {},
                "aggregation_directory": tmp,
            }
            site_results = [
                {
                    "num_subjects": 5,
                    "num_covariates": 3,
                    "status": "completed",
                    "univariate_stat_info_files": ["x.mat"],
                },
                {"num_subjects": 5, "num_covariates": 3, "status": "completed"},
            ]
            parameters = {
                "scica_template": "NeuroMark.nii",
                "univariate_test_list": [{"regression": {"age": ["sex"]}}],
            }
            report_path = generate_report(
                tmp, global_results, site_results, ["alpha", "beta"], parameters
            )
            with open(report_path) as f:
                html = f.read()
        self.assertEqual(os.path.basename(report_path), "index.html")
        self.assertIn("alpha", html)
        self.assertIn("NeuroMark.nii", html)
        self.assertIn("Multivariate MANCOVA", html)
        self.assertEqual(html, global_results["report_html"])


if __name__ == "__main__":
    unittest.main()
