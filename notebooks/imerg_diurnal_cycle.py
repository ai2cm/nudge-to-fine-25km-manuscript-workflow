import dask.diagnostics
import fsspec
import numpy as np
import pandas as pd
import vcm
import xarray as xr
import xhistogram.xarray as xhistogram


IMERG_DATA = "gs://vcm-ml-experiments/spencerc/2022-05-11-IMERG/NASA-IMERG-30-min-20160101-20161231-180x360.zarr"
LAND_MASK_URL = "gs://vcm-ml-experiments/2021-07-02-reference-precip-bias/land-mask.nc"
HOURS_PER_DAY = 24
RADIUS = 6.371e6


def compute_area(lon, lat, lon_b, lat_b):
    dsinlat = np.sin(np.deg2rad(lat_b)).diff("lat_b").rename({"lat_b": "lat"}).drop("lat")
    dlon = np.deg2rad(lon_b).diff("lon_b").rename({"lon_b": "lon"}).drop("lon")
    return (RADIUS ** 2 * dsinlat * dlon).rename("area")


def shift_longitude_180_to_360(ds, lon_dim="lon", lon_b_dim="lon_b"):
    size = ds.sizes[lon_dim]
    rolled_lon = (ds.lon.roll({lon_dim: size // 2}, roll_coords=False) - 360) % 360
    rolled_dataset = ds.roll({lon_dim: size // 2}, roll_coords=False)
    return rolled_dataset.assign_coords({lon_dim: rolled_lon})


def open_imerg_data(url):
    ds = xr.open_zarr(fsspec.get_mapper(IMERG_DATA))
    ds["precipitationCal"] = HOURS_PER_DAY * ds.precipitationCal
    ds = shift_longitude_180_to_360(ds)
    lon_b = np.arange(0, 360.5, 1)
    ds["lon_b"] = xr.DataArray(lon_b, dims=["lon_b"], coords=[lon_b])
    lat_b = np.arange(-90, 90.01, 1)
    ds["lat_b"] = xr.DataArray(lat_b, dims=["lat_b"], coords=[lat_b])
    return ds


def compute_local_time(longitude, time, time_chunk_size=96):
    offset = (longitude * 24 * 3600 / 360).astype("timedelta64[s]")
    time_as_datetime64 = xr.DataArray(
        time,
        dims=["time"]
    ).chunk({"time": time_chunk_size})
    local_time = (time_as_datetime64 + offset) - (time_as_datetime64 + offset).dt.floor("D")
    return (local_time.rename("local_time") / np.timedelta64(1, "h")).assign_coords(time=time)


def diurnal_cycle(
    precipitation,
    longitude,
    weights,
    time_dim="time",
    spatial_dims=["x", "y", "tile"],
    local_time_bins=np.arange(25)
):
    local_time = compute_local_time(
        longitude,
        precipitation[time_dim],
        time_chunk_size=precipitation.chunks[precipitation.get_axis_num(time_dim)]
    )
    local_time = local_time.broadcast_like(precipitation).rename("local_time")
    weights = weights.broadcast_like(precipitation).rename("weights").where(precipitation.notnull()).fillna(0.0)
    precipitation = precipitation.rename("precipitation").fillna(0.0)
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


def construct_weights(area, land_mask):
    return xr.concat(
        [
            area,
            area.where(land_mask).fillna(0.0),
            area.where(~land_mask).fillna(0.0)
        ],
        dim=pd.Index(
            [
                "global |lat| <= 60",
                "land |lat| <= 60",
                "ocean/sea-ice |lat| <= 60"
            ],
            name="region"
        )
    )


if __name__ == "__main__":
    ds = open_imerg_data(IMERG_DATA)
    area = compute_area(ds.lon, ds.lat, ds.lon_b, ds.lat_b)
    fs, *_ = fsspec.get_fs_token_paths(LAND_MASK_URL)
    land_mask = vcm.open_remote_nc(fs, LAND_MASK_URL).region
    weights = construct_weights(area, land_mask)
    result = diurnal_cycle(
        ds.precipitationCal.chunk({"time": 18}).sel(lat=slice(-60, 60)),
        ds.lon.chunk(),
        weights.chunk({"region": 1}).sel(lat=slice(-60, 60)),
        spatial_dims=["lon", "lat"]
    )
    with dask.diagnostics.ProgressBar():
        result = result.to_netcdf("IMERG-diurnal-cycle.nc")
