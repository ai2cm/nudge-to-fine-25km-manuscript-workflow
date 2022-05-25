import os

import fsspec
import pandas as pd
import vcm
import vcm.fv3
import xarray as xr


def open_tape(rundir, tape):
    """Open a zarr store from a particular run directory"""
    basename = f"{tape}.zarr"
    url = os.path.join(rundir, basename)
    mapper = fsspec.get_mapper(url)
    ds = xr.open_zarr(mapper)
    return vcm.fv3.standardize_fv3_diagnostics(ds)


def open_tape_sequence(rundirs, tape, concat_dim="climate"):
    """Open a tape from a sequence of run directories"""
    datasets = {}
    for key, rundir in rundirs.items():
        datasets[key] = open_tape(rundir, tape)
    index = pd.Index(datasets.keys(), name=concat_dim)
    return xr.concat(datasets.values(), dim=index)


def open_remote_nc(url):
    fs, *_ = fsspec.get_fs_token_paths(url)
    return vcm.open_remote_nc(fs, url)