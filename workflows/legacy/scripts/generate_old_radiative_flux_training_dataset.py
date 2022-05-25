import argparse
import json

import dask.diagnostics
import cftime
import fsspec
import numpy as np
import xarray as xr
import xpartition
import zarr

from typing import List

from vcm.fv3.metadata import standardize_fv3_diagnostics
from vcm.safe import get_variables


VARIABLES = ["DSWRFsfc", "DLWRFsfc", "USWRFsfc", "DSWRFtoa"]
RENAME = {
    "DSWRFsfc": "override_for_time_adjusted_total_sky_downward_shortwave_flux_at_surface",
    "DLWRFsfc": "override_for_time_adjusted_total_sky_downward_longwave_flux_at_surface",
    "NSWRFsfc": "override_for_time_adjusted_total_sky_net_shortwave_flux_at_surface",
}


def _remove_coarse(ds: xr.Dataset) -> xr.Dataset:
    rename = {}
    for variable in ds.variables:
        if variable.endswith("_coarse"):
            rename[variable] = variable.replace("_coarse", "")
    return ds.rename(rename)


def _load_dataset(path: str) -> xr.Dataset:
    mapper = fsspec.get_mapper(path)
    return xr.open_zarr(mapper, consolidated=True)


def _load_datasets(paths: List[str]) -> xr.Dataset:
    if len(paths) == 1:
        (path,) = paths
        return _load_dataset(path)
    else:
        return xr.concat([_load_dataset(path) for path in paths], dim="dataset")


def _verification_fluxes(datasets: List[str], fillna=False) -> xr.Dataset:
    ds = _load_datasets(datasets)
    ds = _remove_coarse(ds)
    ds = standardize_fv3_diagnostics(ds)
    ds = get_variables(ds, VARIABLES)
    ds = ds.assign(
        {
            "NSWRFsfc": _net_shortwave(
                ds["DSWRFsfc"], ds["USWRFsfc"]
            )
        }
    ).drop_vars("USWRFsfc")
    ds = ds.assign(
        {"shortwave_transmissivity": _shortwave_transmissivity(ds["DSWRFtoa"], ds["DSWRFsfc"], fillna=fillna)}
    )
    ds = ds.assign({"DSWRFtoa_squared": ds.DSWRFtoa ** 2})
    return _clear_encoding(ds.rename(RENAME))


def _net_shortwave(
    downward_shortwave: xr.DataArray, upward_shortwave: xr.DataArray
) -> xr.DataArray:
    swnetrf_sfc = downward_shortwave - upward_shortwave
    return swnetrf_sfc.assign_attrs(
        {
            "long_name": "net shortwave surface radiative flux (down minus up)",
            "units": "W/m^2",
        }
    )


def _shortwave_transmissivity(downward_shortwave_toa: xr.DataArray, downward_shortwave_sfc: xr.DataArray, fillna=False) -> xr.DataArray:
    transmissivity = downward_shortwave_sfc / downward_shortwave_toa
    if fillna:
        transmissivity = transmissivity.fillna(0.0)
    return transmissivity.assign_attrs(
        {
            "long_name": "ratio of downward shortave flux at the surface to downward shortwave flux at top of atmosphere",
            "units": "dimensionless"
        }
    )


def _total_precipitation(precipitation_rate: xr.DataArray) -> xr.DataArray:
    timestep_seconds = 450.0
    m_per_mm = 1 / 1000.0
    total_precipitation = precipitation_rate * m_per_mm * timestep_seconds
    return total_precipitation.assign_attrs(
        {"long_name": "precipitation increment to land surface", "units": "m",}
    )


def _clear_encoding(ds: xr.Dataset) -> xr.Dataset:
    for var in ds.data_vars:
        ds[var].encoding = {}
    return ds


def _state(paths: List[str]) -> xr.Dataset:
    ds = _load_datasets(paths)
    return standardize_fv3_diagnostics(ds)


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


def _rechunk(ds, chunks_2d, chunks_3d):
    for data_var in ds:
        if "z" in ds[data_var].dims and "time" in ds[data_var].dims:
            ds[data_var] = ds[data_var].chunk(chunks_3d)
        elif "time" in ds[data_var].dims:
            ds[data_var] = ds[data_var].chunk(chunks_2d)
    return ds


def _load_timesteps(timesteps):
    with open(timesteps, "r") as file:
        timestamps = json.load(file)
    times = []
    for time in timestamps:
        year = int(time[:4])
        month = int(time[4:6])
        day = int(time[6:8])
        hour = int(time[9:11])
        minute = int(time[11:13])
        second = int(time[13:15])
        t = cftime.DatetimeJulian(year, month, day, hour, minute, second)
        times.append(t)
    return times


def _load_all_timesteps(files):
    times = []
    for file in files:
        times.extend(_load_timesteps(file))
    return sorted(list(set(times)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fine-res", help="fine resolution dataset(s)", nargs="+")
    parser.add_argument(
        "--coarse-res", help="coarse resolution dataset(s)", nargs="+"
    )
    parser.add_argument("--timesteps", help="timesteps json", nargs="+")
    parser.add_argument("--output", help="location of output")
    parser.add_argument(
        "--fill-nans-with-zeros",
        help="whether to fill NaN values with zeros",
        action="store_true"
    )
    args, _ = parser.parse_known_args()

    verification_ds = _verification_fluxes(args.fine_res, fillna=args.fill_nans_with_zeros)
    state_ds = _state(args.coarse_res)
    ds = xr.merge([verification_ds, state_ds], join="inner")

    times = _load_all_timesteps(args.timesteps)
    ds = ds.sel(time=times)

    ds = _rechunk(ds, {"time": 96}, {"time": 8})
    ds = _clear_encoding(ds)
    ds = cast_to_double(ds)
    three_dimensional_vars = [v for v in ds.data_vars if "z" in ds[v].dims and v not in ["air_temperature", "specific_humidity", "pressure_thickness_of_atmospheric_layer"]]
    ds = ds.drop(three_dimensional_vars)

    mapper = fsspec.get_mapper(args.output)
    ds.partition.initialize_store(mapper)
    for i in range(16):
        with dask.diagnostics.ProgressBar():
            ds.partition.write(mapper, 16, ["time"], i)
    zarr.convenience.consolidate_metadata(mapper)
