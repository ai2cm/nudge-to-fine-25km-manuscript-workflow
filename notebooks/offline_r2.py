import logging

import dask.diagnostics
import fsspec
import fv3fit
import numpy as np
import pandas as pd
import vcm
import vcm.catalog
import xarray as xr
import xpartition

import times


logging.basicConfig(level=logging.INFO)


TEST_DATA = "gs://vcm-ml-experiments/spencerc/2022-03-12/n2f-25km-tapered-25-snoalb-nudging-tendencies-and-fluxes.zarr"
MODELS = {
    0: "gs://vcm-ml-experiments/spencerc/2022-03-12-nudge-to-25-km-ml-models/tq-nn-snoalb-tapered-clipped-25-seed-0",
    1: "gs://vcm-ml-experiments/spencerc/2022-03-12-nudge-to-25-km-ml-models/tq-nn-snoalb-tapered-clipped-25-seed-1",
    2: "gs://vcm-ml-experiments/spencerc/2022-03-12-nudge-to-25-km-ml-models/tq-nn-snoalb-tapered-clipped-25-seed-2",
    3: "gs://vcm-ml-experiments/spencerc/2022-03-12-nudge-to-25-km-ml-models/tq-nn-snoalb-tapered-clipped-25-seed-3"
}
LOADED_MODELS = {k: fv3fit.load(v) for k, v in MODELS.items()}
TARGETS = ["dQ1", "dQ2"]
TESTING_TIMES_FILE = "../workflows/ml-training/test.json"
ALL_CLIMATE_DESTINATION = "offline-r2-all-climates.zarr"
PER_CLIMATE_DESTINATION = "offline-r2-per-climate.zarr"


def _predict_kernel(ds, model):
    return model.predict(ds).transpose(*ds.dims)


def predict(ds, model, template):
    """A dask-compatible version of model.predict"""
    template = template.transpose(*ds.dims)
    return xr.map_blocks(
        _predict_kernel,
        ds,
        args=(model,),
        template=template
    )


def interpolate(ds, delp):
    return vcm.interpolate_to_pressure_levels(ds, delp, dim="z")


def weighted_groupby_bins(ds, weights, lat, bins=np.arange(-90, 91, 2)):
    numerator = (weights * ds).groupby_bins(lat, bins=bins).sum()
    denominator = weights.groupby_bins(lat, bins=bins).sum()
    result = numerator / denominator
    lat_mid = [lat.item().mid for lat in result["lat_bins"]]
    return result.assign_coords(lat_bins=lat_mid).rename({"lat_bins": "lat"})


def weighted_groupby_bins_variance(ds, mean, weights, lat, bins=np.arange(-90, 91, 2)):
    a = weighted_groupby_bins(ds ** 2, weights, lat, bins=bins)
    b = -2 * mean * weighted_groupby_bins(ds, weights, lat, bins=bins)
    c = mean ** 2
    return a + b + c


def coefficient_of_determination_by_lat(target, prediction, grid, bins=np.arange(-90, 91, 2)):
    error = prediction - target
    weights, _ = xr.broadcast(grid.area, error.mean("time"))
    with dask.diagnostics.ProgressBar():
        mean = weighted_groupby_bins(target.mean("time"), weights, grid.lat, bins=bins).mean("dataset")
        mean_square_error = weighted_groupby_bins((error ** 2).mean("time"), weights, grid.lat, bins=bins).mean("dataset")
        variance = weighted_groupby_bins_variance(target, mean, weights, grid.lat, bins=bins).mean(["time", "dataset"])
    return 1.0 - (mean_square_error / variance)


def coefficient_of_determination_by_lat_dataset(target, prediction, grid, bins=np.arange(-90, 91, 2)):
    error = prediction - target
    weights, _ = xr.broadcast(grid.area, error.mean("time"))
    with dask.diagnostics.ProgressBar():
        mean = weighted_groupby_bins(target.mean("time"), weights, grid.lat, bins=bins)
        mean_square_error = weighted_groupby_bins((error ** 2).mean("time"), weights, grid.lat, bins=bins)
        variance = weighted_groupby_bins_variance(target, mean, weights, grid.lat, bins=bins).mean(["time"])
    return 1.0 - (mean_square_error / variance)


def write_via_xpartition(ds, destination):
    RANKS = ds.sizes["seed"]
    mapper = fsspec.get_mapper(destination)
    ds.partition.initialize_store(mapper)
    for rank in range(RANKS):
        logging.info(f"Writing rank {rank + 1} / {RANKS} to {destination}")
        with dask.diagnostics.ProgressBar():
            ds.partition.write(mapper, RANKS, ["seed"], rank)


if __name__ == "__main__":
    grid = vcm.catalog.catalog["grid/c48"].to_dask()
    testing_times = times.open_times(TESTING_TIMES_FILE)
    test_data = xr.open_zarr(fsspec.get_mapper(TEST_DATA)).sel(time=testing_times)
    test_data = test_data.assign(
        cos_zenith_angle=vcm.cos_zenith_angle(
            test_data.time,
            grid.lon.load(),
            grid.lat.load()
        )
    )
    targets = test_data[TARGETS]

    prediction_datasets = []
    for seed, model in LOADED_MODELS.items():
        prediction_datasets.append(predict(test_data, model, targets))
    predictions = xr.concat(prediction_datasets, dim=pd.Index(LOADED_MODELS.keys(), name="seed"))

    interpolated_targets = interpolate(targets, test_data.pressure_thickness_of_atmospheric_layer)
    interpolated_predictions = interpolate(predictions, test_data.pressure_thickness_of_atmospheric_layer)

    all_climates = coefficient_of_determination_by_lat(interpolated_targets, interpolated_predictions, grid)
    write_via_xpartition(all_climates, ALL_CLIMATE_DESTINATION)

    per_climate = coefficient_of_determination_by_lat_dataset(interpolated_targets, interpolated_predictions, grid)
    per_climate = per_climate.assign_coords(dataset=per_climate.dataset.astype(str))
    write_via_xpartition(per_climate, PER_CLIMATE_DESTINATION)
