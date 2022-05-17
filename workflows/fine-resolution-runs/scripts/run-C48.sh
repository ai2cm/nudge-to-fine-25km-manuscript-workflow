#!/bin/tcsh
#SBATCH --output=./stdout/%x.o%j
#SBATCH --qos=urgent
#SBATCH --account=gfdl_w
#SBATCH --time=01:30:00
#SBATCH --clusters=c4
#SBATCH --nodes=1

set echo

set NAME = "C48-0K-baseline"
set NPES = 24
set REFERENCE_CONFIG = /lustre/f2/dev/Spencer.Clark/vulcan/2020-12-15-FV3GFS-baselines/experiment_ymls/C48_0K.yaml
set NUM_TOT = 24

set STEM = "2020-12-15-FV3GFS-baselines"
set SCRATCHROOT    = "${SCRATCH}/${USER}/${STEM}/"
set BUILD_AREA = "~${USER}/fv3gfs-fortran/FV3"

set WORKDIR = ${SCRATCHROOT}/${NAME}
set RUNDIR = ${WORKDIR}/rundir
set LOCAL_CONFIG = $RUNDIR/fv3config.yml
set executable = ${BUILD_AREA}/fv3.exe

# when running with threads, need to use the following command
set run_cmd = "srun --ntasks=$NPES --cpus-per-task=1 ./$executable:t"

setenv MPICH_ENV_DISPLAY
setenv MPICH_MPIIO_CB_ALIGN 2
setenv MALLOC_MMAP_MAX_ 0
setenv MALLOC_TRIM_THRESHOLD_ 536870912
setenv NC_BLKSZ 1M
# necessary for OpenMP when using Intel
setenv KMP_STACKSIZE 256m
setenv SLURM_CPU_BIND verbose


set SCRIPT_AREA = $PWD
#if ( "$PBS_JOBDATE" == "BATCH" | "$PBS_JOBNAME" == "STDIN" ) then
if ( "$SLURM_JOB_NAME" == "sh" ) then
  set SCRIPT = "${SCRIPT_AREA}/$0"
else
  set SCRIPT = "${SCRIPT_AREA}/$SLURM_JOB_NAME"
endif

mkdir -p $WORKDIR/restart
set RST_COUNT = $WORKDIR/restart/rst.count

if ( -f ${RST_COUNT} ) then
  source ${RST_COUNT}
  if ( x"$num" == "x" || ${num} < 1 ) then
    set RESTART_RUN = "F"
  else
    set RESTART_RUN = "T"
  endif
else
  set num = 0
  set RESTART_RUN = "F"
endif

set GET_DATE_DIR = /lustre/f2/dev/Spencer.Clark/vulcan/2020-12-11-FV3GFS-run
set START_DATE = `python $GET_DATE_DIR/get_date.py $REFERENCE_CONFIG $num`
set END_DATE = `python $GET_DATE_DIR/get_date.py --end $REFERENCE_CONFIG $num`

if (${RESTART_RUN} == "F") then

  mkdir -p $RUNDIR
  cp $REFERENCE_CONFIG $LOCAL_CONFIG
  write_run_directory $LOCAL_CONFIG $RUNDIR

else

  set INITIAL_CONDITIONS = $WORKDIR/restart/$START_DATE
  rm -rf $RUNDIR
  mkdir -p $RUNDIR
  cp $REFERENCE_CONFIG $LOCAL_CONFIG
  enable_restart $LOCAL_CONFIG $INITIAL_CONDITIONS
  write_run_directory $LOCAL_CONFIG $RUNDIR

endif

cd $RUNDIR

ls INPUT/
ls RESTART/

cp $executable .

# run the executable
${run_cmd} | tee fms.out || exit

@ num ++
echo "set num = ${num}" >! ${RST_COUNT}

# Move restart files
mkdir -p $WORKDIR/restart/$END_DATE
mv RESTART/* $WORKDIR/restart/$END_DATE/

# Move ascii files
mkdir -p $WORKDIR/history/$START_DATE
mv *.nc $WORKDIR/history/$START_DATE/

# Move history files
mkdir -p $WORKDIR/ascii/$START_DATE
mv *.out *.results *.yml $WORKDIR/ascii/$START_DATE

if ($num < $NUM_TOT) then
  echo "resubmitting... "
  if ( "$SLURM_JOB_NAME" == "sh" ) then
    cd $SCRIPT_AREA
    ./$SCRIPT:t
  else
    cd $SCRIPT_AREA
    sbatch --export=ALL $SCRIPT:t
    sleep 60
  endif
endif
