import argparse

import cftime
import yaml

import fv3config

parser = argparse.ArgumentParser()
parser.add_argument("config")
parser.add_argument("segment")
parser.add_argument("--end-date", action="store_true")


args, extra_args = parser.parse_known_args()

with open(args.config, "r") as file:
    config = yaml.safe_load(file)

initial_date_tuple = fv3config.config.derive.get_current_date(config)
initial_date = cftime.DatetimeJulian(*initial_date_tuple)

duration = fv3config.get_run_duration(config)

segment = int(args.segment)
if args.end_date:
    segment = segment + 1

date = initial_date + segment * duration
print(date.strftime("%Y%m%d%H"))
