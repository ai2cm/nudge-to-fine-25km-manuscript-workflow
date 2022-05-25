import json

import cftime
import xarray as xr


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


def open_times(file):
    with open(file, "r") as file:
        timestamps = json.load(file)
    return decode_times(timestamps)
