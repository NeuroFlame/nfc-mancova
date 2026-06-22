"""
Creates minimal synthetic test data for a Dockerfile-dev NVFlare simulator run.

Generates:
  test_data/site1/  - 4 tiny NIfTI files + covariates.csv
  test_data/site2/  - 4 tiny NIfTI files + covariates.csv
  test_data/server/parameters.json  - MANCOVA params with skip_gica + no univariate tests

Run inside the nfc-mancova:dev container (nibabel is installed there):
  python3 /workspace/create_test_data.py
"""
import json
import os

import nibabel as nib
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))


def make_nifti(path):
    data = np.random.randn(10, 10, 10, 20).astype(np.float32)
    img = nib.Nifti1Image(data, affine=np.eye(4))
    nib.save(img, path)


def make_site(site_name, subjects, ages, sexes):
    site_dir = os.path.join(ROOT, "test_data", site_name)
    os.makedirs(site_dir, exist_ok=True)
    filenames = []
    for i, subj in enumerate(subjects):
        fname = f"sub-{subj}_bold.nii.gz"
        fpath = os.path.join(site_dir, fname)
        make_nifti(fpath)
        filenames.append(fname)
        print(f"  created {fpath}")

    # covariates.csv
    lines = ["filename,age,sex"] + [
        f"{fn},{age},{sex}"
        for fn, age, sex in zip(filenames, ages, sexes)
    ]
    cov_path = os.path.join(site_dir, "covariates.csv")
    with open(cov_path, "w") as f:
        f.write("\n".join(lines))
    print(f"  created {cov_path}")

    # covariate_keys.csv (type annotations)
    keys_path = os.path.join(site_dir, "covariate_keys.csv")
    with open(keys_path, "w") as f:
        f.write("name,type\nage,continuous\nsex,categorical\n")
    print(f"  created {keys_path}")


def make_parameters():
    params = {
        "skip_gica": True,
        "run_univariate_tests": False,
        "num_components": 53,
        "algorithm": 16,
        "TR": 2,
        "features": ["spatial maps", "spectra", "fnc"],
        "numOfPCs": [4, 4, 4],
        "freq_limits": [0.1, 0.15],
        "t_threshold": 0.05,
        "image_values": "positive",
        "threshdesc": "fdr",
        "p_threshold": 0.05,
        "display_p_threshold": 0.05,
        "site_id_name_map": {
            "site1": "Site A",
            "site2": "Site B"
        }
    }
    server_dir = os.path.join(ROOT, "test_data", "server")
    os.makedirs(server_dir, exist_ok=True)
    out = os.path.join(server_dir, "parameters.json")
    with open(out, "w") as f:
        json.dump(params, f, indent=2)
    print(f"  created {out}")


if __name__ == "__main__":
    print("Creating test data for site1...")
    make_site("site1",
              subjects=["001", "002", "003", "004"],
              ages=[25, 31, 28, 35],
              sexes=["M", "F", "M", "F"])

    print("Creating test data for site2...")
    make_site("site2",
              subjects=["005", "006", "007", "008"],
              ages=[22, 40, 33, 27],
              sexes=["F", "M", "F", "M"])

    print("Writing parameters.json...")
    make_parameters()
    print("Done.")
