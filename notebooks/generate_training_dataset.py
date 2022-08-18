import argparse
import logging
import os

import dask.diagnostics
import fsspec
import numpy as np
import pandas as pd
import vcm
import xarray as xr
import xpartition

import cloud
import times


DIRNAME = os.path.dirname(__file__)
TRAINING_TIMES_FILE = os.path.join(DIRNAME, "../workflows/ml-training/train.json")
TESTING_TIMES_FILE = os.path.join(DIRNAME, "../workflows/ml-training/test.json")


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


def open_times(train_file, test_file):
    training_times = times.open_times(train_file)
    testing_times = times.open_times(test_file)
    return training_times.append(testing_times)


def open_data(dataset_times):
    state_after_timestep = cloud.open_tape_sequence(NUDGED, "state_after_timestep", concat_dim="dataset")
    state_after_timestep = state_after_timestep[STATE_VARIABLES]
    state_after_timestep = state_after_timestep.sel(time=dataset_times)

    nudging_tendencies = cloud.open_tape_sequence(NUDGED, "nudging_tendencies", concat_dim="dataset")
    nudging_tendencies = nudging_tendencies[NUDGING_VARIABLES]
    nudging_tendencies = nudging_tendencies.sel(time=dataset_times)

    fine_res = cloud.open_tape_sequence(FINE_RES, "gfsphysics_15min_coarse", concat_dim="dataset")
    fine_res = fine_res[FINE_RES_VARIABLES]
    fine_res = fine_res.sel(time=dataset_times)
    
    physics_tendencies = cloud.open_tape_sequence(NUDGED, "physics_tendencies", concat_dim="dataset")
    physics_tendencies = physics_tendencies[PHYSICS_TENDENCY_VARIABLES]
    physics_tendencies = physics_tendencies.sel(time=dataset_times)

    diags = cloud.open_tape_sequence(NUDGED, "diags", concat_dim="dataset")
    diags = diags[DIAGS_VARIABLES]
    diags = diags.sel(time=dataset_times)

    merged = xr.merge([state_after_timestep, nudging_tendencies, fine_res, physics_tendencies, diags])
    merged = merged.chunk({"time": 10, "dataset": 1})
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
    specific_humidity: xr.DataArray,
    temperature: xr.DataArray,
    pressure_thickness: xr.DataArray,
    vertical_thickness: xr.DataArray
) -> xr.DataArray:
    density = vcm.density(pressure_thickness, vertical_thickness)
    rh = vcm.relative_humidity(specific_humidity, temperature, density)
    return rh.rename("relative_humidity").assign_attrs(
        {
            "long_name": "relative humidity",
            "units": "dimensionless"
        }
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", help="The path to output store.")

    args, _ = parser.parse_known_args()
    destination = args.destination

    dataset_times = open_times(TRAINING_TIMES_FILE, TESTING_TIMES_FILE)
    ds = open_data(dataset_times)
    ds = ds.assign(NSWRFsfc=net_shortwave(ds.DSWRFsfc, ds.USWRFsfc))
    ds = ds.assign(
        shortwave_transmissivity_of_atmospheric_column=shortwave_transmissivity(
            ds.DSWRFtoa, ds.DSWRFsfc, fillna=True
        )
    )
    ds = ds.rename(RENAME)
    scale_factor = nudging_tendency_scale_factor(ds.z)
    ds = ds.assign(dQ1=scale_factor * ds.dQ1, dQ2=scale_factor * ds.dQ2)
    rh = relative_humidity(
        ds.specific_humidity,
        ds.air_temperature,
        ds.pressure_thickness_of_atmospheric_layer,
        ds.vertical_thickness_of_atmospheric_layer
    )
    ds = ds.drop("vertical_thickness_of_atmospheric_layer")
    ds = ds.assign(relative_humidity=rh)

    RANKS = 50
    output_mapper = fsspec.get_mapper(destination)
    ds.partition.initialize_store(output_mapper)
    for i in range(RANKS):
        logging.info(f"Writing rank {i + 1} / {RANKS} to {destination}")
        with dask.diagnostics.ProgressBar():
            ds.partition.write(output_mapper, RANKS, ["time"], i)
