import datetime
import logging

import dask.diagnostics
import numpy as np
import pandas as pd
import vcm.catalog
import xarray as xr
import xhistogram.xarray as xhistogram
import xpartition

import cloud


logging.basicConfig(level=logging.INFO)


CLIMATES = ["Minus 4 K", "Unperturbed", "Plus 4 K", "Plus 8 K"]
SECONDS_PER_DAY = 86400
SPATIAL_DIMS = ["x", "y", "tile"]


def compute_diurnal_cycles(
    roots,
    configuration,
    tape,
    time_slice,
    variable,
    compute_nudging_precip=False,
    time_offset=None
):
    dataarrays = {}
    for climate, root in roots.items():
        logging.info(f"Setting up diurnal cycle calculation for {root}")
        ds = cloud.open_tape(root, tape)
        if compute_nudging_precip:
            ds = compute_nudging_precipitation_diagnostics(ds)
        if time_offset is not None:
            # The fine-resolution fields are offset by seven minutes and thirty
            # seconds since the time-interval average fortran physics
            # diagnostics are output with labels at the end of the interval.  In
            # practice this minor offset doesn't make a material difference when
            # computing the diurnal cycle, but we include it here to be most
            # precise.  The precipitation rates from the other datasets do not
            # need an offset added since they were output by the Python wrapper.
            ds = ds.assign_coords(time=ds.time + time_offset)
        da = SECONDS_PER_DAY * ds[variable].sel(time=time_slice)
        da = da.assign_coords(configuration=configuration)
        da = da.expand_dims(["configuration"])
        diurnal_cycle = compute_diurnal_cycle(da)
        dataarrays[climate] = diurnal_cycle
    index = pd.Index(dataarrays.keys(), name="climate")
    return xr.concat(dataarrays.values(), dim=index)


def compute_nudging_precipitation_diagnostics(ds):
    unrectified_nudging_precip = ds.physics_precip - ds.net_moistening_due_to_nudging
    rectified_nudging_precip = xr.where(unrectified_nudging_precip > 0, unrectified_nudging_precip, 0)
    return ds.assign(
        nudging_precip=rectified_nudging_precip,
        unrectified_nudging_precip=unrectified_nudging_precip
    )


def compute_solar_time(longitude, time, time_chunk_size=96):
    offset = (longitude * 24 * 3600 / 360).astype("timedelta64[s]")
    time_as_datetime64 = xr.DataArray(
        time.indexes["time"].to_datetimeindex(unsafe=True),
        dims=["time"]
    ).chunk({"time": time_chunk_size})
    local_time = (time_as_datetime64 + offset) - (time_as_datetime64 + offset).dt.floor("D")
    return (local_time.rename("local_time") / np.timedelta64(1, "h")).assign_coords(time=time)


def compute_weights(grid, land_mask):
    return xr.concat(
        [
            grid.area,
            grid.area.where(land_mask).fillna(0.0),
            grid.area.where(~land_mask).fillna(0.0),   
            grid.area.where(np.abs(grid.lat) <= 60).fillna(0.0),
            grid.area.where(land_mask).fillna(0.0).where(np.abs(grid.lat) <= 60).fillna(0.0),
            grid.area.where(~land_mask).fillna(0.0).where(np.abs(grid.lat) <= 60).fillna(0.0)
        ],
        dim=pd.Index(
            [
                "global", 
                "land",
                "ocean/sea-ice",
                "global |lat| <= 60",
                "land |lat| <= 60",
                "ocean/sea-ice |lat| <= 60"
            ],
            name="region"
        )
    )


def compute_diurnal_cycle(
    precipitation,
    time_dim="time",
    spatial_dims=SPATIAL_DIMS,
    local_time_bins=np.arange(25)
):
    grid = vcm.catalog.catalog["grid/c48"].to_dask()
    land_mask = vcm.catalog.catalog["landseamask/c48"].to_dask().land_sea_mask == 1
    weights = compute_weights(grid, land_mask)
    longitude = grid.lon
    local_time = compute_solar_time(
        longitude,
        precipitation[time_dim],
        time_chunk_size=precipitation.chunks[precipitation.get_axis_num(time_dim)]
    )
    local_time = local_time.broadcast_like(precipitation).rename("local_time")
    weights = weights.broadcast_like(precipitation).rename("weights")
    precipitation = precipitation.rename("precipitation")
    unified = xr.merge([precipitation, weights, local_time]).unify_chunks()

    dims = spatial_dims + [time_dim]
    
    numerator = xhistogram.histogram(
        unified.local_time,
        bins=[local_time_bins],
        weights=unified.weights * unified.precipitation,
        dim=dims
    )
    denominator = xhistogram.histogram(
        unified.local_time,
        bins=[local_time_bins],
        weights=unified.weights,
        dim=dims
    )
    return (numerator / denominator).rename("precipitation").assign_coords(region=weights.region)


DATASETS = {
    "ML-corrected seed 1": {
        "roots": {
            "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-minus-4k-seed-1/fv3gfs_run",
            "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-unperturbed-seed-1/fv3gfs_run",
            "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-plus-4k-seed-1/fv3gfs_run",
            "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-06-30/n2f-25km-ml-corrected-updated-v3-plus-8k-seed-1/fv3gfs_run"
        },
        "tape": "diags",
        "time_slice": slice("2018-11", "2023-10"),
        "variable": "total_precipitation_rate"
    },
    "Baseline": {
        "roots": {
            "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-minus-4k-snoalb/fv3gfs_run",
            "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-unperturbed-snoalb/fv3gfs_run",
            "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-plus-4k-snoalb/fv3gfs_run",
            "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-07-01/n2f-25km-baseline-updated-plus-8k-snoalb/fv3gfs_run",
        },
        "tape": "diags",
        "time_slice": slice("2018-11", "2023-10"),
        "variable": "total_precipitation_rate"
    },
    "Nudged": {
        "roots": {
            "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-minus-4k-snoalb/fv3gfs_run",
            "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-unperturbed-snoalb/fv3gfs_run",
            "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-plus-4k-snoalb/fv3gfs_run",
            "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-06-14/n2f-25km-updated-plus-8k-snoalb/fv3gfs_run"
        },
        "tape": "diags",
        "time_slice": slice("2018-08", "2019-07"),
        "compute_nudging_precip": True,
        "variable": "unrectified_nudging_precip"
    },
    "Fine resolution (year one)": {
        "roots": {
            "Minus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/minus-4K/C384-to-C48-diagnostics",
            "Unperturbed": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/unperturbed/C384-to-C48-diagnostics",
            "Plus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/plus-4K/C384-to-C48-diagnostics",
            "Plus 8 K": "gs://vcm-ml-raw-flexible-retention/2022-06-02-two-year-C384-FV3GFS-simulations/plus-8K/C384-to-C48-diagnostics"
        },
        "tape": "gfsphysics_15min_coarse",
        "time_slice": slice("2017-08", "2018-07"),
        "variable": "PRATEsfc",
        "time_offset": datetime.timedelta(minutes=-7, seconds=-30)
    },
    "Fine resolution (year two)": {
        "roots": {
            "Minus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/minus-4K/C384-to-C48-diagnostics",
            "Unperturbed": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/unperturbed/C384-to-C48-diagnostics",
            "Plus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/plus-4K/C384-to-C48-diagnostics",
            "Plus 8 K": "gs://vcm-ml-raw-flexible-retention/2022-06-02-two-year-C384-FV3GFS-simulations/plus-8K/C384-to-C48-diagnostics"
        },
        "tape": "gfsphysics_15min_coarse",
        "time_slice": slice("2018-08", "2019-07"),
        "variable": "PRATEsfc",
        "time_offset": datetime.timedelta(minutes=-7, seconds=-30)
    }
}


if __name__ == "__main__":
    dataarrays = []
    for configuration, metadata in DATASETS.items():
        ds = compute_diurnal_cycles(
            metadata["roots"],
            configuration,
            metadata["tape"],
            metadata["time_slice"],
            metadata["variable"],
            metadata.get("compute_nudging_precip", False),
            metadata.get("time_offset", None)
        )
        dataarrays.append(ds)
    ds = xr.concat(dataarrays, dim="configuration").to_dataset()

    ds.partition.initialize_store("simulated_diurnal_cycles.zarr")
    ranks = 120
    for i in range(ranks):
        logging.info(f"Writing rank {i + 1} / {ranks}")
        with dask.diagnostics.ProgressBar():
            ds.partition.write("simulated_diurnal_cycles.zarr", ranks, ["climate", "configuration", "region"], i)
