import os
import subprocess
import tempfile

import cftime
import dask.diagnostics
import fsspec
import loaders
import numpy as np
import pandas as pd
import vcm
import xarray as xr
import xpartition


TIMESTEPS_PER_BATCH = 10
TRAINING_TIMES = [
    '20171124.053000',
    '20180121.173000',
    '20170816.233000',
    '20171004.233000',
    '20180409.083000',
    '20180726.023000',
    '20171229.113000',
    '20171101.233000',
    '20180715.023000',
    '20180622.233000'
]
VARIABLE_NAMES = [
    "air_temperature",
    "specific_humidity",
    "relative_humidity",
    "surface_geopotential",
    "land_sea_mask",
    "surface_diffused_shortwave_albedo",
    "shortwave_transmissivity_of_atmospheric_column",
    "override_for_time_adjusted_total_sky_downward_longwave_flux_at_surface",
    "dQ1",
    "dQ2",
    "is_land",
    "is_sea",
    "is_sea_ice",
    "cos_zenith_angle",
    "tapered_dQ1",
    "tapered_dQ2"
]


NUDGED = {
    "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-minus-4k-snoalb/fv3gfs_run",
    "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-unperturbed-snoalb/fv3gfs_run",
    "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-plus-4k-snoalb/fv3gfs_run",
    "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-06-14/n2f-25km-updated-plus-8k-snoalb/fv3gfs_run",
}


FINE_RES = {
    "Minus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/minus-4K/C384-to-C48-diagnostics",
    "Unperturbed": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/unperturbed/C384-to-C48-diagnostics",
    "Plus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/plus-4K/C384-to-C48-diagnostics",
    "Plus 8 K": "gs://vcm-ml-raw-flexible-retention/2022-06-02-two-year-C384-FV3GFS-simulations/plus-8K/C384-to-C48-diagnostics",
}


STATE_VARIABLES = [
    "air_temperature",
    "specific_humidity",
    "pressure_thickness_of_atmospheric_layer",
    "vertical_thickness_of_atmospheric_layer",
    "latitude",
    "longitude",
    "surface_geopotential",
    "land_sea_mask",
    "surface_diffused_shortwave_albedo"
]
NUDGING_VARIABLES = [
    "air_temperature_tendency_due_to_nudging",
    "specific_humidity_tendency_due_to_nudging",
]
FINE_RES_VARIABLES = ["DSWRFsfc", "DLWRFsfc", "USWRFsfc", "DSWRFtoa"]
DIAGS_VARIABLES = ["water_vapor_path"]
PHYSICS_TENDENCY_VARIABLES = ["tendency_of_air_temperature_due_to_fv3_physics", "tendency_of_specific_humidity_due_to_fv3_physics"]


RENAME = {
    "DSWRFsfc": "override_for_time_adjusted_total_sky_downward_shortwave_flux_at_surface",
    "DLWRFsfc": "override_for_time_adjusted_total_sky_downward_longwave_flux_at_surface",
    "NSWRFsfc": "override_for_time_adjusted_total_sky_net_shortwave_flux_at_surface",
    "air_temperature_tendency_due_to_nudging": "dQ1",
    "specific_humidity_tendency_due_to_nudging": "dQ2",
    "tendency_of_air_temperature_due_to_fv3_physics": "pQ1",
    "tendency_of_specific_humidity_due_to_fv3_physics": "pQ2"
}


def decode_time(timestamp):
    year = int(timestamp[:4])
    month = int(timestamp[4:6])
    day = int(timestamp[6:8])
    hour = int(timestamp[9:11])
    minute = int(timestamp[11:13])
    second = int(timestamp[13:15])
    return cftime.DatetimeJulian(year, month, day, hour, minute, second)


def decode_times(timestamps):
    return xr.CFTimeIndex([decode_time(timestamp) for timestamp in timestamps], name="time")


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


def open_data(dataset_times):
    state_after_timestep = open_tape_sequence(NUDGED, "state_after_timestep", concat_dim="dataset")
    state_after_timestep = state_after_timestep[STATE_VARIABLES]

    nudging_tendencies = open_tape_sequence(NUDGED, "nudging_tendencies", concat_dim="dataset")
    nudging_tendencies = nudging_tendencies[NUDGING_VARIABLES]

    fine_res = open_tape_sequence(FINE_RES, "gfsphysics_15min_coarse", concat_dim="dataset")
    fine_res = fine_res[FINE_RES_VARIABLES]

    physics_tendencies = open_tape_sequence(NUDGED, "physics_tendencies", concat_dim="dataset")
    physics_tendencies = physics_tendencies[PHYSICS_TENDENCY_VARIABLES]

    diags = open_tape_sequence(NUDGED, "diags", concat_dim="dataset")
    diags = diags[DIAGS_VARIABLES]

    merged = xr.merge(
        [state_after_timestep, nudging_tendencies, fine_res, physics_tendencies, diags],
        join="inner"
    )
    return merged.transpose(..., "dataset", "time")


def net_shortwave(
  downward_shortwave: xr.DataArray, upward_shortwave: xr.DataArray
) -> xr.DataArray:
    swnetrf_sfc = downward_shortwave - upward_shortwave
    return swnetrf_sfc.assign_attrs(
        {
            "long_name": "net shortwave surface radiative flux (down minus up)",
            "units": "W/m^2",
        }
    )


def shortwave_transmissivity(
    downward_shortwave_toa: xr.DataArray,
    downward_shortwave_sfc: xr.DataArray,
    fillna=False,
) -> xr.DataArray:
    transmissivity = downward_shortwave_sfc / downward_shortwave_toa
    if fillna:
        transmissivity = transmissivity.fillna(0.0)
    return transmissivity.assign_attrs(
        {
            "long_name": "ratio of downward shortave flux at the surface to downward shortwave flux at top of atmosphere",
            "units": "dimensionless",
        }
    )


def nudging_tendency_scale_factor(z, cutoff=25, rate=5):
    scaled = np.exp((z.isel(z=slice(None, cutoff)) - cutoff) / rate)
    unscaled = xr.ones_like(z.isel(z=slice(cutoff, None)))
    return xr.concat([scaled, unscaled], dim="z")


def relative_humidity(
    temperature: xr.DataArray,
    specific_humidity: xr.DataArray,
    pressure_thickness: xr.DataArray,
    vertical_thickness: xr.DataArray
) -> xr.DataArray:
    density = vcm.density(pressure_thickness, vertical_thickness)
    rh = vcm.relative_humidity(temperature, specific_humidity, density)
    return rh.rename("relative_humidity").assign_attrs(
        {
            "long_name": "relative humidity",
            "units": "dimensionless"
        }
    )


dataset_times = decode_times(TRAINING_TIMES)
ds = open_data(dataset_times)
ds = ds.assign(NSWRFsfc=net_shortwave(ds.DSWRFsfc, ds.USWRFsfc))
ds = ds.assign(
    shortwave_transmissivity_of_atmospheric_column=shortwave_transmissivity(
        ds.DSWRFtoa, ds.DSWRFsfc, fillna=True
    )
)
ds = ds.rename(RENAME)
scale_factor = nudging_tendency_scale_factor(ds.z)
ds = ds.assign(tapered_dQ1=scale_factor * ds.dQ1, tapered_dQ2=scale_factor * ds.dQ2)
rh = relative_humidity(
    ds.air_temperature,
    ds.specific_humidity,
    ds.pressure_thickness_of_atmospheric_layer,
    ds.vertical_thickness_of_atmospheric_layer
)
ds = ds.drop("vertical_thickness_of_atmospheric_layer")
ds = ds.assign(relative_humidity=rh)


@loaders.mapper_functions.register
def xarray_mapper_from_dataset(ds, time="time"):
    return loaders.mappers.XarrayMapper(ds, time=time)


mapper_config = loaders.MapperConfig("xarray_mapper_from_dataset", dict(ds=ds))
batches_from_mapper_config = loaders.BatchesFromMapperConfig(
    mapper_config=mapper_config,
    variable_names=VARIABLE_NAMES,
    timesteps_per_batch=TIMESTEPS_PER_BATCH,
    timesteps=TRAINING_TIMES,
    unstacked_dims=["z"],
    shuffle_samples=True,
)
batches = batches_from_mapper_config.load_batches(VARIABLE_NAMES)


with tempfile.TemporaryDirectory as tempdir:
    for i in range(1):
        batch_file = os.path.join(tempdir, f"batch-{i:05d}.nc")
        batch = batches[i].reset_index(dims_or_levels=["_fv3net_sample"]).chunk({"_fv3net_sample": -1, "z": -1})
        batch.to_netcdf(batch_file)
        call = [
            "gsutil",
            "-m",
            "cp",
            batch_file,
            "gs://vcm-ml-experiments/spencerc/2022-07-11-validation-data-batches/",
        ]
        subprocess.call(call)

