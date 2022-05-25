# fine-resolution simulations

This directory contains the configuration files and some example scripts for
running the spinup C48 resolution simulations and two-year C384 simulations on
Gaea.  The configuration files and diagnostics tables for each of the runs are
stored in the `c48-spinup-runs` and `c384-runs` directories.

## Contents

The contents of this directory is shown below:

```
├── README.md
├── c384-runs
│   ├── C384_0K.yaml
│   ├── C384_minus_4K.yaml
│   ├── C384_plus_4K.yaml
│   ├── C384_plus_8K.yaml
│   └── diag_table_ml_training
├── c48-spinup-runs
│   ├── C48_0K.yaml
│   ├── C48_minus_4K.yaml
│   ├── C48_plus_4K.yaml
│   ├── C48_plus_8K.yaml
│   └── diag_table_spinup
└── scripts
    ├── add_8k.py
    ├── chgres_cube_C48-to-C384.sh
    ├── get_date.py
    ├── run-C384.sh
    └── run-C48.sh
```

Here the `add_8k.py` script is an example script for adding an SST perturbation to an initial condition from GFS analysis.  This particular example is used to generate the initial conditions for the +8 K climate spinup simulation.  The `get_date.py` script is used by the runscripts, `run-C48.sh` and `run-C384.sh`, while running simulations in a segmented fashion.  Finally, the `chgres_cube_C48-to-C384.sh` script is an example script for converting a C48 set of restart files to a C384 initial condition.  This is used at the end of the spinup simulations to generating spun-up initial conditions for the high-resolution runs.

## Software versions

Some important software versions used in running the simulations described in this directory can be found below:

- The model source code used to run these simulations comes from [this
  branch](https://github.com/ai2cm/fv3gfs-fortran/tree/physics-component-time-average-diags)
  of the fv3gfs-fortran repository.
- The version of fv3config used to write run directories is 0.4.0.
- The `chgres_cube` tool used was compiled by Kai-Yuan Cheng on Gaea and is
  derived from cloning the [UFS_UTILS
  repository](https://github.com/ufs-community/UFS_UTILS) at the commit:
  `d2fab3604d00064a25e4587646efe6aae6f93e95`.
