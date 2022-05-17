import glob
import os
import shutil

import xarray as xr


TILES = range(1, 7)
INPUT_DATA = "/lustre/f2/pdata/gfdl/gfdl_W/fvGFS_INPUT_DATA/"

FILES = glob.glob(os.path.join(INPUT_DATA, "global.v201810", "C48", "20160801.00Z_IC", "*.nc"))
for file in FILES:
    if "sfc_data" not in file:
        print(file)
        shutil.copy(file, ".")

IC = os.path.join(INPUT_DATA, "global.v201810", "C48", "20160801.00Z_IC", "sfc_data.tile{tile}.nc")
PATTERN = "sfc_data.tile{tile}.nc"


for tile in TILES:
    ds = xr.open_dataset(IC.format(tile=tile))
    ds = ds.assign(tsea=ds.tsea + 8.0)
    ds.to_netcdf(f"sfc_data.tile{tile}.nc")
