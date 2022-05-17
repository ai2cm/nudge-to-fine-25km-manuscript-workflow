import argparse
import logging
import os
import subprocess
import tempfile

import fsspec
import pandas as pd
import xarray as xr

import vcm
import vcm.fv3
import vcm.cubedsphere

from vcm.cubedsphere.coarsen_restarts import _area_weighted_mean_over_dominant_sfc_type, _compute_arguments_for_complex_sfc_coarsening, _doubles_to_floats


DESCRIPTION = """
Replace the maximum snow albedo in a given set of coarse restart
netCDF files with the area-weighted average of the maximum snow albedo
in a fine resolution set of coarse restart files.
"""


def open_remote_tiles(stem):
    logging.info(f"Loading files from {stem}")
    files = [f"{stem}.tile{tile}.nc" for tile in range(1, 7)]
    sample, *_ = files
    fs, *_ = fsspec.get_fs_token_paths(sample)
    datasets = []
    for file in files:
        ds = vcm.open_remote_nc(fs, file)
        datasets.append(ds)
    return xr.concat(datasets, dim=pd.Index(range(6), name="tile"))


def compute_coarsening_factor(fine, coarse):
    fine_resolution = fine.sizes["xaxis_1"]
    coarse_resolution = coarse.sizes["xaxis_1"]
    if fine_resolution % coarse_resolution:
        raise ValueError(f"Coarse resolution {coarse_resolution} does not evenly divide fine resolution {fine_resolution}.")
    else:
        return fine_resolution // coarse_resolution


def write_tiles(ds, stem):
    for tile in range(6):
        filename = f"{stem}.tile{tile + 1}.nc"
        ds.isel(tile=tile).to_netcdf(filename)


def gsutil(source, destination):
    subprocess.call(["gsutil", "-m", "cp", source, destination])


def patch(fine_reference, fine_grid_area, coarse_reference, destination, timestamp):
    fine_reference = open_remote_tiles(fine_reference).drop(["geolon", "geolat"], errors="ignore")
    fine_area = open_remote_tiles(fine_grid_area).area
    coarse_stem = os.path.join(coarse_reference, timestamp, f"{timestamp}.sfc_data")
    coarse_reference = open_remote_tiles(coarse_stem)
    coarsening_factor = compute_coarsening_factor(fine_reference, coarse_reference)

    coarsening_arguments = _compute_arguments_for_complex_sfc_coarsening(
        fine_reference,
        coarsening_factor
    )
    is_dominant_surface_type = coarsening_arguments["is_dominant_surface_type"]
    coarse_snoalb = _area_weighted_mean_over_dominant_sfc_type(
        fine_reference.snoalb,
        coarsening_factor,
        fine_area,
        is_dominant_surface_type
    ).compute()

    patched_coarse_files = coarse_reference.copy(deep=True)
    patched_coarse_files["snoalb"] = coarse_snoalb
    patched_coarse_files = _doubles_to_floats(patched_coarse_files)

    with tempfile.TemporaryDirectory() as directory:
        stem = os.path.join(directory, f"{timestamp}.sfc_data")
        write_tiles(patched_coarse_files, stem)
        destination = os.path.join(destination, timestamp)
        gsutil(os.path.join(args.coarse_reference, timestamp, "*"), destination)
        logging.info(f"Writing patched sfc_data files to {destination}")
        gsutil(f"{stem}*", destination)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("fine_reference", type=str, help="Stem of fine restart files")
    parser.add_argument("fine_grid_area", type=str, help="Stem of fine grid area")
    parser.add_argument("coarse_reference", type=str, help="Directory of coarse restart files")
    parser.add_argument("destination", type=str, help="Directory to copy resulting coarse restart files")
    parser.add_argument("timestamp", type=str, nargs="+", help="Timestamp of restart files")
    args, _ = parser.parse_known_args()

    for timestamp in args.timestamp:
        patch(args.fine_reference, args.fine_grid_area, args.coarse_reference, args.destination, timestamp)
