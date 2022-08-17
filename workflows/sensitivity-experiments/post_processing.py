import dataclasses
import datetime
import logging
import os
import typing

import dask.diagnostics
import fsspec
import numpy as np
import pandas as pd
import vcm
import vcm.catalog
import vcm.fv3
import xarray as xr
import xpartition


logging.basicConfig(level=logging.INFO)


TARGET_TIMES = xr.cftime_range("2018-08", "2023-10", freq="MS", calendar="julian")
CLIMATES = ["Minus 4 K", "Unperturbed", "Plus 4 K", "Plus 8 K"]
DESTINATION = fsspec.get_mapper("gs://vcm-ml-experiments/spencerc/2022-08-15-n2f-25-km/post-processed-data-v5.zarr")


def reindex_like_months(ds, times):
    """Input dataset must contain a single value per month.  Order is not
    important.
    """
    reindexed = ds.reindex(time=times)
    for month in range(1, 13):
        reindexed = xr.where(
            reindexed.time.dt.month == month,
            ds.isel(time=ds.time.dt.month == month).squeeze("time"),
            reindexed
        )
    return reindexed


def compute_nudging_precipitation_diagnostics(ds):
    unrectified_nudging_precip = ds.physics_precip - ds.net_moistening_due_to_nudging
    rectified_nudging_precip = xr.where(unrectified_nudging_precip > 0, unrectified_nudging_precip, 0)
    return ds.assign(
        nudging_precip=rectified_nudging_precip,
        unrectified_nudging_precip=unrectified_nudging_precip
    )


def rotate_winds(ds):
    matrix = vcm.catalog.catalog["wind_rotation/c48"].to_dask()
    u, v = vcm.cubedsphere.center_and_rotate_xy_winds(
        matrix,
        ds.x_wind,
        ds.y_wind
    )
    return ds.assign(eastward_wind=u, northward_wind=v).drop(["x_wind", "y_wind"])


@dataclasses.dataclass
class Store:
    url: str
    configuration: str
    climate: str
    variables: typing.List[str]
    rename: typing.Dict[str, str]
    time_offset: typing.Optional[datetime.timedelta] = None
    compute_nudging_precip: typing.Optional[bool] = False
    rotate_winds: typing.Optional[bool] = False

    @property
    def mapper(self):
        return fsspec.get_mapper(self.url)

    def open_raw(self):
        ds = xr.open_zarr(self.mapper)
        ds = vcm.fv3.standardize_fv3_diagnostics(ds)
        if self.time_offset is not None:
            return ds.assign_coords(time=ds.time + self.time_offset)
        else:
            return ds

    def open_variables(self):
        logging.info(f"Opening {self.url}")
        ds = self.open_raw()
        if self.compute_nudging_precip:
            ds = compute_nudging_precipitation_diagnostics(ds)
        ds = ds[self.variables].rename(self.rename)
        ds = ds.assign_coords(climate=self.climate, configuration=self.configuration)
        return ds.expand_dims(["climate", "configuration"])

    def compute_samples_per_month(self, ds):
        samples = xr.ones_like(ds.time, dtype=int).rename("samples")
        samples = samples.assign_coords(configuration=self.configuration)
        samples = samples.expand_dims("configuration")
        freq_str = xr.infer_freq(ds.indexes["time"])
        if freq_str in ["T", "H", "D"]:
            freq_str = f"1{freq_str}"  # pandas requires "1" prepends unit frequencies
        delta = pd.Timedelta(freq_str).to_numpy()
        scale_factor = delta / np.timedelta64(1, "D")
        return scale_factor * samples.resample(time="MS").sum(skipna=False)

    def resample(self, ds):
        samples_per_month = self.compute_samples_per_month(ds)
        ds = ds.resample(time="MS").mean()
        # Allow for some tolerance for missing data (really only needed for nudged
        # runs that are missing a single timestep at the beginning and end months,
        # because they were started an hour into the August 2017).
        mask = np.abs(samples_per_month - samples_per_month.time.dt.days_in_month) < 1.0
        samples_per_month = samples_per_month.time.dt.days_in_month.where(mask)
        ds = ds.assign(samples=samples_per_month)
        ds = ds.where(mask)
        if self.rotate_winds:
            ds = rotate_winds(ds)
        return ds


class CoarseStore(Store):
    def open(self):
        ds = self.open_variables()
        ds = self.resample(ds)
        return ds.reindex(time=TARGET_TIMES)


class FineStore(Store):
    def open(self, time_slice=slice("2018-08", "2019-07")):
        ds = self.open_variables()
        if "tile" in ds.coords:
            ds = ds.drop("tile")
        ds = self.resample(ds)
        ds = ds.sel(time=time_slice)
        return reindex_like_months(ds, TARGET_TIMES)


ML_CORRECTED = {
    "Minus 4 K": {
        "ML-corrected seed 0": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-minus-4k-seed-0/fv3gfs_run",
        "ML-corrected seed 1": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-minus-4k-seed-1/fv3gfs_run",
        "ML-corrected seed 2": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-minus-4k-seed-2/fv3gfs_run",
        "ML-corrected seed 3": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-minus-4k-seed-3/fv3gfs_run",
    },
    "Unperturbed": {
        "ML-corrected seed 0": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-unperturbed-seed-0/fv3gfs_run",
        "ML-corrected seed 1": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-unperturbed-seed-1/fv3gfs_run",
        "ML-corrected seed 2": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-unperturbed-seed-2/fv3gfs_run",
        "ML-corrected seed 3": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-unperturbed-seed-3/fv3gfs_run",
    },
    "Plus 4 K": {
        "ML-corrected seed 0": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-4k-seed-0/fv3gfs_run",
        "ML-corrected seed 1": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-4k-seed-1/fv3gfs_run",
        "ML-corrected seed 2": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-4k-seed-2/fv3gfs_run",
        "ML-corrected seed 3": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-4k-seed-3/fv3gfs_run",
    },
    "Plus 8 K": {
        "ML-corrected seed 0": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-8k-seed-0/fv3gfs_run",
        "ML-corrected seed 1": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-8k-seed-1/fv3gfs_run",
        "ML-corrected seed 2": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-8k-seed-2/fv3gfs_run",
        "ML-corrected seed 3": "gs://vcm-ml-experiments/spencerc/2022-08-04/n2f-25km-ml-corrected-updated-v5-plus-8k-seed-3/fv3gfs_run",
    },
}


BASELINE = {
    "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-minus-4k-snoalb/fv3gfs_run",
    "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-unperturbed-snoalb/fv3gfs_run",
    "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-22/n2f-25km-baseline-plus-4k-snoalb/fv3gfs_run",
    "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-07-01/n2f-25km-baseline-updated-plus-8k-snoalb/fv3gfs_run",
}


TAPES = {
    "sfc_dt_atmos": {
        "variables": ["DSWRFsfc", "USWRFsfc", "DLWRFsfc", "ULWRFsfc", "LHTFLsfc", "SHTFLsfc"],
        "rename": {
            "DSWRFsfc": "downward_shortwave_radiative_flux_at_surface",
            "USWRFsfc": "upward_shortwave_radiative_flux_at_surface",
            "DLWRFsfc": "downward_longwave_radiative_flux_at_surface",
            "ULWRFsfc": "upward_longwave_radiative_flux_at_surface",
            "LHTFLsfc": "latent_heat_flux",
            "SHTFLsfc": "sensible_heat_flux"
        },
        "time_offset": datetime.timedelta(hours=-12)
    },
    "atmos_dt_atmos": {
        "variables": ["PWAT"],
        "rename": {
            "PWAT": "precipitable_water",
        }
    },
    "diags": {
        "variables": ["total_precipitation_rate"],
        "rename": {}
    },
    "state_after_timestep": {
        "variables": ["surface_temperature", "air_temperature", "specific_humidity", "pressure_thickness_of_atmospheric_layer", "eastward_wind", "northward_wind"],
        "rename": {}
    },
}


NUDGED = {
    "Minus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-minus-4k-snoalb/fv3gfs_run",
    "Unperturbed": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-unperturbed-snoalb/fv3gfs_run",
    "Plus 4 K": "gs://vcm-ml-experiments/spencerc/2022-01-19/n2f-25km-plus-4k-snoalb/fv3gfs_run",
    "Plus 8 K": "gs://vcm-ml-experiments/spencerc/2022-06-14/n2f-25km-updated-plus-8k-snoalb/fv3gfs_run"
}


NUDGED_TAPES = {
    "sfc_dt_atmos": {
        "variables": ["ULWRFsfc", "LHTFLsfc", "SHTFLsfc", "DSWRFsfc_from_RRTMG", "USWRFsfc_from_RRTMG", "DLWRFsfc_from_RRTMG", "TMPsfc"],
        "rename": {
            "ULWRFsfc": "upward_longwave_radiative_flux_at_surface",
            "LHTFLsfc": "latent_heat_flux",
            "SHTFLsfc": "sensible_heat_flux",
            "DSWRFsfc_from_RRTMG": "downward_shortwave_radiative_flux_at_surface",
            "USWRFsfc_from_RRTMG": "upward_shortwave_radiative_flux_at_surface",
            "DLWRFsfc_from_RRTMG": "downward_longwave_radiative_flux_at_surface",
            "TMPsfc": "surface_temperature",
        },
        "time_offset": datetime.timedelta(hours=-1, minutes=-30)
    },
    "atmos_dt_atmos": {
        "variables": ["PWAT"],
        "rename": {
            "PWAT": "precipitable_water",
        }
    },
    "diags": {
        "variables": ["unrectified_nudging_precip"],
        "rename": {"unrectified_nudging_precip": "total_precipitation_rate"},
        "compute_nudging_precip": True
    },
    "state_after_timestep": {
        "variables": ["air_temperature", "specific_humidity", "pressure_thickness_of_atmospheric_layer", "eastward_wind", "northward_wind"],
        "rename": {}
    },
}


FINE_RES = {
    "Minus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/minus-4K/C384-to-C48-diagnostics",
    "Unperturbed": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/unperturbed/C384-to-C48-diagnostics",
    "Plus 4 K": "gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations/plus-4K/C384-to-C48-diagnostics",
    "Plus 8 K": "gs://vcm-ml-raw-flexible-retention/2022-06-02-two-year-C384-FV3GFS-simulations/plus-8K/C384-to-C48-diagnostics"
}


FINE_RES_TAPES = {
    "atmos_8xdaily_coarse_interpolated": {"variables": ["PWAT"], "rename": {"PWAT": "precipitable_water"}},
    "gfsphysics_15min_coarse": {
        "variables": ["DSWRFsfc", "DLWRFsfc", "USWRFsfc", "ULWRFsfc", "PRATEsfc", "LHTFLsfc", "SHTFLsfc", "tsfc"],
        "rename": {
            "DSWRFsfc": "downward_shortwave_radiative_flux_at_surface",
            "USWRFsfc": "upward_shortwave_radiative_flux_at_surface",
            "DLWRFsfc": "downward_longwave_radiative_flux_at_surface",
            "ULWRFsfc": "upward_longwave_radiative_flux_at_surface",
            "LHTFLsfc": "latent_heat_flux",
            "SHTFLsfc": "sensible_heat_flux",
            "PRATEsfc": "total_precipitation_rate",
            "tsfc": "surface_temperature"
        },
        "time_offset": datetime.timedelta(minutes=-7, seconds=-30)
    }
}


REFERENCE_TAPES = {
    "reference_state": {
        "variables": ["air_temperature_reference", "specific_humidity_reference", "pressure_thickness_of_atmospheric_layer_reference", "x_wind_reference", "y_wind_reference"],
        "rename": {
            "air_temperature_reference": "air_temperature",
            "specific_humidity_reference": "specific_humidity",
            "pressure_thickness_of_atmospheric_layer_reference": "pressure_thickness_of_atmospheric_layer",
            "x_wind_reference": "x_wind",
            "y_wind_reference": "y_wind"
        },
        "rotate_winds": True
    }
}


if __name__ == "__main__":
    stores = []
    for climate in ML_CORRECTED:
        for configuration in ML_CORRECTED[climate]:
            root = ML_CORRECTED[climate][configuration]
            for tape, kwargs in TAPES.items():
                url = os.path.join(root, f"{tape}.zarr")
                store = CoarseStore(url, configuration, climate, **kwargs)
                stores.append(store)

    result = xr.combine_by_coords([s.open() for s in stores])
    result = result.chunk({"time": "auto", "configuration": 1, "climate": 1})
    result = result.sel(climate=CLIMATES)  # Ensure climates are ordered from coldest to warmest

    result.partition.initialize_store(DESTINATION)
    ranks = 96
    for i in range(ranks):
        logging.info(f"Writing rank {i + 1} / {ranks}")
        with dask.diagnostics.ProgressBar():
            result.partition.write(DESTINATION, ranks, ["climate", "configuration", "time"], i)
