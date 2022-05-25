"""Adapted to script form from a notebook written by Brian Henn.

https://github.com/VulcanClimateModeling/explore/blob/master/brianh/2021-03-29-create-surface-radiation-reference/2021-03-29-create-surface-radiation-reference.ipynb
"""
import argparse

import fsspec
import numpy as np
import xarray as xr

from dask.distributed import Client
from vcm.safe import get_variables


TIMESTEP_SECONDS = 450
M_PER_MM = 1 / 1000.0
VARIABLES = ["DSWRFsfc_coarse", "DLWRFsfc_coarse", "USWRFsfc_coarse", "PRATEsfc_coarse"]
RENAME = {
    "grid_yt_coarse": "y",
    "grid_xt_coarse": "x",
    "DSWRFsfc_coarse": "override_for_time_adjusted_total_sky_downward_shortwave_flux_at_surface",
    "DLWRFsfc_coarse": "override_for_time_adjusted_total_sky_downward_longwave_flux_at_surface",
    "NSWRFsfc_coarse": "override_for_time_adjusted_total_sky_net_shortwave_flux_at_surface",
}


def add_total_precipitation(ds: xr.Dataset) -> xr.Dataset:
    total_precipitation = ds["PRATEsfc_coarse"] * M_PER_MM * TIMESTEP_SECONDS
    total_precipitation = total_precipitation.assign_attrs(
        {"long_name": "precipitation increment to land surface", "units": "m",}
    )
    ds["total_precipitation"] = total_precipitation
    return ds.drop_vars("PRATEsfc_coarse")


def add_net_shortwave(ds: xr.Dataset) -> xr.Dataset:
    net_shortwave = ds["DSWRFsfc_coarse"] - ds["USWRFsfc_coarse"]
    net_shortwave = net_shortwave.assign_attrs(
        {
            "long_name": "net shortwave radiative flux at surface (downward)",
            "units": "W/m^2",
        }
    )
    ds["NSWRFsfc_coarse"] = net_shortwave
    return ds.drop_vars("USWRFsfc_coarse")


def set_missing_units_attr(ds: xr.Dataset) -> xr.Dataset:
    for var in ds:
        da = ds[var]
        if "units" not in da.attrs:
            da.attrs["units"] = "unspecified"
    return ds


def cast_to_double(ds: xr.Dataset) -> xr.Dataset:
    new_ds = {}
    for name in ds.data_vars:
        if ds[name].dtype != np.float64:
            new_ds[name] = (
                ds[name]
                .astype(np.float64, casting="same_kind")
                .assign_attrs(ds[name].attrs)
            )
        else:
            new_ds[name] = ds[name]
    return xr.Dataset(new_ds).assign_attrs(ds.attrs)


def round_time_coord(ds: xr.Dataset) -> xr.Dataset:
    return ds.assign_coords(time=ds.time.dt.round("S"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source", help="The source dataset to derive prescriber inputs from."
    )
    parser.add_argument("destination", help="The path to output store.")

    args, _ = parser.parse_known_args()
    source = args.source
    destination = args.destination
    client = Client()

    source_mapper = fsspec.get_mapper(source)
    source_ds = xr.open_zarr(source_mapper, consolidated=True)
    ds = (
        get_variables(source_ds, VARIABLES)
        .pipe(set_missing_units_attr)
        .pipe(add_net_shortwave)
        .pipe(add_total_precipitation)
        .pipe(cast_to_double)
        .pipe(round_time_coord)
        .rename(RENAME)
    )

    destination_mapper = fsspec.get_mapper(destination)
    ds.to_zarr(destination_mapper, consolidated=True)
