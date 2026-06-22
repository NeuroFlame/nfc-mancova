#!/usr/bin/env python3
"""
create_vault_subset.py — Create N-subject subsets of GICA vaults for fast testing.

Usage:
    python create_vault_subset.py [--n-subjects 20] [--common-timepoints 144]

Creates subset vaults alongside the originals:
    CMI-GICA_vault_Nsubj/
    TReNDS-COBRE-GICA_vault_Nsubj/

Each subset contains:
    - First N *_timecourses_*.nii files
    - covariates.csv truncated to N rows
    - gica_cmd_ica_parameter_info.mat with numOfSub/numOfDataSets patched to N

--common-timepoints truncates all timecourse NIfTIs to that many volumes so that
the 'timecourses spectra' GIFT feature produces a compatible feature vector across
sites (required when sites have different scan lengths).
"""

import argparse
import glob
import os
import shutil
import struct

import numpy as np
import pandas as pd

VAULT_BASE = "/Users/admin/Desktop/Vault Data"

VAULTS = [
    {
        "src": f"{VAULT_BASE}/CMI-GICA_vault",
        "dst_template": f"{VAULT_BASE}/CMI-GICA_vault_{{n}}subj",
        "mat_format": "hdf5",
    },
    {
        "src": f"{VAULT_BASE}/TReNDS-COBRE-GICA_vault",
        "dst_template": f"{VAULT_BASE}/TReNDS-COBRE-GICA_vault_{{n}}subj",
        "mat_format": "v5",
    },
]


def patch_hdf5_mat(src: str, dst: str, n: int, n_scans: int = 0) -> None:
    import h5py
    shutil.copy2(src, dst)
    with h5py.File(dst, "r+") as f:
        f["sesInfo/numOfSub"][0, 0] = float(n)
        f["sesInfo/numOfDataSets"][0, 0] = float(n)
        if n_scans:
            f["sesInfo/numOfScans"][0, 0] = float(n_scans)
            # diffTimePoints is a per-subject TP count vector (shape: numSubjects, 1).
            # GIFT indexes into this by subject number, so all entries must match
            # the truncated scan length or GIFT preallocates the wrong matrix size.
            if "sesInfo/diffTimePoints" in f:
                f["sesInfo/diffTimePoints"][:] = float(n_scans)
    msg = f"numOfSub={n}"
    if n_scans:
        msg += f", numOfScans={n_scans}, diffTimePoints={n_scans}"
    print(f"  Patched mat (HDF5) → {msg}")


def _v5_read_tag(data: bytes, offset: int):
    """Return (type, size, data_offset, next_offset) for a MATLAB v5 data element."""
    if offset + 8 > len(data):
        return None
    t, s = struct.unpack_from("<II", data, offset)
    if t >> 16:  # small data element
        return t & 0xFFFF, t >> 16, offset + 4, offset + 8
    return t, s, offset + 8, offset + 8 + ((s + 7) & ~7)


def _v5_find_sesinfo_field_data_offsets(data: bytes, target_fields: set) -> dict:
    """
    Parse a MATLAB v5 mat file and return {field_name: byte_offset_of_value}
    for each requested field in the top-level sesInfo struct.

    The MATLAB v5 struct layout is:
      miMATRIX (type 14)
        array flags   (miUINT32, 8 bytes)
        dimensions    (miINT32)
        array name    (miINT8)
        field name length (miINT32, 4 bytes) — SCALAR stored as a tag
        field names   (miINT8 block, all names padded to fieldNameLength)
        field0 value  (miMATRIX)
        field1 value  (miMATRIX)
        ...
    """
    import struct

    results = {}
    off = 128  # skip 128-byte file header
    tag = _v5_read_tag(data, off)
    if tag is None or tag[0] != 14:
        return results
    tp, sz, data_start, _ = tag

    # Array flags
    ft = _v5_read_tag(data, data_start)
    sub = ft[3]
    # Dimensions
    dt = _v5_read_tag(data, sub)
    sub = dt[3]
    # Array name (skip)
    nt = _v5_read_tag(data, sub)
    sub = nt[3]

    # Field name length — stored as a small-data element (type=5=miINT32, size=4)
    fnl_tag = _v5_read_tag(data, sub)
    field_name_length = struct.unpack_from("<I", data, fnl_tag[2])[0]
    sub = fnl_tag[3]

    # Field names block (miINT8)
    fn_tag = _v5_read_tag(data, sub)
    fn_block_offset = fn_tag[2]
    num_fields = fn_tag[1] // field_name_length
    sub = fn_tag[3]

    field_names = []
    for i in range(num_fields):
        raw = data[fn_block_offset + i * field_name_length:
                   fn_block_offset + (i + 1) * field_name_length]
        field_names.append(raw.rstrip(b"\x00").decode("ascii", "replace"))

    # Walk field values to find our targets
    for i, fname in enumerate(field_names):
        ftag = _v5_read_tag(data, sub)
        if ftag is None:
            break
        if fname in target_fields:
            # Inside this miMATRIX: flags → dims → name → data
            fs = ftag[2]
            fs = _v5_read_tag(data, fs)[3]   # skip flags
            fs = _v5_read_tag(data, fs)[3]   # skip dims
            fs = _v5_read_tag(data, fs)[3]   # skip name
            data_tag = _v5_read_tag(data, fs)
            if data_tag:
                results[fname] = data_tag[2]  # offset of the raw value byte(s)
        sub = ftag[3]

    return results


def patch_v5_mat(src: str, dst: str, n: int, n_scans: int = 0) -> None:
    """Patch numOfSub, numOfDataSets, and optionally numOfScans in a MATLAB v5 mat file."""
    import struct
    shutil.copy2(src, dst)
    with open(dst, "rb") as fh:
        data = bytearray(fh.read())

    target_fields = {"numOfSub", "numOfDataSets"}
    if n_scans:
        target_fields.add("numOfScans")

    offsets = _v5_find_sesinfo_field_data_offsets(bytes(data), target_fields)

    patched = []
    for field, off in offsets.items():
        old = data[off]
        val = n_scans if (field == "numOfScans" and n_scans) else n
        data[off] = val & 0xFF
        patched.append(f"{field}: {old} → {val}")

    with open(dst, "wb") as fh:
        fh.write(data)
    if patched:
        print(f"  Patched mat (v5 binary) → {', '.join(patched)}")
    else:
        print("  WARNING: could not locate fields in mat file")


def truncate_nii_timepoints(src: str, dst: str, n_tp: int) -> None:
    """Copy a NIfTI timecourse file, keeping only the first n_tp volumes."""
    import nibabel as nib
    img = nib.load(src)
    data = img.get_fdata()
    if data.ndim < 2 or data.shape[0] <= n_tp:
        shutil.copy2(src, dst)
        return
    truncated = data[:n_tp, ...]
    new_img = nib.Nifti1Image(truncated, img.affine, img.header)
    new_img.header["dim"][1] = n_tp
    nib.save(new_img, dst)


def create_subset(src: str, dst: str, n: int, mat_format: str, common_timepoints: int = 0) -> None:
    print(f"\n{'='*60}")
    print(f"Creating {'all' if n == 0 else n}-subject subset")
    print(f"  src: {src}")
    print(f"  dst: {dst}")
    if common_timepoints:
        print(f"  truncating timecourses to {common_timepoints} TPs")

    if os.path.exists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)

    # Copy subject timecourse NIfTIs (sorted); n=0 means all subjects
    all_nii = sorted(
        glob.glob(os.path.join(src, "*timecourses*.nii")) +
        glob.glob(os.path.join(src, "*timecourses*.nii.gz"))
    )
    subset_nii = all_nii if n == 0 else all_nii[:n]
    for f in subset_nii:
        dst_f = os.path.join(dst, os.path.basename(f))
        if common_timepoints:
            truncate_nii_timepoints(f, dst_f, common_timepoints)
        else:
            shutil.copy2(f, dst_f)
    print(f"  Copied {len(subset_nii)} NIfTI files")

    # Always use the NIfTI count as the authoritative subject count —
    # source vaults can have extra covariate rows for excluded subjects.
    actual_n = len(subset_nii)

    # Truncate covariates.csv to match NIfTI count
    csv_src = os.path.join(src, "covariates.csv")
    if os.path.exists(csv_src):
        df = pd.read_csv(csv_src)
        out_df = df.head(actual_n)
        out_df.to_csv(os.path.join(dst, "covariates.csv"), index=False)
        if len(df) != actual_n:
            print(f"  Wrote covariates.csv ({len(out_df)} rows, trimmed from {len(df)} to match NIfTI count)")
        else:
            print(f"  Wrote covariates.csv ({len(out_df)} rows)")
    else:
        print("  WARNING: covariates.csv not found in source vault")
    mat_src = os.path.join(src, "gica_cmd_ica_parameter_info.mat")
    mat_dst = os.path.join(dst, "gica_cmd_ica_parameter_info.mat")
    if os.path.exists(mat_src):
        if mat_format == "hdf5":
            patch_hdf5_mat(mat_src, mat_dst, actual_n, n_scans=common_timepoints)
        else:
            patch_v5_mat(mat_src, mat_dst, actual_n, n_scans=common_timepoints)
    else:
        print("  WARNING: gica_cmd_ica_parameter_info.mat not found in source vault")

    print(f"  Done → {dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-subjects", type=int, default=20, help="Subjects per site")
    parser.add_argument(
        "--common-timepoints", type=int, default=0,
        help="Truncate all timecourse NIfTIs to this many volumes (0 = no truncation). "
             "Use the minimum across sites (e.g. 144 for CMI+TReNDS) to enable "
             "timecourses spectra federation."
    )
    args = parser.parse_args()

    n = args.n_subjects
    tag = "all" if n == 0 else n
    created = []
    for cfg in VAULTS:
        dst = cfg["dst_template"].format(n=tag)
        create_subset(cfg["src"], dst, n, cfg["mat_format"], common_timepoints=args.common_timepoints)
        created.append(dst)

    print("\n=== Subset vaults ready ===")
    for d in created:
        print(f"  {d}")
    print()
    print("Update dockerRunVault.sh to point to these paths, or run:")
    print(f"  ./dockerRunVault.sh --n-subjects {n}")


if __name__ == "__main__":
    main()
