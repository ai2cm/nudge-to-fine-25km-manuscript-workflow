import dask.diagnostics
import fsspec
import numpy as np
import pandas as pd
import vcm
import vcm.catalog
import xarray as xr

ML_CORRECTED_POST_PROCESSED_DATA = fsspec.get_mapper("gs://vcm-ml-experiments/spencerc/2022-08-15-n2f-25-km/post-processed-data-v5.zarr")
OTHER_POST_PROCESSED_DATA = fsspec.get_mapper("gs://vcm-ml-experiments/spencerc/2022-08-04-n2f-25-km/post-processed-data-v4.zarr")
SPATIAL_DIMS = ["x", "y", "tile"]
ZONAL_DIMS = ["lat", "pressure"]
AS_AUG_CONFIGURATIONS = ["Fine resolution (year one)", "Fine resolution (year two)", "Nudged"]
AS_NOV_CONFIGURATIONS = ["Baseline"] + [f"ML-corrected seed {seed}" for seed in range(4)]
VARIABLES_2D = ["surface_temperature", "total_precipitation_rate", "net_surface_radiative_flux", "samples"]
VARIABLES_3D = ["air_temperature", "specific_humidity", "pressure_thickness_of_atmospheric_layer"]
VARIABLES = VARIABLES_2D + VARIABLES_3D
SECONDS_PER_DAY = 86400


def weighted_resample(ds, weights, freq):
    weights = weights.where(ds.notnull())
    return (
        (ds * weights).resample(time=freq).sum(skipna=True) /
        weights.resample(time=freq).sum(skipna=True)
    )


def compute_spatial_mean(bias, weights, dims=SPATIAL_DIMS):
    return bias.weighted(weights).mean(dims)


def compute_spatial_mae(bias, weights, dims=SPATIAL_DIMS):
    return np.abs(bias).weighted(weights).mean(dims)


def compute_spatial_rmse(bias, weights, dims=SPATIAL_DIMS):
    return np.sqrt((bias ** 2).weighted(weights).mean(dims))


def compute_spatial_metrics(bias, weights):
    mean = compute_spatial_mean(bias, weights)
    rmse = compute_spatial_rmse(bias, weights)
    mae = compute_spatial_mae(bias, weights)
    index = pd.Index(["mean", "rmse", "mae"], name="metric")
    return xr.concat([mean, rmse, mae], dim=index)


def compute_zonal_metrics(bias, weights):
    mean = compute_spatial_mean(bias, weights, dims=ZONAL_DIMS)
    rmse = compute_spatial_rmse(bias, weights, dims=ZONAL_DIMS)
    mae = compute_spatial_mae(bias, weights, dims=ZONAL_DIMS)
    index = pd.Index(["mean", "rmse", "mae"], name="metric")
    return xr.concat([mean, rmse, mae], dim=index)


def compute_spatial_weights():
    grid = vcm.catalog.catalog["grid/c48"].to_dask().load()
    land_mask = vcm.catalog.catalog["landseamask/c48"].to_dask().land_sea_mask.load() == 1
    return xr.concat(
        [
            grid.area,
            grid.area.where(land_mask).fillna(0.0),
            grid.area.where(~land_mask).fillna(0.0)
        ],
        dim=pd.Index(["global", "land", "ocean/sea-ice"], name="region")
    )


def estimate_pressure_thickness_from_midpoints(pressure):
    bounds = (
        pressure.isel(pressure=slice(None, -1)).drop("pressure") + 
        pressure.isel(pressure=slice(1, None)).drop("pressure")
    ) / 2
    upper_bound = xr.DataArray([0], dims=["pressure"])
    lower_bound = xr.DataArray([pressure.isel(pressure=-1)], dims=["pressure"])
    return xr.concat([upper_bound, bounds, lower_bound], dim="pressure").diff("pressure")


def compute_zonal_weights(latitude, pressure):
    cosine_latitude = np.cos(np.deg2rad(latitude))
    pressure_thickness = estimate_pressure_thickness_from_midpoints(pressure)
    return xr.concat(
        [
            cosine_latitude * pressure_thickness,
            cosine_latitude * pressure_thickness.where(pressure >= 200).fillna(0.0)
        ],
        pd.Index(["Global", "Below tapering region"], name="zonal_region")
    )


def compute_annual_mean(ds):
    as_aug = weighted_resample(
        ds.sel(configuration=AS_AUG_CONFIGURATIONS),
        ds.sel(configuration=AS_AUG_CONFIGURATIONS).samples,
        "AS-AUG"
    ).sel(time=slice("2018", "2022"))
    as_nov = weighted_resample(
        ds.sel(configuration=AS_NOV_CONFIGURATIONS),
        ds.sel(configuration=AS_NOV_CONFIGURATIONS).samples,
        "AS-NOV"
    ).sel(time=slice("2018", "2022"))
    as_aug = as_aug.assign_coords(time=as_nov.time)
    return xr.concat([as_aug, as_nov], dim="configuration")


def compute_bias(ds):
    bias_year_one = ds - ds.sel(configuration="Fine resolution (year one)").sel(time="2018").squeeze("time")
    bias_year_two = ds - ds.sel(configuration="Fine resolution (year two)").sel(time="2018").squeeze("time")
    index = pd.Index(["Year one", "Year two"], name="validation_year")
    return xr.concat([bias_year_one, bias_year_two], dim=index)


def compute_zonal_mean_bias(ds):
    grid = vcm.catalog.catalog["grid/c48"].to_dask().load()
    pressure_interpolated = vcm.interpolate_to_pressure_levels(
        ds,
        ds.pressure_thickness_of_atmospheric_layer,
        dim="z"
    )
    zonal_mean = vcm.select.zonal_average_approximate(grid.lat, pressure_interpolated)
    zonal_mean = zonal_mean.assign_coords(sinlat=np.sin(np.deg2rad(zonal_mean.lat)))
    zonal_mean = zonal_mean.assign_coords(pressure=zonal_mean.pressure / 100.0)  # Convert to hPa

    bias_year_one = zonal_mean - zonal_mean.sel(configuration="Fine resolution (year one)").sel(time="2018").squeeze("time")
    bias_year_two = zonal_mean - zonal_mean.sel(configuration="Fine resolution (year two)").sel(time="2018").squeeze("time")
    index = pd.Index(["Year one", "Year two"], name="validation_year")
    return xr.concat([bias_year_one, bias_year_two], dim=index)


def net_surface_radiative_flux(ds):
    return (
        ds.downward_shortwave_radiative_flux_at_surface + 
        ds.downward_longwave_radiative_flux_at_surface - 
        ds.upward_shortwave_radiative_flux_at_surface - 
        ds.upward_longwave_radiative_flux_at_surface
    )


def compute_climate_change_pattern(ds):
    colder_climates = ["Minus 4 K", "Unperturbed", "Plus 4 K"]
    warmer_climates = ["Unperturbed", "Plus 4 K", "Plus 8 K"]
    climate_change_coord = [f"{warmer} minus {colder}" for colder, warmer in zip(colder_climates, warmer_climates)]
    difference = (
        ds.sel(climate=warmer_climates).drop("climate") - 
        ds.sel(climate=colder_climates).drop("climate")
    )
    return difference.assign_coords(climate=climate_change_coord)


if __name__ == "__main__":
    ml = xr.open_zarr(ML_CORRECTED_POST_PROCESSED_DATA)
    other = xr.open_zarr(OTHER_POST_PROCESSED_DATA)
    other = other.sel(configuration=[c for c in other.configuration.values if "ML-corrected" not in c])
    ds = xr.concat([ml, other], dim="configuration")
    ds["net_surface_radiative_flux"] = net_surface_radiative_flux(ds)
    ds["total_precipitation_rate"] = SECONDS_PER_DAY * ds.total_precipitation_rate
    ds = ds[VARIABLES]
    annual_mean = compute_annual_mean(ds)
    climate_change = compute_climate_change_pattern(annual_mean)

    with dask.diagnostics.ProgressBar():
        annual_mean_bias_2d = compute_bias(annual_mean[VARIABLES_2D]).compute()
        climate_change_bias_2d = compute_bias(climate_change[VARIABLES_2D]).compute()
    spatial_weights = compute_spatial_weights()
    annual_mean_metrics_2d = compute_spatial_metrics(annual_mean_bias_2d, spatial_weights)
    climate_change_metrics_2d = compute_spatial_metrics(climate_change_bias_2d, spatial_weights)

    with dask.diagnostics.ProgressBar():
        annual_mean_bias_3d = compute_zonal_mean_bias(annual_mean[VARIABLES_3D]).compute()
        climate_change_bias_3d = compute_zonal_mean_bias(climate_change[VARIABLES_3D]).compute()
    zonal_weights = compute_zonal_weights(annual_mean_bias_3d.lat, annual_mean_bias_3d.pressure)
    annual_mean_metrics_3d = compute_zonal_metrics(annual_mean_bias_3d, zonal_weights)
    climate_change_metrics_3d = compute_zonal_metrics(climate_change_bias_3d, zonal_weights)

    merged_bias = xr.merge([annual_mean_bias_2d, annual_mean_bias_3d])
    merged_climate_change_bias = xr.merge([climate_change_bias_2d, climate_change_bias_3d])
    merged_metrics = xr.merge([annual_mean_metrics_2d, annual_mean_metrics_3d])
    merged_climate_change_metrics = xr.merge([climate_change_metrics_2d, climate_change_metrics_3d])
    with dask.diagnostics.ProgressBar():
        merged_bias.to_netcdf("annual_mean_bias_v5.nc")
        merged_climate_change_bias.to_netcdf("climate_change_bias_v5.nc")
        merged_metrics.to_netcdf("annual_mean_metrics_v5.nc")
        merged_climate_change_metrics.to_netcdf("climate_change_metrics_v5.nc")
